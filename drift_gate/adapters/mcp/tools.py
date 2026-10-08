"""Small callable helpers for future MCP servers or agent connectors."""
from pathlib import Path

from drift_gate.adapters.git.client import GitAdapter
from drift_gate.adapters.github.client import GitHubAdapter, parse_drift_ignores
from drift_gate.adapters.history.store import (
    DEFAULT_HISTORY_PATH,
    load_records,
    summarize_records,
)
from drift_gate.adapters.inspection import inspect as run
from drift_gate.adapters.policy_loader import load_policy, read_policy, require_check_policy
from drift_gate.adapters.execution import identity
from drift_gate.reporters.json_reporter import JsonReporter


DEFAULT_TOKEN_BUDGET = 1200


def drift_gate_check_git(*, base: str, head: str, trusted_policy_ref: str,
                         trusted_policy_sha256: str, policy_path: str = '.drift-gate.yml',
                         comparison_mode: str = 'commit', mode: str = 'compact',
                         token_budget: int = DEFAULT_TOKEN_BUDGET, contract_proofs: bool = False) -> dict:
    """Inspect immutable Git objects with an explicit caller policy anchor."""
    from drift_gate.adapters.git.immutable import collect_git_snapshot
    from drift_gate.adapters.inspection import inspect_snapshot
    snapshot = collect_git_snapshot(root=Path.cwd(), base=base, head=head,
        trusted_policy_ref=trusted_policy_ref, trusted_policy_sha256=trusted_policy_sha256,
        policy_path=policy_path, comparison_mode=comparison_mode, contract_proofs=contract_proofs)
    result = inspect_snapshot(snapshot)
    return _render_for_agent(result, changed_files=result.inspected_files, mode=mode, token_budget=token_budget)


def drift_gate_check_local(
    *,
    base: str = "HEAD",
    policy_path: str = ".drift-gate.yml",
    mode: str = "compact",
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    contract_proofs: bool = False,
) -> dict:
    execution = identity()
    source, policy = read_policy(policy_path)
    require_check_policy(policy)
    git = GitAdapter()
    changed_files = git.get_changed_files(base)
    # Local runs cannot manufacture GitHub approval evidence.
    from drift_gate.adapters.docs.content import attach_env_documents, local_document_reader
    changed_files = attach_env_documents(changed_files, policy, local_document_reader(git.repo_root or Path.cwd()))
    result = run(changed_files=changed_files, policy=policy, execution=execution,
        policy_source=source, policy_path=policy_path,
        provenance={"source": "local-git", **getattr(git, "provenance", {})},contract_proofs=contract_proofs)
    return _render_for_agent(
        result,
        changed_files=result.inspected_files,
        mode=mode,
        token_budget=token_budget,
    )


def drift_gate_check_pr(
    pr_number: int,
    *,
    repo: str,
    token: str,
    policy_path: str = ".drift-gate.yml",
    mode: str = "compact",
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    contract_proofs: bool = False,
) -> dict:
    execution = identity()
    source, policy = read_policy(policy_path)
    require_check_policy(policy)
    github = GitHubAdapter(token=token, repo=repo)
    changed_files, pr_body = github.get_pr_files_and_body(pr_number)
    from drift_gate.adapters.github.approvals import verify_ignores
    from drift_gate.adapters.execution import digest
    from drift_gate.adapters.github_action.runner import _approval_context
    directives = verify_ignores(github, pr_number, parse_drift_ignores(pr_body), policy, changed_files,
                                policy_sha256=digest(source))
    changed_files = github.attach_env_documents(pr_number, changed_files, policy)
    result = run(
        changed_files=changed_files,
        drift_ignores=directives,
        policy=policy,
        execution=execution, policy_source=source, policy_path=policy_path,
        provenance={"source": "github-pr", "repository": repo, "pr_number": pr_number},
        contract_proofs=contract_proofs,
        context=_approval_context(getattr(github, '_snapshot_head', None), digest(source), directives),
    )
    return _render_for_agent(
        result,
        changed_files=result.inspected_files,
        mode=mode,
        token_budget=token_budget,
    )


