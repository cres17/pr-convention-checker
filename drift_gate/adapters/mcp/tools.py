"""Small callable helpers for future MCP servers or agent connectors."""
from pathlib import Path

from drift_gate.adapters.ast.analyzer import enrich_semantic_signals
from drift_gate.adapters.git.client import GitAdapter
from drift_gate.adapters.github.client import GitHubAdapter, parse_drift_ignores
from drift_gate.adapters.history.store import (
    DEFAULT_HISTORY_PATH,
    load_records,
    summarize_records,
)
from drift_gate.core.engine import run
from drift_gate.adapters.policy_loader import load_policy
from drift_gate.reporters.json_reporter import JsonReporter


DEFAULT_TOKEN_BUDGET = 1200


def drift_gate_check_local(
    *,
    base: str = "HEAD",
    policy_path: str = ".drift-gate.yml",
    mode: str = "compact",
    token_budget: int = DEFAULT_TOKEN_BUDGET,
) -> dict:
    changed_files = enrich_semantic_signals(GitAdapter().get_changed_files(base))
    policy = load_policy(policy_path)
    result = run(changed_files=changed_files, policy=policy)
    return _render_for_agent(
        result,
        changed_files=changed_files,
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
) -> dict:
    github = GitHubAdapter(token=token, repo=repo)
    changed_files, pr_body = github.get_pr_files_and_body(pr_number)
    changed_files = enrich_semantic_signals(changed_files)
    policy = load_policy(policy_path)
    result = run(
        changed_files=changed_files,
        drift_ignores=parse_drift_ignores(pr_body),
        policy=policy,
    )
    return _render_for_agent(
        result,
        changed_files=changed_files,
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
    changed_files = enrich_semantic_signals(GitAdapter().get_changed_files(base))
    policy = load_policy(policy_path)
    result = run(changed_files=changed_files, policy=policy)
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
        "actions": actions,
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


def _compact_result(result, changed_files, *, token_budget: int) -> dict:
    violations = [_compact_violation(v) for v in result.violations]
    payload = {
        "result": result.result,
        "summary": result.to_dict()["summary"],
        "change_types": result.change_types,
        "scan_metrics": {
            "scanned_files": result.scan_metrics.scanned_files,
            "skipped_ignored_files": result.scan_metrics.skipped_ignored_files,
            "evaluated_rules": result.scan_metrics.evaluated_rules,
        },
        "violations": violations,
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
    budgeted["changed_file_index"] = payload["changed_file_index"][:20]
    budgeted["violations"] = payload["violations"][:5]
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
