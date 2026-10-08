"""
GitHub Actions 전용 adapter.
환경변수로 설정을 받고 $GITHUB_OUTPUT에 결과를 기록.
"""
import json
import os
import sys
from pathlib import Path

from drift_gate.adapters.inspection import inspect as run
from drift_gate.adapters.github.client import GitHubAdapter, parse_drift_ignores
from drift_gate.adapters.claude.enricher import ClaudeEnricher
from drift_gate.adapters.history.store import append_result
from drift_gate.core.policy.loader import PolicyLoadError
from drift_gate.reporters.markdown import MarkdownReporter
from drift_gate.reporters.html import HtmlReporter


def main() -> None:
    contract_proofs = os.environ.get('CONTRACT_PROOFS','false').strip().lower()
    if contract_proofs not in {'true','false'}:
        raise ValueError('CONTRACT_PROOFS must be true or false')
    token         = _require_env("GITHUB_TOKEN")
    repo          = _require_env("REPO")
    pr_number     = int(_require_env("PR_NUMBER"))
    runner_temp   = os.environ.get("RUNNER_TEMP", "/tmp")
    from drift_gate.adapters.execution import identity
    from drift_gate.adapters.run_coordinator import RunController
    execution = identity()
    run_store = Path(runner_temp) / "drift-gate-runs"
    controller = RunController(run_store, run_id=execution['run_id'])
    post_comment = os.environ.get("POST_COMMENT", "true").lower() == "true"
    controller.start(data={'command': 'github-action', 'mode': 'github-pr', 'repo': repo, 'pr': pr_number,
                           'publication_target': 'pr-comment' if post_comment else None})
    _write_github_output({"run_id": execution['run_id'],
                          "run_record_path": str(controller.journal.path)})
    try:
        _main(controller, execution, token=token, repo=repo, pr_number=pr_number,
              runner_temp=runner_temp, contract_proofs=contract_proofs, post_comment=post_comment)
    except BaseException as exc:
        view = controller.view()
        from drift_gate.core.execution.lifecycle import STAGES
        early = view is not None and view.state in STAGES and STAGES.index(view.state) < STAGES.index('analyzing')
        state = ('cancelled' if isinstance(exc, KeyboardInterrupt) else
                 'rejected-input' if early and isinstance(exc, (ValueError, OSError, PolicyLoadError))
                 else 'internal-error')
        controller.fail(state, type(exc).__name__, exc)
        raise