def drift_gate_get_evidence(
    *,
    base: str = "HEAD",
    policy_path: str = ".drift-gate.yml",
    rule_id: str = "",
    max_files: int = 5,
    max_lines_per_file: int = 20,
) -> dict:
    """Return bounded diff evidence for one rule after the compact check."""
    execution = identity()
    source, policy = read_policy(policy_path)
    require_check_policy(policy)
    git = GitAdapter()
    changed_files = git.get_changed_files(base)
    from drift_gate.adapters.docs.content import attach_env_documents, local_document_reader
    changed_files = attach_env_documents(changed_files, policy, local_document_reader(git.repo_root or Path.cwd()))
    result = run(changed_files=changed_files, policy=policy, execution=execution,
        policy_source=source, policy_path=policy_path,
        provenance={"source": "local-git", **getattr(git, "provenance", {})})
    violations = [
        violation for violation in result.violations
        if not rule_id or violation.rule_id == rule_id
    ]
    evidence = []
    for violation in violations:
        files = []
        for file in violation.trigger_files[:max_files]:
            files.append({
                "path": file.path,
                "status": file.status,
                "semantic_signals": file.semantic_signals,
                "semantic_evidence": file.semantic_evidence,
                "diff_snippet": _diff_snippet(file.patch, max_lines_per_file),
            })
        evidence.append({
            "rule_id": violation.rule_id,
            "severity": violation.severity,
            "files": files,
        })
    return {
        "evidence": evidence,
        "execution": result.execution,
        "verification": result.verification,
        "verification_limits": _verification_limits(result, rule_id),
        "token_strategy": "bounded evidence only; call with rule_id for narrower output",
    }


def drift_gate_list_rules(policy_path: str = ".drift-gate.yml") -> list[dict]:
    policy = load_policy(policy_path)
    return [
        {
            "id": rule.id,
            "severity": rule.severity,
            "message": rule.message,
            "when": rule.when.any_changed,
            "min_change_intensity": rule.when.min_change_intensity,
            "require": {"groups": [{"name": g.name, "any_changed": g.any_changed,
                "all_changed": g.all_changed, "required": g.required, "content": g.content}
                for g in rule.require.groups],
                "cross_file": [{"name": r.name, "when_any_changed": r.when_any_changed,
                    "require_groups": r.require_groups} for r in rule.require.cross_file]},
            "on_unverified": policy.gate.on_unverified,
        }
        for rule in policy.rules
    ]


def drift_gate_explain_rule(
    rule_id: str,
    policy_path: str = ".drift-gate.yml",
) -> dict:
    rules = drift_gate_list_rules(policy_path)
    for rule in rules:
        if rule["id"] == rule_id:
            return rule
    raise KeyError(f"rule not found: {rule_id}")


def drift_gate_suggest_policy(repo_root: str = ".") -> dict:
    root = Path(repo_root)
    suggestions = []
    if (root / "prisma" / "schema.prisma").exists() or (root / "db").exists():
        suggestions.append("db")
    if (root / "src" / "routes").exists() or (root / "app" / "api").exists():
        suggestions.append("api")
    if (root / ".github" / "workflows").exists():
        suggestions.append("ci")
    if (root / ".env.example").exists() or (root / "config").exists():
        suggestions.append("env")
    return {"suggested_presets": suggestions or ["fullstack"]}


def drift_gate_history(
    days: int = 30,
    *,
    path: str = DEFAULT_HISTORY_PATH,
    rule_id: str = "",
) -> dict:
    records = load_records(path, days=days, rule_id=rule_id)
    return {
        "records": records,
        "summary": summarize_records(records),
    }


def drift_gate_prepare_fix_plan(
    *,
    base: str = "HEAD",
    policy_path: str = ".drift-gate.yml",
) -> dict:
    report = drift_gate_check_local(base=base, policy_path=policy_path, mode="compact")
    actions = []
    for violation in report.get("violations", []):
        targets = []
        for group in violation.get("unsatisfied_groups", violation.get("missing", [])):
            targets.extend(group.get("required", []))
        actions.append({
            "rule_id": violation["rule_id"],
            "severity": violation["severity"],
            "suggested_targets": sorted(set(targets)),
            "trigger_files": _trigger_file_paths(violation.get("trigger_files", [])),
        })
    return {
        "result": report.get("result"),
        "execution": report.get("execution", {}),
        "actions": actions,
        "verification": report.get("verification"),
        "verification_limits": report.get("verification_limits", []),
        "deterministic": True,
    }


def _render_for_agent(
    result,
    *,
    changed_files,
    mode: str,
    token_budget: int,
) -> dict:
    if mode == "full":
        return JsonReporter().render(result)
    if mode != "compact":
        raise ValueError("mode must be 'compact' or 'full'")
    return _compact_result(result, changed_files, token_budget=max(200, token_budget))


def _verification_limits(result, rule_id=""):
    return [{"rule_id": d.rule_id, "decision": d.decision, "verification": d.verification,
        "reasons": [g.evidence for g in d.satisfied_groups + d.unsatisfied_groups if g.verification in {"partial", "unverified"}]}
        for d in result.rule_decisions if d.verification in {"partial", "unverified"} and (not rule_id or d.rule_id == rule_id)]


