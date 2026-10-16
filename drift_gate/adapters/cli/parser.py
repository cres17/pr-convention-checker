"""CLI argument contract, separate from command execution."""
import argparse
import os

from drift_gate.adapters.cli.presets import POLICY_PRESETS
from drift_gate.adapters.eval.runner import DEFAULT_FIXTURE_PATH
from drift_gate.adapters.history.store import DEFAULT_HISTORY_PATH


def build_parser() -> argparse.ArgumentParser:
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

    bundle = subparsers.add_parser('bundle', help='Verify or replay a locally persisted evidence bundle')
    bundle.add_argument('operation', choices=['verify', 'replay', 'spans'])
    bundle.add_argument('path', help='Published bundle directory (named by receipt SHA-256)')
    bundle.add_argument('--expected-receipt-sha256', help='Optional independently retained receipt digest')
    bundle.add_argument('--json', action='store_true', dest='json_output')
    bundle.add_argument('--out-json', help='Write verification or replay JSON')
    bundle.add_argument('--engine-manifest', help='Replay with the pinned engine that produced the bundle')
    bundle.add_argument('--engine-manifest-sha256', help='Externally retained SHA-256 pin of --engine-manifest')
    bundle.add_argument('--repo-root', default='.', help='Repository holding the pinned engine commit')

    scope = subparsers.add_parser('scope', help='Whole-tree dependency impact, service identity and no-delta certificates')
    scope.add_argument('--base', required=True)
    scope.add_argument('--head', required=True)
    scope.add_argument('--policy', default='.drift-gate.yml')
    scope.add_argument('--trusted-policy-ref', required=True)
    scope.add_argument('--trusted-policy-sha256', required=True)
    scope.add_argument('--isolated-workers', action='store_true', help='Extract module facts in isolated worker processes')
    scope.add_argument('--cache-dir', help='Persistent analysis cache keyed by input, engine, profile and parser digests')
    scope.add_argument('--out-json')
    scope.add_argument('--json', action='store_true', dest='json_output')

    migrate = subparsers.add_parser('migrate', help='Shadow-compare legacy decisions with proof-gate or typed triggers')
    migrate.add_argument('kind', choices=['proof-gate', 'typed-trigger'])
    migrate.add_argument('--base', required=True)
    migrate.add_argument('--head', required=True)
    migrate.add_argument('--policy', default='.drift-gate.yml')
    migrate.add_argument('--trusted-policy-ref', required=True)
    migrate.add_argument('--trusted-policy-sha256', required=True)
    migrate.add_argument('--out-json')
    migrate.add_argument('--json', action='store_true', dest='json_output')

    holdout = subparsers.add_parser('holdout', help='Independent evaluation: split, freeze, run, review packet, adjudicate, score')
    holdout.add_argument('operation', choices=['split', 'freeze', 'run', 'packet', 'adjudicate', 'score'])
    holdout.add_argument('--input', help='Candidate cases (split) / holdout cases (freeze)')
    holdout.add_argument('--frozen', help='Frozen holdout file')
    holdout.add_argument('--frozen-sha256', help='Pinned SHA-256 of --frozen')
    holdout.add_argument('--results', help='Results file (score)')
    holdout.add_argument('--results-sha256', help='Pinned SHA-256 of --results')
    holdout.add_argument('--packet', help='Review packet (adjudicate)')
    holdout.add_argument('--packet-sha256', help='Pinned SHA-256 of --packet (printed by packet)')
    holdout.add_argument('--reviews', nargs='*', default=[], help='Review JSONL files (adjudicate)')
    holdout.add_argument('--resolutions', help='Adjudicator resolutions JSONL (optional)')
    holdout.add_argument('--labels', help='Adjudicated labels file (score)')
    holdout.add_argument('--labels-sha256', help='Pinned SHA-256 of --labels (printed by adjudicate)')
    holdout.add_argument('--seed', default='drift-gate-holdout')
    holdout.add_argument('--holdout-fraction', type=float, default=0.3)
    holdout.add_argument('--regression-families', nargs='*', default=[])
    holdout.add_argument('--protocol', default='drift-gate-holdout-protocol-v1')
    holdout.add_argument('--out', required=True, help='Output path (never overwritten)')
    holdout.add_argument('--out-development', help='Development split output (split)')
    holdout.set_defaults(json_output=True)

    org = subparsers.add_parser('org', help='Organization service operations on a local tenant store')
    org.add_argument('operation', choices=['create-tenant', 'add-principal', 'store', 'list', 'delete', 'purge',
                                           'audit', 'backup', 'restore', 'set-retention'])
    org.add_argument('--root', required=True, help='Service store directory')
    org.add_argument('--tenant', required=True)
    org.add_argument('--actor', required=True, help='Principal performing the action (self-asserted in the CLI)')
    org.add_argument('--principal'); org.add_argument('--roles', nargs='*', default=[])
    org.add_argument('--scopes', nargs='*', default=[]); org.add_argument('--repository')
    org.add_argument('--result-json', help='Inspection JSON to store'); org.add_argument('--result-id')
    org.add_argument('--retention-days', type=int, default=90); org.add_argument('--archive')
    org.add_argument('--archive-sha256'); org.add_argument('--max-runs-per-day', type=int, default=500)
    org.add_argument('--max-stored-bytes', type=int, default=1_000_000_000)
    org.set_defaults(json_output=True)

    engine = subparsers.add_parser('engine', help='Build an engine manifest or attest loaded code against one')
    engine.add_argument('operation', choices=['manifest', 'attest'])
    engine.add_argument('--ref', help='Immutable engine commit (manifest)')
    engine.add_argument('--manifest', help='Engine manifest file (attest)')
    engine.add_argument('--manifest-sha256', help='Externally retained SHA-256 pin of --manifest')
    engine.add_argument('--out', help='Write the manifest (never overwrites an existing file)')
    engine.add_argument('--json', action='store_true', dest='json_output')

    trusted = subparsers.add_parser('trusted-check',
                                    help='Evaluate the candidate head with a pinned trusted engine and policy')
    trusted.add_argument('--base', required=True)
    trusted.add_argument('--head', required=True)
    trusted.add_argument('--policy', default='.drift-gate.yml')
    trusted.add_argument('--trusted-policy-ref', required=True)
    trusted.add_argument('--trusted-policy-sha256', required=True)
    trusted.add_argument('--engine-manifest', required=True)
    trusted.add_argument('--engine-manifest-sha256', required=True)
    trusted.add_argument('--comparison-mode', choices=['commit', 'merge-base'], default='commit')
    trusted.add_argument('--out-json')
    trusted.add_argument('--json', action='store_true', dest='json_output')

    runs = subparsers.add_parser('run', help='Inspect, cancel or recover journaled runs and latest pointers')
    runs.add_argument('operation', choices=['show', 'list', 'cancel', 'recover', 'latest', 'reconcile'])
    runs.add_argument('name', nargs='?', help='Run ID (show/cancel) or latest target name (latest)')
    runs.add_argument('--run-store', required=True, help='Run store directory used by check --run-store')
    runs.add_argument('--reason', default='operator-request', help='Cancellation reason to record')
    runs.add_argument('--stale-after', type=float, default=600.0,
                      help='Seconds of owner silence after which recover closes a run')
    runs.add_argument('--json', action='store_true', dest='json_output')

    publication = subparsers.add_parser('publication', help='Resolve a PR comment whose write outcome is unknown')
    publication.add_argument('operation', choices=['reconcile'])
    publication.add_argument('--record', required=True, help='drift_gate_publication.json from the action artifact')
    publication.add_argument('--repo', required=True)
    publication.add_argument('--pr', type=int, required=True)
    publication.add_argument('--out-json', help='Write the reconciled record (never overwrites --record)')
    publication.add_argument('--json', action='store_true', dest='json_output')

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
        default=str(DEFAULT_FIXTURE_PATH),
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
    _add_local_comparison_mode(self_audit)
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
    _add_local_comparison_mode(review)
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