def _main(controller, execution, *, token, repo, pr_number, runner_temp, contract_proofs, post_comment):
    policy_file   = os.environ.get("POLICY_FILE", ".drift-gate.yml")
    workspace     = os.environ.get("GITHUB_WORKSPACE", os.getcwd())
    policy_path   = Path(policy_file)
    if not policy_path.is_absolute():
        policy_path = Path(workspace) / policy_path
    model         = os.environ.get("MODEL", "claude-opus-4-6")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    history_path   = Path(runner_temp) / "drift_gate_history.jsonl"
    artifact_name  = "drift-gate-report"
    is_fork_pr     = _is_fork_pr(os.environ.get("GITHUB_EVENT_PATH", ""), repo)
    controller.advance('validated')

    _log(f"변경 파일 수집 중 (PR #{pr_number})...")
    gh = GitHubAdapter(token=token, repo=repo)
    changed_files, pr_body = gh.get_pr_files_and_body(pr_number)
    drift_ignores = parse_drift_ignores(pr_body)
    _log(f"변경 파일: {len(changed_files)}개 | drift-ignore: {len(drift_ignores)}개")
    if is_fork_pr:
        _log("Fork PR detected: disabling optional enrichment and PR comment posting for safety")
        anthropic_key = ""
        post_comment = False

    _log(f"정책 평가 중 ({policy_path})...")
    try:
        from drift_gate.adapters.policy_loader import read_policy, require_check_policy
        policy_source, _policy_obj = read_policy(policy_path)
        require_check_policy(_policy_obj)
        from drift_gate.adapters.github.approvals import verify_ignores
        drift_ignores = verify_ignores(gh, pr_number, drift_ignores, _policy_obj, changed_files)
        changed_files = gh.attach_env_documents(pr_number, changed_files, _policy_obj)
        head_oid = getattr(gh, '_snapshot_head', None)
        controller.advance('captured', changed_files=len(changed_files), head_oid=head_oid,
                           capture_scope='github-api-collection; inspection snapshot sealed inside the engine call')
        for _w in _policy_obj.load_warnings:
            print(f"::warning title=Drift Gate policy warning::{_escape_workflow_command(_w)}", file=sys.stderr)
        controller.advance('planned', rules=len(_policy_obj.rules), contract_proofs=contract_proofs == 'true')
        controller.advance('analyzing')
        result = run(
            changed_files=changed_files,
            drift_ignores=drift_ignores,
            policy=_policy_obj,
            policy_source=policy_source, policy_path=policy_path,
            provenance={"source": "github-pr", "repository": repo, "pr_number": pr_number},
            contract_proofs=contract_proofs == 'true', execution=execution,
        )
    except Exception as exc:
        _write_github_output({"result": "fail", "policy_error": str(exc)})
        print(f"::error title=Drift Gate policy error::{_escape_workflow_command(str(exc))}", file=sys.stderr)
        raise
    controller.advance('evaluated', gate_result=result.result, input_sha256=result.execution.get('input_sha256'))
    from drift_gate.adapters.run_coordinator import result_digest
    base_result_sha256 = result_digest(result.to_dict())
    controller.advance('result-validated', result_sha256=base_result_sha256, gate_result=result.result)

    # Claude 보강 (선택적 — 실패해도 fallback checklist 유지)
    if anthropic_key and result.violations and not result.skip:
        _log(f"Claude API 호출 중 (모델: {model})...")
        try:
            result = ClaudeEnricher(api_key=anthropic_key, model=model).enrich(result)
        except Exception as e:
            _log(f"WARNING: Claude API 실패, fallback checklist 사용 ({e})")

    # 리포트 저장
    md_path   = Path(runner_temp) / "drift_gate_report.md"
    json_path = Path(runner_temp) / "drift_gate_report.json"
    html_path = Path(runner_temp) / "drift_gate_report.html"

    run_id   = os.environ.get("GITHUB_RUN_ID", "")
    md_base  = MarkdownReporter().render(result)
    artifact_footer = _artifact_footer(repo, run_id, artifact_name)
    md       = md_base + artifact_footer
    html_report = HtmlReporter().render(
        result,
        policy_source=policy_source,
    )
    md_path.write_text(md, encoding="utf-8")
    html_path.write_text(html_report, encoding="utf-8")
    json_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    controller.advance('persisted', report_json=str(json_path),
                       persistence='runner-temp-reports; durable only if the workflow uploads the artifact')
    _write_job_summary(md)
    _write_job_summary(
        f"\n\nArtifact: `{artifact_name}` contains Markdown, JSON, HTML, and history reports.\n"
    )
    _log(f"리포트 저장: {md_path} | {json_path} | {html_path}")

    # GitHub Actions 출력 변수
    artifact_url = (
        f"https://github.com/{repo}/actions/runs/{run_id}/artifacts"
        if run_id else ""
    )
    _write_github_output({
        "result":          result.result,
        "blocker_count":   str(result.blocker_count),
        "major_count":     str(result.major_count),
        "violation_count": str(len(result.violations)),
        "markdown_report_path": str(md_path),
        "json_report_path": str(json_path),
        "html_report_path": str(html_path),
        "history_path": str(history_path),
        "artifact_name": artifact_name,
        "html_artifact_hint": f"{artifact_name}/drift_gate_report.html",
        "artifact_url": artifact_url,
    })

    _log(
        f"결과: {result.result.upper()} | "
        f"BLOCKER={result.blocker_count} MAJOR={result.major_count} "
        f"MINOR={result.minor_count} NIT={result.nit_count}"
    )
    _write_annotations(result)
    append_result(
        result,
        history_path,
        source="github-action",
        pr_number=pr_number,
        commit_sha=os.environ.get("GITHUB_SHA", ""),
        changed_file_count=len(changed_files),
        release=os.environ.get("GITHUB_REF_NAME", ""),
    )

    if post_comment:
        record = _publish_comment(controller, token=token, repo=repo, pr_number=pr_number, body=md,
                                  head_oid=head_oid, result_sha256=base_result_sha256, runner_temp=runner_temp)
        if record.get('url') and record.get('published'):
            _log(f"PR comment 게시: {record['url']} ({record['state']})")
            _write_github_output({"comment_url": record['url']})
    else:
        from drift_gate.adapters.execution import atomic_json
        skipped = {'schema': 'pr-comment-publication-record-v1', 'state': 'publication-skipped',
                   'reason': 'fork-pr' if is_fork_pr else 'post-comment-disabled', 'published': False}
        record_path = Path(runner_temp) / "drift_gate_publication.json"
        atomic_json(record_path, skipped)
        _write_github_output({"publication_record_path": str(record_path), "publication_state": skipped['state']})
        controller.advance('publication-skipped', publication=skipped)

    # 콘솔 출력 (Actions 로그에 표시)
    print(md)


