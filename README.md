# Drift Gate

Drift Gate is a GitHub Action and local CLI that checks whether PR code changes
are matched by the contract documents your team expects: API specs, runbooks,
CHANGELOG entries, `.env.example`, security docs, and similar files.

It is not a style checker and it does not need an LLM to decide pass/fail. Rules
live in `.drift-gate.yml`.

## What It Catches

- API route or OpenAPI changes without API docs or CHANGELOG updates
- DB migrations without runbooks or release notes
- Environment/config changes without `.env.example`
- CI/infra changes without ops docs
- Auth/RBAC changes without security docs

## Quick Start

```bash
py -m pip install -e .
py main.py init --preset api
py main.py check --explain
```

Useful commands:

```bash
py main.py check                         # check current working tree
py main.py report --out-html report.html # write an HTML report
py main.py docs-check README.md --json   # verify docs match CLI/schema
py main.py review --base main            # deterministic code review helper
py main.py demo                          # generate benchmark.html
py main.py eval --compare-baseline       # run fixture benchmark
```

If Python's Scripts directory is on `PATH`, the console command is also
available:

```bash
drift-gate check
drift-gate report --out-html report.html
```

## GitHub Action

Create `.github/workflows/drift-gate.yml`:

```yaml
name: Drift Gate

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  drift-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: cres17/pr-convention-checker@v1
```

Optional Claude enrichment can improve checklist wording, but does not affect
the deterministic gate decision:

```yaml
      - uses: cres17/pr-convention-checker@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
```

## Policy Example

Create `.drift-gate.yml`:

```yaml
rules:
  - id: api-contract-sync
    when:
      any_changed:
        - "src/routes/**"
        - "openapi/**"
    require:
      groups:
        - name: "API docs"
          any_changed:
            - "docs/api/**"
            - "docs/spec.md"
        - name: "Release notes"
          all_changed:
            - "CHANGELOG.md"
    severity: blocker
    message: "API surface changed without synced contract docs"

gate:
  fail_on_blocker: true
  fail_on_major_count: 2

ignore_paths:
  - "src/internal/**"
```

Important: do not put required docs paths such as `docs/**` or `CHANGELOG.md`
inside `ignore_paths`, because ignored paths are excluded from both trigger and
require checks.

## Rule Fields

| Field | Meaning |
|---|---|
| `id` | Rule ID, also used by `drift-ignore` |
| `when.any_changed` | Paths that trigger the rule |
| `when.min_change_intensity` | Optional threshold such as `signature-change` or `route-contract-change` |
| `require.groups[].any_changed` | Group is satisfied when any listed path changed |
| `require.groups[].all_changed` | Group is satisfied only when every listed path changed |
| `severity` | `blocker`, `major`, `minor`, or `nit` |
| `gate.fail_on_blocker` | Fail CI on blocker violations |
| `gate.fail_on_major_count` | Fail CI when major count reaches this number |

## Suppressing Intentional Drift

Add this to the PR description:

```text
drift-ignore: api-contract-sync
reason: internal-only refactor, no public contract changed
```

For `blocker` and `major` rules, `reason:` is required. Without it, the ignore
is rejected and the rule still counts toward the gate.

## Outputs

CLI and Action runs produce:

- Markdown summary for PR comments
- JSON report for automation
- Optional HTML report for local review

JSON includes:

```json
{
  "summary": {"blocker": 0, "major": 0, "minor": 0, "nit": 0, "gate_decision": "pass"},
  "scan_metrics": {"scanned_files": 3, "evaluated_rules": 1, "runtime_seconds": 0.01},
  "result": "pass",
  "change_types": ["api-surface"],
  "violations": [],
  "rule_decisions": [],
  "skipped_rules": [],
  "rejected_ignores": [],
  "ignore_audit": [],
  "temporal_warnings": [],
  "gate": {"fail_on_blocker": true, "fail_on_major_count": 2}
}
```

## Semantic Detection

Drift Gate combines path rules with patch/semantic signals. Current adapters
cover Python, TypeScript/JavaScript, Go, Java, Kotlin, and Ruby. When
`tree-sitter-language-pack` is installed, grammar-backed parsing is used where
available; conservative patch heuristics remain as fallback.

## Development

```bash
py -m pip install -e .
py -m pytest -q
py main.py eval drift_gate/tests/fixtures --recursive --compare-baseline --engines semantic-aware --max-fp 0 --max-fn 0 --min-f1 1.0
```

Current semantic-aware benchmark:

| Engine | Cases | Passed | Precision | Recall | F1 | FP | FN |
|---|---:|---:|---:|---:|---:|---:|---:|
| Semantic-aware | 22 | 22 | 1.000 | 1.000 | 1.000 | 0 | 0 |

## License

MIT
