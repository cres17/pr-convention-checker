"""
CLI adapter.

Friendly entrypoints:
- drift-gate check
- drift-gate report
- drift-gate init
- drift-gate doctor
- drift-gate demo
- drift-gate eval

For local preflight, running without a command behaves like ``check``.
"""
import argparse
import json
import os
import sys
import time
import webbrowser
from pathlib import Path

from drift_gate.adapters.eval.runner import (
    benchmark_gate_failures,
    compare_engines,
    compare_paths,
    discover_fixture_paths,
    evaluate_paths,
    render_comparison_html,
    render_comparison_markdown,
    render_engine_comparison_html,
    render_engine_comparison_markdown,
    render_markdown,
    EvalEngineComparison,
    write_case_reports,
)
from drift_gate.adapters.ast.analyzer import enrich_semantic_signals
from drift_gate.adapters.git.client import GitAdapter
from drift_gate.adapters.github.client import GitHubAdapter, parse_drift_ignores
from drift_gate.adapters.history.store import (
    DEFAULT_HISTORY_PATH,
    append_result,
    ignored_rule_counts,
    load_records,
    render_history_html,
    render_history_markdown,
)
from drift_gate.adapters.claude.enricher import ClaudeEnricher
from drift_gate.core.engine import run
from drift_gate.core.gating.temporal import apply_temporal_gate
from drift_gate.core.policy.loader import PolicyLoadError
from drift_gate.adapters.policy_loader import load_policy
from drift_gate.core.policy.validator import validate
from drift_gate.reporters.json_reporter import JsonReporter
from drift_gate.reporters.html import HtmlReporter
from drift_gate.reporters.markdown import MarkdownReporter
from drift_gate.utils.glob_matcher import match_glob


POLICY_TEMPLATE = """# Drift Gate policy
rules:
  - id: api-contract-sync
    when:
      any_changed:
        - "src/routes/**"
        - "openapi/**"
      min_change_intensity: signature-change
    require:
      groups:
        - name: "API docs"
          any_changed:
            - "docs/spec.md"
            - "docs/api/**"
        - name: "Release notes"
          all_changed:
            - "CHANGELOG.md"
    severity: blocker
    message: "API surface changed without synced contract docs"

  - id: env-config-sync
    when:
      any_changed:
        - ".env"
        - ".env.*"
        - "src/config/**"
        - "config/**"
    require:
      groups:
        - name: "Example env"
          all_changed:
            - ".env.example"
        - name: "Deployment docs"
          any_changed:
            - "docs/deployment/**"
            - "docs/runbook/**"
    severity: major
    message: "Environment/config changed without docs or .env.example update"

  - id: db-schema-sync
    when:
      any_changed:
        - "db/migrations/**"
        - "prisma/schema.prisma"
      min_change_intensity: db-schema-change
    require:
      groups:
        - name: "Migration runbook"
          any_changed:
            - "docs/runbook/**"
            - "docs/database/**"
        - name: "Verification"
          any_changed:
            - "tests/integration/**"
            - "tests/e2e/**"
    severity: major
    message: "DB schema changed without migration docs or verification"

  - id: auth-security-sync
    when:
      any_changed:
        - "src/auth/**"
        - "**/rbac/**"
        - "**/permissions/**"
      min_change_intensity: auth-policy-change
    require:
      groups:
        - name: "Security docs"
          any_changed:
            - "docs/security/**"
            - "SECURITY.md"
        - name: "Release notes"
          all_changed:
            - "CHANGELOG.md"
    severity: blocker
    message: "Auth policy changed without security docs"

  - id: workflow-secret-sync
    when:
      any_changed:
        - ".github/workflows/**"
      min_change_intensity: ci-secret-change
    require:
      groups:
        - name: "Ops docs"
          any_changed:
            - "docs/ops/**"
            - "docs/runbook/**"
    severity: major
    message: "Workflow secret changed without ops docs"

  - id: cli-public-interface-sync
    when:
      any_changed:
        - "commands/**"
        - "cli/**"
        - "src/cli/**"
        - "**/cli.py"
        - "main.py"
        - "pyproject.toml"
      min_change_intensity: public-cli-change
    require:
      groups:
        - name: "CLI docs"
          any_changed:
            - "README.md"
            - "docs/cli/**"
        - name: "Release notes"
          all_changed:
            - "CHANGELOG.md"
    severity: major
    message: "Public CLI interface changed without docs or release notes"

gate:
  fail_on_blocker: true
  fail_on_major_count: 2

ignore_paths:
  - "**/__pycache__/**"
  - "**/*.pyc"
"""