def _compact_result(result, changed_files, *, token_budget: int) -> dict:
    violations = [_compact_violation(v) for v in result.violations]
    execution = dict(result.execution)
    if 'input_capture' in execution:
        capture = dict(execution['input_capture'])
        capture['artifact_count'] = len(capture.pop('artifacts'))
        capture['manifest_entries_omitted'] = True
        if 'git_input' in capture:
            git_input = dict(capture['git_input'])
            git_input['artifact_count'] = len(git_input.pop('artifacts'))
            git_input['manifest_entries_omitted'] = True
            capture['git_input'] = git_input
        execution['input_capture'] = capture
    payload = {
        "schema_version": 3,
        "verification": result.verification,
        "result": result.result,
        "execution": execution,
        "summary": result.to_dict()["summary"],
        "change_types": result.change_types,
        "scan_metrics": {
            "scanned_files": result.scan_metrics.scanned_files,
            "skipped_ignored_files": result.scan_metrics.skipped_ignored_files,
            "evaluated_rules": result.scan_metrics.evaluated_rules,
        },
        "violations": violations,
        "verification_limits": _verification_limits(result),
        "skipped_rules": [s.to_dict() for s in result.skipped_rules],
        "rejected_ignores": [r.to_dict() for r in result.rejected_ignores],
        "changed_file_index": _changed_file_index(changed_files, limit=80),
        "next_tools": [
            "drift_gate_get_evidence(rule_id=...) for bounded diff snippets",
            "drift_gate_explain_rule(rule_id=...) for policy details",
            "drift_gate_prepare_fix_plan() for target docs to update",
            "rerun check with mode='full' only when raw JSON is required",
        ],
        "token_strategy": {
            "mode": "compact",
            "estimated_token_budget": token_budget,
            "omitted": ["raw patches", "full trigger file dicts", "rule_decisions"],
        },
    }
    if result.contract_diagnostics is not None:
        payload['contract_diagnostics'] = result.contract_diagnostics.to_dict(compact=True)
    return _budget_payload(payload, token_budget)


def _compact_violation(violation) -> dict:
    return {
        "rule_id": violation.rule_id,
        "severity": violation.severity,
        "confidence": violation.confidence,
        "message": violation.message,
        "change_type": violation.change_type,
        "change_intensity": violation.change_intensity,
        "trigger_files": [f.path for f in violation.trigger_files[:12]],
        "missing": [
            {
                "name": group.name,
                "type": group.type,
                "required": group.required,
            }
            for group in violation.unsatisfied_groups
        ],
        "checklist": violation.checklist[:5],
        "blast_radius": violation.blast_radius[:8],
    }


def _changed_file_index(changed_files, *, limit: int) -> list[dict]:
    return [
        {
            "path": file.path,
            "status": file.status,
            "signals": file.semantic_signals,
        }
        for file in changed_files[:limit]
    ]


def _budget_payload(payload: dict, token_budget: int) -> dict:
    """Approximate token budget with a conservative 4 chars/token estimate."""
    text = __import__("json").dumps(payload, ensure_ascii=False)
    max_chars = token_budget * 4
    if len(text) <= max_chars:
        payload["token_strategy"]["truncated"] = False
        return payload

    budgeted = dict(payload)
    # Inspection identity and omitted-input counts survive compacting. Paths may
    # be bounded, but an agent must still know the complete omission count.
    budgeted["execution"] = dict(payload["execution"])
    untracked = budgeted["execution"].get("untracked_skipped", [])
    if len(untracked) > 5:
        budgeted["execution"]["untracked_skipped"] = untracked[:5]
        budgeted["execution"]["untracked_skipped_truncated"] = True
    budgeted["changed_file_index"] = payload["changed_file_index"][:20]
    budgeted["violations"] = payload["violations"][:5]
    if 'contract_diagnostics' in payload:
        diagnostics = dict(payload['contract_diagnostics'])
        diagnostics['omitted_entry_count'] = len(diagnostics['entries'])
        diagnostics['entries'] = []
        diagnostics['display_truncated'] = True
        budgeted['contract_diagnostics'] = diagnostics
    budgeted["token_strategy"] = dict(payload["token_strategy"])
    budgeted["token_strategy"]["truncated"] = True
    budgeted["token_strategy"]["reason"] = "compact response exceeded token_budget"
    return budgeted


def _diff_snippet(patch: str, max_lines: int) -> str:
    if not patch:
        return ""
    lines = []
    for raw in patch.splitlines():
        if raw.startswith(("diff --git", "index ")):
            continue
        if raw.startswith(("+++", "---", "@@", "+", "-")):
            lines.append(raw)
        if len(lines) >= max_lines:
            break
    return "\n".join(lines)


def _trigger_file_paths(files: list) -> list[str]:
    paths = []
    for file in files:
        if isinstance(file, str):
            paths.append(file)
        elif isinstance(file, dict) and "path" in file:
            paths.append(file["path"])
    return paths
