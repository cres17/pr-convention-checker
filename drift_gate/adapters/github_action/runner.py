"""
GitHub Actions 전용 adapter.
환경변수로 설정을 받고 $GITHUB_OUTPUT에 결과를 기록.
"""
import json
import os
import sys
from pathlib import Path

from drift_gate.core.engine import run
from drift_gate.adapters.github.client import GitHubAdapter, parse_drift_ignores
from drift_gate.adapters.claude.enricher import ClaudeEnricher
from drift_gate.reporters.markdown import MarkdownReporter
from drift_gate.reporters.json_reporter import JsonReporter


def main() -> None:
    token        = _require_env("GITHUB_TOKEN")
    repo         = _require_env("REPO")
    pr_number    = int(_require_env("PR_NUMBER"))
    policy_file  = os.environ.get("POLICY_FILE", ".drift-gate.yml")
    model        = os.environ.get("MODEL", "claude-opus-4-6")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    runner_temp  = os.environ.get("RUNNER_TEMP", "/tmp")

    _log(f"변경 파일 수집 중 (PR #{pr_number})...")
    gh = GitHubAdapter(token=token, repo=repo)
    changed_files, pr_body = gh.get_pr_files_and_body(pr_number)
    drift_ignores = parse_drift_ignores(pr_body)
    _log(f"변경 파일: {len(changed_files)}개 | drift-ignore: {len(drift_ignores)}개")

    _log(f"정책 평가 중 ({policy_file})...")
    result = run(
        changed_files=changed_files,
        drift_ignores=drift_ignores,
        policy_path=policy_file,
    )

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

    md = MarkdownReporter().render(result)
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _log(f"리포트 저장: {md_path} | {json_path}")

    # GitHub Actions 출력 변수
    _write_github_output({
        "result":          result.result,
        "blocker_count":   str(result.blocker_count),
        "major_count":     str(result.major_count),
        "violation_count": str(len(result.violations)),
    })

    _log(
        f"결과: {result.result.upper()} | "
        f"BLOCKER={result.blocker_count} MAJOR={result.major_count} "
        f"MINOR={result.minor_count} NIT={result.nit_count}"
    )

    # 콘솔 출력 (로그에 표시)
    print(md)


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


if __name__ == "__main__":
    main()