def _publish_comment(controller, *, token, repo, pr_number, body, head_oid, result_sha256, runner_temp,
                     api=None):
    from drift_gate.adapters.execution import atomic_json
    from drift_gate.adapters.github import publication
    record_path = Path(runner_temp) / "drift_gate_publication.json"
    _write_github_output({"publication_record_path": str(record_path)})
    try:
        ident = publication.identity(
            repo=repo, pr_number=pr_number, head_oid=head_oid or '',
            workflow_ref=os.environ.get('GITHUB_WORKFLOW_REF', ''), run_id=os.environ.get('GITHUB_RUN_ID', ''),
            run_number=int(os.environ.get('GITHUB_RUN_NUMBER') or 0),
            run_attempt=int(os.environ.get('GITHUB_RUN_ATTEMPT') or 0), result_sha256=result_sha256)
    except ValueError as exc:
        # Without a commit and run order the comment cannot be fenced; do not post.
        record = {'schema': 'pr-comment-publication-record-v1', 'state': 'publication-rejected',
                  'reason': f'publication-identity-unavailable: {exc}', 'published': False}
        controller.advance('publish-pending', publication={'state': 'publish-pending', 'kind': 'pr-comment'})
        controller.advance('publication-rejected', publication=record)
        atomic_json(record_path, record)
        _write_github_output({"publication_state": record['state']})
        _log(f"WARNING: PR comment not posted ({record['reason']})")
        return record
    controller.advance('publish-pending', publication={'state': 'publish-pending', 'kind': 'pr-comment',
                                                       'idempotency_key': ident['key']})
    record = publication.publish(api or publication.CommentApi(token, repo), pr_number=pr_number,
                                 body=body, ident=ident)
    record.setdefault('published', False)
    atomic_json(record_path, record)
    summary = {k: record.get(k) for k in ('state', 'reason', 'comment_id', 'idempotency_key', 'body_sha256',
                                          'head_before', 'head_after', 'race_window')}
    controller.advance(record['state'], publication=summary)
    _write_github_output({"publication_state": record['state']})
    if record['state'] != 'published':
        print(f"::warning title=Drift Gate publication::{_escape_workflow_command(record['state'] + ': ' + record['reason'])}",
              file=sys.stderr)
    return record


def _require_env(name: str) -> str:
    val = os.environ.get(name, "")
    if not val:
        print(f"ERROR: 환경변수 {name}이 필요합니다.", file=sys.stderr)
        sys.exit(1)
    return val


def _log(msg: str) -> None:
    print(f"[drift-gate] {msg}", file=sys.stderr)


def _write_github_output(values: dict) -> None:
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if not github_output:
        return
    with open(github_output, "a", encoding="utf-8") as f:
        for k, v in values.items():
            f.write(f"{k}={v}\n")


def _is_fork_pr(event_path: str, repo: str) -> bool:
    if not event_path:
        return False
    path = Path(event_path)
    if not path.exists():
        return False
    try:
        event = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    pr = event.get("pull_request") or {}
    head_repo = ((pr.get("head") or {}).get("repo") or {}).get("full_name")
    base_repo = ((pr.get("base") or {}).get("repo") or {}).get("full_name") or repo
    return bool(head_repo and base_repo and head_repo != base_repo)


def _write_job_summary(markdown: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as f:
        f.write(markdown)
        f.write("\n")


def _write_annotations(result) -> None:
    for violation in result.violations:
        title = _escape_workflow_command(f"Drift Gate: {violation.rule_id}")
        message = _escape_workflow_command(
            violation.message or "Contract docs are not synced with this change."
        )
        if violation.trigger_files:
            for file in violation.trigger_files:
                path = _escape_workflow_command(file.path)
                print(
                    f"::error file={path},title={title}::{message}",
                    file=sys.stderr,
                )
        else:
            print(f"::error title={title}::{message}", file=sys.stderr)

    for rejected in result.rejected_ignores:
        rule_id = _escape_workflow_command(rejected.rule_id)
        reason = _escape_workflow_command(rejected.reason)
        print(
            f"::warning title=Rejected drift-ignore::{rule_id}: {reason}",
            file=sys.stderr,
        )


def _artifact_footer(repo: str, run_id: str, artifact_name: str) -> str:
    """Return a Markdown footer with a clickable link to the HTML artifact."""
    if not run_id:
        return ""
    url = f"https://github.com/{repo}/actions/runs/{run_id}/artifacts"
    return (
        f"\n\n---\n"
        f"[View HTML report]({url}) "
        f"&middot; Artifact: `{artifact_name}/drift_gate_report.html`\n"
    )


def _escape_workflow_command(value: str) -> str:
    return (
        value.replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
        .replace(":", "%3A")
        .replace(",", "%2C")
    )


if __name__ == "__main__":
    main()