POLICY_PRESETS = {
    "api": """# Drift Gate policy: API contract sync
rules:
  - id: api-contract-sync
    when:
      any_changed:
        - "src/routes/**"
        - "app/api/**"
        - "openapi/**"
      min_change_intensity: signature-change
    require:
      groups:
        - name: "API docs"
          any_changed:
            - "docs/spec.md"
            - "docs/api/**"
        - name: "Release notes"
          all_changed:
            - "CHANGELOG.md"
    severity: blocker
    message: "API surface changed without synced contract docs"

gate:
  fail_on_blocker: true
  fail_on_major_count: 2

ignore_paths:
  - "**/__pycache__/**"
  - "**/*.pyc"
""",
    "auth": """# Drift Gate policy: auth/security sync
rules:
  - id: auth-security-sync
    when:
      any_changed:
        - "src/auth/**"
        - "**/rbac/**"
        - "**/permissions/**"
      min_change_intensity: auth-policy-change
    require:
      groups:
        - name: "Security docs"
          any_changed:
            - "docs/security/**"
            - "SECURITY.md"
        - name: "Release notes"
          all_changed:
            - "CHANGELOG.md"
    severity: blocker
    message: "Auth policy changed without security docs"

gate:
  fail_on_blocker: true
  fail_on_major_count: 2

ignore_paths:
  - "**/__pycache__/**"
  - "**/*.pyc"
""",
    "ci": """# Drift Gate policy: workflow/secret sync
rules:
  - id: workflow-secret-sync
    when:
      any_changed:
        - ".github/workflows/**"
      min_change_intensity: ci-secret-change
    require:
      groups:
        - name: "Ops docs"
          any_changed:
            - "docs/ops/**"
            - "docs/runbook/**"
    severity: major
    message: "Workflow secret changed without ops docs"

gate:
  fail_on_blocker: true
  fail_on_major_count: 2

ignore_paths:
  - "**/__pycache__/**"
  - "**/*.pyc"
""",
    "db": """# Drift Gate policy: database migration sync
rules:
  - id: db-schema-sync
    when:
      any_changed:
        - "db/migrations/**"
        - "prisma/schema.prisma"
      min_change_intensity: db-schema-change
    require:
      groups:
        - name: "Migration runbook"
          any_changed:
            - "docs/runbook/**"
            - "docs/database/**"
        - name: "Verification"
          any_changed:
            - "tests/integration/**"
            - "tests/e2e/**"
    severity: major
    message: "DB schema changed without migration docs or verification"

gate:
  fail_on_blocker: true
  fail_on_major_count: 2

ignore_paths:
  - "**/__pycache__/**"
  - "**/*.pyc"
""",
    "env": """# Drift Gate policy: env/config sync
rules:
  - id: env-config-sync
    when:
      any_changed:
        - ".env"
        - ".env.*"
        - "src/config/**"
        - "config/**"
      min_change_intensity: config-key-added
    require:
      groups:
        - name: "Example env"
          all_changed:
            - ".env.example"
        - name: "Deployment docs"
          any_changed:
            - "docs/deployment/**"
            - "docs/runbook/**"
    severity: major
    message: "Environment/config changed without docs or .env.example update"

gate:
  fail_on_blocker: true
  fail_on_major_count: 2

ignore_paths:
  - "**/__pycache__/**"
  - "**/*.pyc"
""",
}
POLICY_PRESETS["fullstack"] = POLICY_TEMPLATE


def run_cli(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv.insert(0, "check")

    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "demo":
        _run_demo(args)
        return
    if args.command == "eval":
        _run_eval(args)
        return
    if args.command == "init":
        _run_init(args)
        return
    if args.command == "doctor":
        _run_doctor(args)
        return
    if args.command == "history":
        _run_history(args)
        return
    if args.command == "explain":
        _run_explain(args)
        return
    if args.command == "self-audit":
        _run_self_audit(args)
        return
    if args.command == "docs-check":
        _run_docs_check(args)
        return
    if args.command == "review":
        _run_review(args)
        return
    if args.command == "install":
        _run_install(args)
        return
    if args.command == "setup":
        _run_setup(args)
        return
    if args.command == "serve":
        _run_serve(args)
        return

    _run_check(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="drift-gate",
        description="Spec/Contract Drift Gate",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser(
        "check",
        help="Check current working tree or a GitHub PR",
    )
    _add_check_args(check)

    report = subparsers.add_parser(
        "report",
        help="Check and write drift-report.md / drift-report.json",
    )
    _add_check_args(report)
    report.set_defaults(
        explain=True,
        out_md="drift-report.md",
        out_json="drift-report.json",
        out_html="drift-report.html",
    )

    init = subparsers.add_parser(
        "init",
        help="Create a starter .drift-gate.yml policy",
    )
    init.add_argument("--policy", default=".drift-gate.yml", help="Policy file path")
    init.add_argument("--force", action="store_true", help="Overwrite existing policy")
    init.add_argument(
        "--preset",
        choices=["auto"] + sorted(POLICY_PRESETS),
        default="fullstack",
        help="Starter policy preset",
    )
    init.add_argument(
        "--recommend",
        action="store_true",
        help="Print repo-based preset/framework/docs recommendations without writing a policy",
    )

    doctor = subparsers.add_parser(
        "doctor",
        help="Check local Drift Gate setup",
    )
    doctor.add_argument("--policy", default=".drift-gate.yml", help="Policy file path")
    doctor.add_argument("--base", default="HEAD", help="git diff base for local mode")

    demo = subparsers.add_parser(
        "demo",
        help="Generate benchmark.html from built-in fixtures",
    )
    demo.add_argument(
        "--fixtures",
        default="drift_gate/tests/fixtures",
        help="Fixture JSON file or directory",
    )
    demo.add_argument("--html-out", default="benchmark.html")
    demo.add_argument("--case-report-dir", default="benchmark-reports")

    eval_parser = subparsers.add_parser(
        "eval",
        help="Run deterministic fixture evaluation",
    )
    _add_eval_args(eval_parser)

    history = subparsers.add_parser(
        "history",
        help="Show local Drift Gate history",
    )
    history.add_argument("--path", default=DEFAULT_HISTORY_PATH)
    history.add_argument("--last", default="30d", help="History window, e.g. 7d")
    history.add_argument("--rule", default="", help="Only show records involving this rule id")
    history.add_argument("--html", help="Write HTML history report")

    explain = subparsers.add_parser(
        "explain",
        help="Explain a policy rule",
    )
    explain.add_argument("rule_id", help="Rule id to explain")
    explain.add_argument("--policy", default=".drift-gate.yml", help="Policy file path")

    self_audit = subparsers.add_parser(
        "self-audit",
        help="Verify that checked items in a Markdown checklist have code evidence in the diff",
    )
    self_audit.add_argument(
        "--checklist",
        default="고쳐야할점.md",
        help="Path to Markdown checklist file",
    )
    self_audit.add_argument(
        "--base",
        default="HEAD",
        help="git diff base (e.g. main, HEAD~1)",
    )
    self_audit.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print JSON output",
    )
    self_audit.add_argument(
        "--out",
        help="Write JSON report to this path",
    )
    self_audit.add_argument(
        "--out-html",
        dest="out_html",
        help="Write HTML self-audit report to this path",
    )

    docs_check = subparsers.add_parser(
        "docs-check",
        help="Verify README CLI commands and JSON schema match actual implementation",
    )
    docs_check.add_argument(
        "docs_positional",
        nargs="*",
        help="Documentation files to check (alias for --docs)",
    )
    docs_check.add_argument(
        "--docs",
        default=["README.md"],
        help="Space-separated list of documentation files to check",
        nargs="+",
    )
    docs_check.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print JSON output",
    )
    docs_check.add_argument(
        "--fail-on-warn",
        action="store_true",
        help="Exit with code 1 on any warning (default: exit 0 with warnings printed)",
    )

    review = subparsers.add_parser(
        "review",
        help="Deterministic code quality review (heuristic, no LLM required)",
    )
    review.add_argument(
        "--base",
        default="HEAD",
        help="git diff base for changed-files scope (e.g. main, HEAD~1)",
    )
    review.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format",
    )
    review.add_argument(
        "--fail-on",
        choices=["high", "medium", "low"],
        default=None,
        help="Exit 1 when any finding at this severity or higher is found",
    )
    review.add_argument(
        "--all-files",
        action="store_true",
        help="Review all Python files in the project, not just changed files",
    )

    install = subparsers.add_parser(
        "install",
        help="Install local MCP config for Codex/Claude-style AI tools",
    )
    install.add_argument(
        "--platform",
        choices=["codex", "claude-code", "local"],
        default="codex",
        help="Target integration style. codex writes project .mcp.json.",
    )
    install.add_argument(
        "--repo",
        default=".",
        help="Repository path the MCP server should inspect",
    )
    install.add_argument(
        "--config",
        help="Override output config path. Defaults to .mcp.json for codex/local.",
    )
    install.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing drift-gate MCP entry",
    )

    setup = subparsers.add_parser(
        "setup",
        help="One-command local setup: create policy if needed and install MCP config",
    )
    setup.add_argument("--repo", default=".", help="Repository path to configure")
    setup.add_argument("--policy", default=".drift-gate.yml", help="Policy file path")
    setup.add_argument(
        "--preset",
        choices=["auto"] + sorted(POLICY_PRESETS),
        default="auto",
        help="Starter policy preset when policy file is missing",
    )
    setup.add_argument(
        "--platform",
        choices=["codex", "claude-code", "local"],
        default="codex",
        help="Target MCP integration style",
    )
    setup.add_argument("--config", help="Override output MCP config path")

    serve = subparsers.add_parser(
        "serve",
        help="Run the local Drift Gate MCP-style stdio server",
    )
    serve.add_argument(
        "--repo",
        default=".",
        help="Repository path to inspect while serving tool requests",
    )

    return parser