def _add_local_comparison_mode(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--comparison-mode', choices=['commit', 'merge-base'], default='merge-base',
                        help='merge-base (default) compares against the fork point of --base and HEAD; '
                             'commit compares against --base itself')


def _add_check_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--run-store', help='Journal this run (stages, failure, cancel, publication) in a local store')
    parser.add_argument('--timeout-seconds', type=float, help='Close the run as timed-out at this deadline')
    parser.add_argument('--retry-of', help='Closed run ID this run retries; the previous record is kept')
    parser.add_argument('--latest-target', help='Compare-and-set this result as latest for a named target')
    parser.add_argument('--evidence-store', help='Opt in to private raw-input storage; persists the base inspection')
    parser.add_argument('--head', help='Immutable Git target ref; requires a separate policy ref and SHA-256 pin')
    parser.add_argument('--trusted-policy-ref', help='Caller-selected trusted Git policy revision')
    parser.add_argument('--trusted-policy-sha256', help='Expected raw SHA-256 of the selected trusted policy')
    parser.add_argument('--contract-proofs', action='store_true', help='Include validated shadow proofs; policy gate is unchanged')
    parser.add_argument("--policy", default=None, help="Policy file path (explicit paths use the calling directory)")
    parser.add_argument('--comparison-mode', choices=['commit', 'merge-base'], default=None,
                        help='Comparison basis. Default: merge-base for local working-tree checks (the fork point of '
                             '--base and HEAD, like a PR diff); commit for immutable --head checks')
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
        default=str(DEFAULT_FIXTURE_PATH),
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


