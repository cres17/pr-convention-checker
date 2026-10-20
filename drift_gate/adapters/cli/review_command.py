"""review·explain·history·docs-check 명령: 저장소 내용 점검과 규칙 설명, 이력 조회."""
import json
import sys
from pathlib import Path

from drift_gate.adapters.cli.common import _parse_days
from drift_gate.adapters.cli.output import write_stdout as _write_stdout
from drift_gate.adapters.git.client import GitAdapter, GitInputError
from drift_gate.adapters.history.store import (
    load_records,
    render_history_html,
    render_history_markdown,
)
from drift_gate.adapters.policy_loader import load_policy
from drift_gate.core.policy.loader import PolicyLoadError
from drift_gate.reporters.html import HtmlReporter
from drift_gate.reporters.markdown import MarkdownReporter


def _run_review(args) -> None:
    from drift_gate.adapters.git.client import repository_root
    from drift_gate.core.review.heuristics import (
        SEVERITY_ORDER,
        find_reporter_field_gaps,
        find_test_gaps,
        review_files,
    )
    root = repository_root()
    patch_text = ""
    # Collect files to review
    if args.all_files:
        file_paths = [str(Path(p).relative_to(root)) for p in _collect_python_files(root)]
    else:
        changed_objs = GitAdapter().get_changed_files(args.base, comparison_mode=args.comparison_mode)
        file_paths = [f.path for f in changed_objs if f.path.endswith(".py") and f.status != "deleted"]
        patch_text = "\n".join(f.patch for f in changed_objs)

    def _read_file(path: str) -> str:
        try:
            return (root / path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise GitInputError(f"검사할 파일을 읽지 못했습니다: {path}") from exc

    # The core review helper tolerates unavailable files; CLI automation must
    # distinguish incomplete input from a successfully reviewed empty set.
    contents = {path: _read_file(path) for path in file_paths}
    result = review_files(file_paths, contents.__getitem__)

    if patch_text and not args.all_files:
        result.test_gaps = find_test_gaps(patch_text, file_paths)
        result.test_gaps.extend(_review_reporter_field_gaps(file_paths, find_reporter_field_gaps))

    if args.format == "json":
        _write_stdout(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        _write_stdout(result.format_markdown())

    # Exit code logic
    if args.fail_on:
        severity_idx = SEVERITY_ORDER.index(args.fail_on)
        for finding in result.findings:
            if SEVERITY_ORDER.index(finding.severity) <= severity_idx:
                sys.exit(1)
    sys.exit(0)


def _collect_python_files(root) -> list[str]:
    """Collect all Python files under root, excluding common non-source dirs."""
    ignored = {
        ".git", "__pycache__", ".pytest_cache", ".venv", "venv",
        "node_modules", "dist", "build", ".mypy_cache",
        "tests",
    }
    paths = []
    for path in root.rglob("*.py"):
        if any(part in ignored for part in path.parts):
            continue
        paths.append(path.as_posix())
    return paths


def _review_reporter_field_gaps(file_paths: list[str], find_reporter_field_gaps):
    normalized = {path.replace("\\", "/") for path in file_paths}
    relevant = normalized & {
        "drift_gate/core/models/result.py",
        "drift_gate/reporters/markdown.py",
        "drift_gate/reporters/html.py",
        "drift_gate/reporters/json_reporter.py",
    }
    if not relevant:
        return []

    from drift_gate.core.models.policy import Gate
    from drift_gate.core.models.result import EvaluationResult

    sample = EvaluationResult(
        change_types=["api-surface"],
        violations=[],
        skipped_rules=[],
        rejected_ignores=[],
        gate=Gate(),
    )
    html = HtmlReporter().render(sample)
    raw_json_idx = html.find("<summary>Raw JSON</summary>")
    human_html = html[:raw_json_idx] if raw_json_idx != -1 else html
    return find_reporter_field_gaps(
        sample.to_dict(),
        {
            "markdown": MarkdownReporter().render(sample),
            "html": human_html,
        },
    )


def _run_explain(args) -> None:
    try:
        policy = load_policy(args.policy)
        for w in policy.load_warnings:
            print(f"[drift-gate] WARNING: {w}", file=sys.stderr)
    except FileNotFoundError:
        print(f"ERROR: policy file missing: {args.policy}", file=sys.stderr)
        sys.exit(1)
    except PolicyLoadError as exc:
        print(f"ERROR: policy failed to load: {exc}", file=sys.stderr)
        sys.exit(1)

    for rule in policy.rules:
        if rule.id != args.rule_id:
            continue
        lines = [
            f"# Drift Gate Rule: {rule.id}",
            "",
            f"- Severity: `{rule.severity.upper()}`",
            f"- Message: {rule.message or '-'}",
            f"- Min change intensity: `{rule.when.min_change_intensity}`",
            "",
            "## Triggers",
            "",
        ]
        lines.extend(f"- `{pattern}`" for pattern in rule.when.any_changed)
        lines += ["", "## Required Groups", ""]
        for group in rule.require.groups:
            group_type = "any_changed" if group.any_changed else "all_changed"
            required = group.any_changed or group.all_changed
            lines.append(f"- **{group.name}** (`{group_type}`):")
            lines.extend(f"  - `{pattern}`" for pattern in required)
        lines += [
            "",
            "## Gate Meaning",
            "",
            "This rule triggers when a changed file matches the trigger glob and passes the minimum change intensity.",
            "It fails only when one or more required groups are missing from the same change set.",
        ]
        _write_stdout("\n".join(lines))
        sys.exit(0)

    print(f"ERROR: rule not found: {args.rule_id}", file=sys.stderr)
    sys.exit(1)


def _run_history(args) -> None:
    days = _parse_days(args.last)
    records = load_records(args.path, days=days, rule_id=args.rule)
    markdown = render_history_markdown(records, days=days, rule_id=args.rule)
    if args.html:
        Path(args.html).write_text(
            render_history_html(records, days=days, rule_id=args.rule),
            encoding="utf-8",
        )
    _write_stdout(markdown)
    sys.exit(0)


def _run_docs_check(args) -> None:
    from pathlib import Path as _Path

    from drift_gate.adapters.docs.readme_contract import check_docs

    selected_docs = args.docs_positional or args.docs
    doc_paths = [_Path(p) for p in selected_docs]
    result = check_docs(doc_paths)

    if args.json_output:
        _write_stdout(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        _write_stdout(result.format_report())
        if result.warnings:
            _write_stdout(f"\n{len(result.warnings)} warning(s) found.")
        else:
            _write_stdout("\nNo docs-consistency issues found.")

    if args.fail_on_warn and result.warnings:
        sys.exit(1)
    sys.exit(0)