def _add_check_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--policy", default=".drift-gate.yml", help="Policy file path")
    parser.add_argument("--pr", type=int, help="GitHub PR number")
    parser.add_argument("--repo", help="GitHub repository in owner/repo format")
    parser.add_argument(
        "--base",
        default="HEAD",
        help="git diff base for local mode; HEAD checks current working tree",
    )
    parser.add_argument("--json", action="store_true", dest="json_output", help="Print JSON")
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Include rule evaluation explanation in Markdown output",
    )
    parser.add_argument("--out", dest="out_md", help="Alias for --out-md")
    parser.add_argument("--out-md", help="Write Markdown report to this path")
    parser.add_argument("--out-json", help="Write JSON report to this path")
    parser.add_argument("--out-html", help="Write HTML report to this path")
    parser.add_argument(
        "--anthropic-api-key",
        default=os.environ.get("ANTHROPIC_API_KEY", ""),
        help="Optional Claude API key for checklist enrichment",
    )
    parser.add_argument(
        "--model",
        default="claude-opus-4-6",
        help="Claude model for optional enrichment",
    )
    parser.add_argument(
        "--token-estimate",
        action="store_true",
        dest="token_estimate",
        help="Print dry-run token cost estimate without calling the Claude API",
    )
    parser.add_argument(
        "--record-history",
        action="store_true",
        help="Append this run to .drift-gate-history.jsonl",
    )
    parser.add_argument("--history-path", default=DEFAULT_HISTORY_PATH)
    parser.add_argument(
        "--temporal-gate",
        action="store_true",
        help="Warn when recent history shows repeated drift-ignore for the same rule",
    )
    parser.add_argument(
        "--temporal-window",
        default="30d",
        help="History window for --temporal-gate, e.g. 30d",
    )
    parser.add_argument(
        "--temporal-threshold",
        type=int,
        help="Repeated ignore threshold for --temporal-gate",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the generated HTML report in the default browser",
    )


def _add_eval_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "path",
        nargs="?",
        default="drift_gate/tests/fixtures",
        help="Fixture JSON file or directory",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Discover fixture JSON files recursively",
    )
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument(
        "--compare-baseline",
        action="store_true",
        help="Compare candidate against path-only baseline",
    )
    parser.add_argument(
        "--engines",
        help="Comma-separated engine comparison, e.g. path-only,patch-aware,semantic-aware,llm-enriched",
    )
    parser.add_argument("--out", help="Write report to file")
    parser.add_argument(
        "--html-out",
        help="Write a shareable HTML benchmark report (compare mode only)",
    )
    parser.add_argument(
        "--case-report-dir",
        help="Write raw per-case JSON reports to a directory",
    )
    parser.add_argument("--max-fp", type=int, help="Candidate false-positive budget")
    parser.add_argument("--max-fn", type=int, help="Candidate false-negative budget")
    parser.add_argument("--min-f1", type=float, help="Candidate minimum F1")
    parser.add_argument(
        "--min-f1-delta",
        type=float,
        help="Minimum F1 delta in compare mode",
    )


def _run_check(args) -> None:
    changed_files, drift_ignores = _collect_inputs(args)

    start = time.perf_counter()
    try:
        policy_for_run = load_policy(args.policy)
    except FileNotFoundError:
        policy_for_run = None
    result = run(
        changed_files=changed_files,
        drift_ignores=drift_ignores,
        policy=policy_for_run,
    )
    runtime_seconds = time.perf_counter() - start
    result.scan_metrics.runtime_seconds = runtime_seconds
    policy = _load_policy_optional(args.policy)
    if args.temporal_gate:
        threshold = (
            args.temporal_threshold
            or (policy.suppression.repeated_ignore_threshold if policy else 3)
        )
        records = load_records(
            args.history_path,
            days=_parse_days(args.temporal_window),
        )
        result = apply_temporal_gate(
            result,
            ignored_rule_counts(records),
            threshold=threshold,
        )
    if getattr(args, "token_estimate", False) and not result.skip:
        result.enrichment_metrics = ClaudeEnricher(
            api_key="",
            model=args.model,
        ).estimate_dry_run(result)
    elif (
        args.anthropic_api_key
        and result.violations
        and not result.skip
        and (policy is None or not policy.enrichment.enabled or policy.enrichment.provider == "claude")
    ):
        result = ClaudeEnricher(
            api_key=args.anthropic_api_key,
            model=args.model,
        ).enrich(result)

    markdown = MarkdownReporter().render(result, explain=args.explain)
    json_report = JsonReporter().render(result)
    html_report = HtmlReporter().render(
        result,
        policy_source=_read_policy_source(args.policy),
    )

    if args.json_output:
        _write_stdout(json.dumps(json_report, ensure_ascii=False, indent=2))
    else:
        _write_stdout(markdown)
        if result.enrichment_metrics is not None and not args.json_output:
            _write_stdout("")
            prefix = "[dry-run estimate] " if getattr(args, "token_estimate", False) and not args.anthropic_api_key else ""
            _write_stdout(prefix + result.enrichment_metrics.format_report())

    if args.out_md:
        Path(args.out_md).write_text(markdown, encoding="utf-8")

    if args.out_json:
        Path(args.out_json).write_text(
            json.dumps(json_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if args.out_html:
        html_path = Path(args.out_html)
        html_path.write_text(html_report, encoding="utf-8")
        if args.open:
            _open_file(html_path)
    elif args.open:
        print("ERROR: --open requires --out-html or the report command", file=sys.stderr)
        sys.exit(1)

    if args.record_history:
        append_result(
            result,
            args.history_path,
            source="github-pr" if args.pr else "local",
            pr_number=args.pr,
            commit_sha=_git_commit_sha(),
            changed_file_count=len(changed_files),
            runtime_seconds=runtime_seconds,
            release=os.environ.get("GITHUB_REF_NAME", ""),
        )

    sys.exit(1 if result.result == "fail" else 0)


def _run_demo(args) -> None:
    paths = discover_fixture_paths(Path(args.fixtures))
    comparison = compare_paths(paths)

    Path(args.html_out).write_text(
        _render_demo_html(comparison),
        encoding="utf-8",
    )
    write_case_reports(comparison, Path(args.case_report_dir))

    _write_stdout(render_comparison_markdown(comparison))
    _write_stdout("")
    _write_stdout(f"Wrote HTML report: {args.html_out}")
    _write_stdout(f"Wrote raw reports: {args.case_report_dir}")
    sys.exit(1 if comparison.candidate.failed else 0)


def _run_eval(args) -> None:
    paths = discover_fixture_paths(Path(args.path), recursive=args.recursive)
    report = (
        compare_engines(paths, args.engines.split(","))
        if args.engines
        else compare_paths(paths) if args.compare_baseline else evaluate_paths(paths)
    )
    output = (
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
        if args.json_output
        else (
            render_engine_comparison_markdown(report)
            if isinstance(report, EvalEngineComparison)
            else render_comparison_markdown(report)
            if args.compare_baseline
            else render_markdown(report)
        )
    )
    if isinstance(report, EvalEngineComparison) and not args.json_output:
        output = render_engine_comparison_markdown(report)

    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
    if args.html_out:
        if not args.compare_baseline and not args.engines:
            print("ERROR: --html-out requires --compare-baseline or --engines", file=sys.stderr)
            sys.exit(2)
        Path(args.html_out).write_text(
            render_engine_comparison_html(report)
            if isinstance(report, EvalEngineComparison)
            else render_comparison_html(report),
            encoding="utf-8",
        )
    if args.case_report_dir:
        write_case_reports(report, Path(args.case_report_dir))

    _write_stdout(output)
    gate_failures = benchmark_gate_failures(
        report,
        max_fp=args.max_fp,
        max_fn=args.max_fn,
        min_f1=args.min_f1,
        min_f1_delta=args.min_f1_delta,
    )
    for failure in gate_failures:
        print(f"[drift-gate-eval] benchmark gate failed: {failure}", file=sys.stderr)

    failed = report.candidate.failed if hasattr(report, "candidate") else report.failed
    sys.exit(1 if failed or gate_failures else 0)


def _run_init(args) -> None:
    recommendations = _repo_recommendations(Path.cwd())
    if args.recommend:
        _write_stdout(_format_recommendations(recommendations))
        sys.exit(0)

    path = Path(args.policy)
    if path.exists() and not args.force:
        _write_stdout(f"Policy already exists: {path}")
        _write_stdout("Use --force to overwrite it.")
        sys.exit(1)

    preset = _select_init_preset(args.preset, recommendations)
    path.write_text(POLICY_PRESETS[preset], encoding="utf-8")
    _write_stdout(f"Created starter policy: {path}")
    _write_stdout(f"Preset: {preset}")
    _write_stdout("")
    _write_stdout(_format_recommendations(recommendations))
    _write_stdout("")
    _write_stdout("Next steps:")
    _write_stdout("  py main.py doctor")
    _write_stdout("  py main.py check --explain")
    sys.exit(0)


def _run_install(args) -> None:
    repo = Path(args.repo).expanduser().resolve()
    if not repo.exists() or not repo.is_dir():
        print(f"ERROR: repo path not found: {repo}", file=sys.stderr)
        sys.exit(2)

    outcome = _install_mcp_config(
        repo=repo,
        platform=args.platform,
        config_path=Path(args.config) if args.config else None,
        force=args.force,
    )
    if outcome["kind"] == "file":
        _write_stdout(f"Installed Drift Gate MCP config: {outcome['path']}")
        _write_stdout("Restart your AI tool, then ask it to run Drift Gate on this repo.")
    else:
        _write_stdout("Add this MCP server entry to your Claude Code config:")
        _write_stdout(json.dumps(outcome["entry"], ensure_ascii=False, indent=2))
    sys.exit(0)


def _run_setup(args) -> None:
    repo = Path(args.repo).expanduser().resolve()
    if not repo.exists() or not repo.is_dir():
        print(f"ERROR: repo path not found: {repo}", file=sys.stderr)
        sys.exit(2)

    policy_path = Path(args.policy)
    if not policy_path.is_absolute():
        policy_path = repo / policy_path

    created_policy = False
    if not policy_path.exists():
        recommendations = _repo_recommendations(repo)
        preset = _select_init_preset(args.preset, recommendations)
        policy_path.write_text(POLICY_PRESETS[preset], encoding="utf-8")
        created_policy = True
    else:
        preset = "existing"

    outcome = _install_mcp_config(
        repo=repo,
        platform=args.platform,
        config_path=Path(args.config) if args.config else None,
        force=True,
    )

    lines = [
        "Drift Gate setup complete.",
        f"Policy: {policy_path} ({'created ' + preset if created_policy else 'kept existing'})",
    ]
    if outcome["kind"] == "file":
        lines.append(f"MCP config: {outcome['path']}")
        lines.append("Restart your AI tool so it reloads the MCP server.")
    else:
        lines.append("Claude Code MCP entry:")
        lines.append(json.dumps(outcome["entry"], ensure_ascii=False, indent=2))
    lines += [
        "",
        "Daily commands:",
        "  py -m drift_gate          # local pre-push contract check",
        "  py -m drift_gate review   # deterministic code-quality preflight",
    ]
    _write_stdout("\n".join(lines))
    sys.exit(0)


def _install_mcp_config(
    *,
    repo: Path,
    platform: str,
    config_path: Path | None,
    force: bool,
) -> dict:
    entry = {
        "command": sys.executable,
        "args": ["-m", "drift_gate", "serve", "--repo", str(repo)],
        "env": {"PYTHONUTF8": "1"},
    }

    if platform in ("codex", "local"):
        config_path = config_path or repo / ".mcp.json"
        config = _read_json_file(config_path)
        servers = config.setdefault("mcpServers", {})
        if "drift-gate" in servers and not force:
            _write_stdout(f"Drift Gate MCP entry already exists: {config_path}")
            _write_stdout("Use --force to replace it.")
            sys.exit(1)
        servers["drift-gate"] = entry
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return {"kind": "file", "path": config_path, "entry": entry}

    if platform == "claude-code":
        return {"kind": "snippet", "entry": {"drift-gate": entry}}

    print(f"ERROR: unsupported platform: {platform}", file=sys.stderr)
    sys.exit(2)


def _run_serve(args) -> None:
    from drift_gate.adapters.mcp.server import main as serve_main

    serve_main(["--repo", args.repo])


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


def _run_review(args) -> None:
    from pathlib import Path as _Path
    from drift_gate.adapters.git.client import GitAdapter
    from drift_gate.core.review.heuristics import (
        find_reporter_field_gaps,
        find_test_gaps,
        review_files,
        SEVERITY_ORDER,
    )

    patch_text = ""
    # Collect files to review
    if args.all_files:
        file_paths = _collect_python_files(_Path.cwd())
    else:
        try:
            git = GitAdapter()
            changed_objs = git.get_changed_files(args.base)
            file_paths = [
                f.path for f in changed_objs
                if f.path.endswith(".py")
            ]
            patch_text = _collect_patch_text(args.base)
        except Exception as exc:
            print(f"WARNING: could not collect git diff: {exc}", file=sys.stderr)
            file_paths = []

    if not file_paths:
        _write_stdout("No Python files to review.")
        sys.exit(0)

    def _read_file(path: str) -> str:
        return _Path(path).read_text(encoding="utf-8", errors="replace")

    result = review_files(file_paths, _read_file)

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
    from drift_gate.reporters.html import HtmlReporter
    from drift_gate.reporters.markdown import MarkdownReporter

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


def _run_self_audit(args) -> None:
    from pathlib import Path as _Path
    from drift_gate.adapters.docs.checklist import parse_checklist
    from drift_gate.adapters.git.client import GitAdapter
    from drift_gate.core.self_audit.matcher import DiffEvidence, match_checklist

    checklist_path = _Path(args.checklist)
    if not checklist_path.exists():
        print(f"ERROR: checklist file not found: {checklist_path}", file=sys.stderr)
        sys.exit(1)

    items = parse_checklist(checklist_path)

    # Collect git diff evidence
    try:
        git = GitAdapter()
        changed_files_objs = git.get_changed_files(args.base)
        changed_file_paths = [f.path for f in changed_files_objs]
        patch_text = _collect_patch_text(args.base)
    except Exception as exc:
        print(f"WARNING: could not collect git diff: {exc}", file=sys.stderr)
        changed_file_paths = []
        patch_text = ""

    evidence = DiffEvidence.from_raw(
        changed_files=changed_file_paths,
        patch_text=patch_text,
    )
    audit_result = match_checklist(items, evidence)

    output_dict = audit_result.to_dict()

    if args.json_output or args.out:
        json_str = json.dumps(output_dict, ensure_ascii=False, indent=2)
        if args.out:
            _Path(args.out).write_text(json_str, encoding="utf-8")
        if args.json_output:
            _write_stdout(json_str)
        else:
            _write_stdout(_format_self_audit_markdown(audit_result))
    else:
        _write_stdout(_format_self_audit_markdown(audit_result))

    if getattr(args, "out_html", None):
        _Path(args.out_html).write_text(
            _render_self_audit_html(audit_result), encoding="utf-8"
        )

    warnings = audit_result.warnings
    mismatch_count = sum(1 for w in warnings if w.kind == "checklist-code-mismatch")
    missing_count = sum(1 for w in warnings if w.kind == "missing-progress-entry")
    supported = sum(1 for i in audit_result.checklist_items if i.status == "supported")
    checked = sum(1 for i in audit_result.checklist_items if i.checked)

    if not args.json_output:
        _write_stdout("")
        _write_stdout(
            f"Self-audit: {supported}/{checked} checked items supported by diff evidence"
        )
        if warnings:
            _write_stdout(
                f"Warnings: {mismatch_count} checklist-code-mismatch, "
                f"{missing_count} missing-progress-entry"
            )

    sys.exit(0)


def _collect_patch_text(base: str) -> str:
    """Return the unified diff text from git diff base."""
    import subprocess
    try:
        return subprocess.check_output(
            ["git", "diff", base],
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return ""


def _format_self_audit_markdown(audit_result) -> str:
    lines = ["# Self-Audit Report", ""]
    supported = [i for i in audit_result.checklist_items if i.status == "supported"]
    unsupported = [i for i in audit_result.checklist_items if i.status == "unsupported"]
    unchecked = [i for i in audit_result.checklist_items if i.status == "unchecked"]

    lines.append(
        f"**{len(supported)} supported** / **{len(supported)+len(unsupported)} checked** "
        f"/ {len(unchecked)} unchecked"
    )
    lines.append("")

    if unsupported:
        lines.append("## Unsupported Checked Items")
        lines.append("")
        for item in unsupported:
            lines.append(f"- [x] {item.text} *(line {item.line_number})*")
        lines.append("")

    if audit_result.warnings:
        lines.append("## Warnings")
        lines.append("")
        for w in audit_result.warnings:
            lines.append(f"- **{w.kind}**: {w.message}")
            if w.details:
                lines.append(f"  - {w.details}")
        lines.append("")

    return "\n".join(lines)


def _render_self_audit_html(audit_result) -> str:
    import html as _html
    supported = [i for i in audit_result.checklist_items if i.status == "supported"]
    unsupported = [i for i in audit_result.checklist_items if i.status == "unsupported"]
    unchecked = [i for i in audit_result.checklist_items if i.status == "unchecked"]

    def _item_rows(items, badge_class, badge_label):
        if not items:
            return f"<tr><td colspan='3'><em>None</em></td></tr>"
        rows = ""
        for item in items:
            ev = ", ".join(_html.escape(e) for e in item.evidence) or "—"
            rows += (
                f"<tr>"
                f"<td><span class='badge {badge_class}'>{badge_label}</span></td>"
                f"<td>{_html.escape(item.text)}</td>"
                f"<td class='ev'>{ev}</td>"
                f"</tr>"
            )
        return rows

    warnings_html = ""
    if audit_result.warnings:
        wrows = "".join(
            f"<tr><td><code>{_html.escape(w.kind)}</code></td>"
            f"<td>{_html.escape(w.message)}</td>"
            f"<td>{_html.escape(w.details)}</td></tr>"
            for w in audit_result.warnings
        )
        warnings_html = f"""
  <div class="card">
    <h2 style="margin-top:0">Warnings ({len(audit_result.warnings)})</h2>
    <table>
      <thead><tr><th>Kind</th><th>Message</th><th>Details</th></tr></thead>
      <tbody>{wrows}</tbody>
    </table>
  </div>"""

    all_rows = (
        _item_rows(supported, "green", "supported")
        + _item_rows(unsupported, "red", "unsupported")
        + _item_rows(unchecked, "gray", "unchecked")
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Drift Gate — Self-Audit Report</title>
  <style>
    body {{ font: 14px/1.5 system-ui, sans-serif; margin: 32px; background: #f8fafc; color: #172033; }}
    h1 {{ margin-bottom: 4px; }}
    .card {{ background: #fff; border: 1px solid #d8dee8; border-radius: 8px; padding: 24px; margin-bottom: 24px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-bottom: 1px solid #d8dee8; padding: 8px 10px; text-align: left; vertical-align: top; }}
    th {{ background: #f5f7fb; font-weight: 600; }}
    .badge {{ display: inline-block; border-radius: 4px; padding: 1px 7px; font-size: 12px; font-weight: 600; }}
    .green {{ background: #c6f6d5; color: #276749; }}
    .red {{ background: #fed7d7; color: #9b2c2c; }}
    .gray {{ background: #e2e8f0; color: #4a5568; }}
    .ev {{ font-size: 12px; color: #555; word-break: break-all; }}
    .summary {{ font-size: 1.1em; margin-bottom: 8px; }}
  </style>
</head>
<body>
  <h1>Drift Gate — Self-Audit Report</h1>
  <div class="card">
    <p class="summary">
      <strong>{len(supported)}</strong> supported &nbsp;/&nbsp;
      <strong>{len(supported) + len(unsupported)}</strong> checked &nbsp;/&nbsp;
      {len(unchecked)} unchecked
    </p>
    <table>
      <thead><tr><th>Status</th><th>Item</th><th>Evidence</th></tr></thead>
      <tbody>{all_rows}</tbody>
    </table>
  </div>
  {warnings_html}
</body>
</html>"""


def _run_doctor(args) -> None:
    checks = []
    errors = []
    warnings = []

    policy_path = Path(args.policy)
    if policy_path.exists():
        checks.append(f"OK policy file found: {policy_path}")
        try:
            policy = load_policy(policy_path)
            # load_warnings are already a subset of validation.warnings — avoid duplication
            validation = validate(policy)
            if validation.ok:
                checks.append(f"OK policy has {len(policy.rules)} rule(s)")
            warnings.extend(validation.warnings)
            errors.extend(validation.errors)
            warnings.extend(_broad_glob_warnings(policy))
            warnings.extend(_dead_rule_warnings(policy, Path.cwd()))
        except PolicyLoadError as exc:
            errors.append(f"policy failed to load: {exc}")
    else:
        errors.append(f"policy file missing: {policy_path}")

    if _git_ok(["git", "rev-parse", "--is-inside-work-tree"]):
        checks.append("OK git repository detected")
        if _git_ok(["git", "rev-parse", "--verify", "--quiet", args.base]):
            checks.append(f"OK git base exists: {args.base}")
        else:
            warnings.append(f"git base was not found locally: {args.base}")
        try:
            changed_files = GitAdapter().get_changed_files(args.base)
            checks.append(f"OK local diff collected: {len(changed_files)} file(s)")
        except Exception as exc:
            errors.append(f"local diff collection failed: {exc}")
    else:
        errors.append("not inside a git repository")

    if Path("action.yml").exists():
        checks.append("OK action.yml found")
    else:
        warnings.append("action.yml not found")

    if Path(".github/workflows").exists():
        checks.append("OK GitHub workflow directory found")
    else:
        warnings.append("GitHub workflow directory not found")

    if _console_entrypoints_ok():
        checks.append("OK console entrypoints import")
    else:
        warnings.append("console entrypoint import failed")

    if Path("drift_gate/tests/fixtures").exists():
        checks.append("OK benchmark fixtures found")
    else:
        warnings.append("benchmark fixtures not found")

    lines = ["# Drift Gate Doctor", ""]
    if checks:
        lines += ["## Checks", ""]
        lines.extend(f"- {item}" for item in checks)
        lines.append("")
    if warnings:
        lines += ["## Warnings", ""]
        lines.extend(f"- {item}" for item in warnings)
        lines.append("")
    if errors:
        lines += ["## Errors", ""]
        lines.extend(f"- {item}" for item in errors)
        lines.append("")
        lines.append("Doctor result: FAIL")
    else:
        lines.append("Doctor result: PASS")

    _write_stdout("\n".join(lines))
    sys.exit(1 if errors else 0)


def _render_demo_html(comparison) -> str:
    return render_comparison_html(comparison)


def _open_file(path: Path) -> None:
    webbrowser.open(path.resolve().as_uri())


def _read_policy_source(path: str) -> str:
    policy_path = Path(path)
    if not policy_path.exists():
        return ""
    return policy_path.read_text(encoding="utf-8")


def _read_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON config {path}: {exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(data, dict):
        print(f"ERROR: JSON config root must be an object: {path}", file=sys.stderr)
        sys.exit(1)
    return data


def _load_policy_optional(path: str):
    try:
        policy = load_policy(path)
        for w in policy.load_warnings:
            print(f"[drift-gate] WARNING: {w}", file=sys.stderr)
        return policy
    except Exception:
        return None


def _parse_days(value: str) -> int:
    normalized = value.strip().lower()
    if normalized.endswith("d"):
        normalized = normalized[:-1]
    try:
        days = int(normalized)
    except ValueError:
        print(f"ERROR: invalid --last value: {value}", file=sys.stderr)
        sys.exit(2)
    return max(days, 1)


def _collect_inputs(args) -> tuple[list, list]:
    if args.pr and args.repo:
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            print("ERROR: GITHUB_TOKEN is required for GitHub PR mode", file=sys.stderr)
            sys.exit(1)
        github = GitHubAdapter(token=token, repo=args.repo)
        changed_files, pr_body = github.get_pr_files_and_body(args.pr)
        return enrich_semantic_signals(changed_files), parse_drift_ignores(pr_body)

    git = GitAdapter()
    return enrich_semantic_signals(git.get_changed_files(args.base)), []


def _git_ok(args: list[str]) -> bool:
    import subprocess

    try:
        subprocess.check_output(args, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False


def _git_commit_sha() -> str:
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return ""


def _broad_glob_warnings(policy) -> list[str]:
    warnings = []
    broad = {"**", "**/*", "src/**", "app/**", "*"}
    for rule in policy.rules:
        for pattern in rule.when.any_changed:
            if pattern in broad:
                warnings.append(
                    f"rule '{rule.id}' uses broad trigger glob '{pattern}'; "
                    "consider a narrower contract boundary"
                )
    return warnings


def _dead_rule_warnings(policy, repo_root: Path) -> list[str]:
    repo_paths = _repo_paths(repo_root)
    if not repo_paths:
        return []

    warnings = []
    for rule in policy.rules:
        matched = any(
            match_glob(path, pattern)
            for path in repo_paths
            for pattern in rule.when.any_changed
        )
        if not matched:
            warnings.append(
                f"rule '{rule.id}' appears inactive: no repository files match "
                f"when.any_changed patterns {rule.when.any_changed}"
            )
    return warnings


def _repo_recommendations(repo_root: Path) -> dict:
    paths = set(_repo_paths(repo_root))
    frameworks = _detect_frameworks(paths)
    presets = []

    if _has_any(paths, ["prisma/schema.prisma", "db/**", "database/migrations/**", "alembic/versions/**"]):
        presets.append("db")
    if _has_any(paths, ["src/routes/**", "app/api/**", "openapi/**", "proto/**"]):
        presets.append("api")
    if _has_any(paths, [".github/workflows/**", "Dockerfile", "Dockerfile.*", "infra/**", "terraform/**", "k8s/**", "helm/**"]):
        presets.append("ci")
    if _has_any(paths, [".env.example", ".env", "config/**", "src/config/**", "**/settings.py"]):
        presets.append("env")
    if _has_any(paths, ["src/auth/**", "**/rbac/**", "**/permissions/**", "**/policy/**"]):
        presets.append("auth")

    docs_paths = _recommend_docs_paths(paths, frameworks, presets)
    return {
        "presets": presets or ["fullstack"],
        "frameworks": frameworks or ["unknown"],
        "docs_paths": docs_paths,
    }


def _format_recommendations(recommendations: dict) -> str:
    lines = [
        "Repo recommendations:",
        f"  presets: {', '.join(recommendations['presets'])}",
        f"  frameworks: {', '.join(recommendations['frameworks'])}",
        "  docs paths:",
    ]
    lines.extend(f"    - {path}" for path in recommendations["docs_paths"])
    return "\n".join(lines)


def _select_init_preset(requested: str, recommendations: dict) -> str:
    if requested != "auto":
        return requested
    presets = recommendations["presets"]
    if len(presets) == 1 and presets[0] in POLICY_PRESETS:
        return presets[0]
    return "fullstack"


def _detect_frameworks(paths: set[str]) -> list[str]:
    frameworks = []
    package_json = Path("package.json")
    pyproject = Path("pyproject.toml")
    requirements = Path("requirements.txt")

    package_text = package_json.read_text(encoding="utf-8") if package_json.exists() else ""
    pyproject_text = pyproject.read_text(encoding="utf-8") if pyproject.exists() else ""
    requirements_text = requirements.read_text(encoding="utf-8") if requirements.exists() else ""
    python_deps = f"{pyproject_text}\n{requirements_text}".lower()

    if "fastapi" in python_deps or _has_any(paths, ["**/main.py", "**/api.py"]) and "fastapi" in python_deps:
        frameworks.append("FastAPI")
    if "django" in python_deps or _has_any(paths, ["manage.py", "**/settings.py"]):
        frameworks.append("Django")
    if "express" in package_text:
        frameworks.append("Express")
    if "next" in package_text or _has_any(paths, ["next.config.js", "next.config.mjs", "app/**", "pages/**"]):
        frameworks.append("Next.js")
    if "rails" in paths or _has_any(paths, ["Gemfile", "config/routes.rb", "app/controllers/**"]):
        frameworks.append("Rails")
    return sorted(set(frameworks))


def _recommend_docs_paths(
    paths: set[str],
    frameworks: list[str],
    presets: list[str],
) -> list[str]:
    docs = []
    if "api" in presets or any(f in frameworks for f in ("FastAPI", "Express", "Next.js", "Django", "Rails")):
        docs.extend(["docs/api/**", "docs/spec.md", "openapi/**"])
    if "db" in presets:
        docs.extend(["docs/database/**", "docs/runbook/**"])
    if "env" in presets:
        docs.extend([".env.example", "docs/deployment/**"])
    if "ci" in presets:
        docs.extend(["docs/ops/**", "docs/runbook/**"])
    if "auth" in presets:
        docs.extend(["docs/security/**", "SECURITY.md"])
    if _has_any(paths, ["README.md"]):
        docs.append("README.md")
    return sorted(set(docs)) or ["docs/**", "README.md"]


def _has_any(paths: set[str], patterns: list[str]) -> bool:
    return any(match_glob(path, pattern) for path in paths for pattern in patterns)


def _repo_paths(repo_root: Path) -> list[str]:
    ignored_dirs = {
        ".git", ".hg", ".svn", "__pycache__", ".pytest_cache",
        ".mypy_cache", ".ruff_cache", "node_modules", "dist", "build",
        ".venv", "venv",
    }
    paths = []
    for path in repo_root.rglob("*"):
        if any(part in ignored_dirs for part in path.parts):
            continue
        if path.is_file():
            paths.append(path.relative_to(repo_root).as_posix())
    return paths


def _console_entrypoints_ok() -> bool:
    try:
        from drift_gate.adapters.cli.runner import run_cli as _cli
        from drift_gate.adapters.eval.runner import run_eval as _eval
    except Exception:
        return False
    return callable(_cli) and callable(_eval)


def _write_stdout(output: str) -> None:
    data = (output + "\n").encode("utf-8")
    if hasattr(sys.stdout, "buffer"):
        sys.stdout.buffer.write(data)
    else:
        sys.stdout.write(output + "\n")


if __name__ == "__main__":
    run_cli()
