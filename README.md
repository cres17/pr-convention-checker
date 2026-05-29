# Spec/Contract Drift Gate

> Automatically checks if your PR's code changes are in sync with your team's contract documents — spec, runbook, CHANGELOG, .env.example, and more.

![Claude Code Plugin](https://img.shields.io/badge/Claude_Code-plugin-6C47FF)
![GitHub Action](https://img.shields.io/badge/GitHub_Actions-ready-2088FF?logo=github-actions)
![CI](https://github.com/cres17/pr-convention-checker/actions/workflows/ci.yml/badge.svg)
![License](https://img.shields.io/badge/license-MIT-blue)
![Python](https://img.shields.io/badge/python-3.10+-blue)

Unlike AI code reviewers (CodeRabbit, Qodo), this tool is not about code quality.
It's a **doc-code consistency policy engine** — it enforces that your contract documents stay in sync with your code changes.

---

## How it works

```
PR opened / drift-gate invoked
        │
        ▼
Load .drift-gate.yml policy
        │
        ▼
Collect changed files (GitHub API or git)
        │
        ▼
Classify change types: api-surface / db-schema / env-config / workflow-ci / auth-permission
        │
        ▼  docs-only or test-only? → skip (pass)
Evaluate rules: when → require.groups + optional cross-file relations
        │
        ▼
Parse drift-ignore directives from PR description
        │
        ▼
Generate deterministic checklist per violation (Claude enrichment optional)
        │
        ▼
Output: Markdown report + JSON result

  BLOCKER → merge blocked (CI fails)
  MAJOR   → team discussion needed
  MINOR   → PR comment only, non-blocking
  NIT     → informational
```

---

## Architecture

```
drift_gate/
├── core/              # pure logic — no I/O, no external dependencies
│   ├── models/        # ChangedFile, Policy, EvaluationResult
│   ├── classification/ # path-rule classifier
│   ├── policy/        # .drift-gate.yml loader + validation
│   ├── evaluation/    # rule evaluator
│   ├── reasoning/     # deterministic checklist builder
│   ├── gating/        # pass / warn / fail decision
│   └── engine.py      # single entrypoint: run()
│
├── adapters/          # I/O lives here only
│   ├── github/        # paginated PR file collection
│   ├── github_action/ # GitHub Actions runner (env vars → GITHUB_OUTPUT)
│   ├── git/           # local git diff
│   ├── cli/           # argparse CLI
│   └── claude/        # optional LLM enrichment
│
├── reporters/         # MarkdownReporter, JsonReporter
└── tests/
    ├── fixtures/       # sample PR scenarios
    ├── test_engine.py
    └── test_validator.py
```

The same `engine.run()` call powers all three execution modes: CLI, GitHub Actions, and Claude Plugin.

---

## Problems it solves

- API changed but OpenAPI spec / CHANGELOG not updated
- DB schema migrated but no runbook or rollback plan
- `.env` changed but `.env.example` still outdated
- GitHub Actions / infra changed but ops docs missing
- Auth rules changed but security docs not updated

---

## Installation

### Option A - Local MCP install (Codex / Claude-style tools)

This is the recommended local execution model. It mirrors tools like
`code-review-graph`: install the package, register a project-local MCP server,
restart your AI coding tool, then ask it to run Drift Gate against the repo.

```bash
py -m pip install -e .
py -m drift_gate setup
```

`py -m drift_gate setup` creates `.drift-gate.yml` when needed and writes a
`.mcp.json` entry:

```text
{
  "mcpServers": {
    "drift-gate": {
      "command": "<python-executable>",
      "args": ["-m", "drift_gate", "serve", "--repo", "."],
      "env": {"PYTHONUTF8": "1"}
    }
  }
}
```

For Claude Code, print the equivalent server entry:

```bash
py -m drift_gate setup --platform claude-code
```

Available local tools include checking the working tree, checking a PR,
listing rules, explaining a rule, reading history, and preparing a fix plan.

The MCP tools are token-budgeted by default. `drift_gate_check_local` and
`drift_gate_check_pr` return compact summaries without raw patches, full
trigger-file dictionaries, or rule-decision traces. Ask for
`drift_gate_get_evidence(rule_id=...)` only when you need bounded diff snippets
for a specific rule, or rerun with `mode="full"` when raw JSON is required.

### Option B - Claude Code plugin (command shortcut)

Run before pushing. Uses your existing Claude subscription.

**Install** (copies command + skill into your project):

```bash
curl -fsSL https://raw.githubusercontent.com/cres17/pr-convention-checker/main/install.sh | bash
```

Or manually:

```bash
mkdir -p .claude/commands .claude/skills
curl -fsSL https://raw.githubusercontent.com/cres17/pr-convention-checker/main/commands/drift-gate.md \
  -o .claude/commands/drift-gate.md
curl -fsSL https://raw.githubusercontent.com/cres17/pr-convention-checker/main/skills/drift-gate.md \
  -o .claude/skills/drift-gate.md
```

Then invoke inside Claude Code:
```
/drift-gate:review
/drift-gate:review main        # compare against main
/drift-gate:review 42          # check PR #42
/drift-gate:review 42 --json   # JSON output
```

### Option C - GitHub Actions (automatic on every PR)

Requires an `ANTHROPIC_API_KEY` secret (optional — used for checklist enrichment only; core gate logic works without it).

```yaml
# .github/workflows/drift-gate.yml
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
    if: github.event.pull_request.head.repo.full_name == github.repository
    steps:
      - uses: actions/checkout@v4
      - uses: cres17/pr-convention-checker@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
```

Add the secret: `Settings → Secrets → Actions → ANTHROPIC_API_KEY`

> **Large PRs**: All changed files are collected via paginated GitHub API calls (`per_page=100`). PRs with 100+ files are fully supported.

### Option D - CLI

```bash
py -m pip install -e .
py main.py setup                            # one-command local setup
py main.py                                  # check current working tree
py main.py check --explain                  # explain why rules pass/fail
py main.py report                           # write drift-report.md/json/html
py main.py report --out report.md           # alias for --out-md
py main.py report --out-json report.json --out-html report.html
py main.py report --open                    # write and open drift-report.html
py main.py init --preset fullstack          # create starter .drift-gate.yml
py main.py init --preset api                # api/db/env/auth/ci/fullstack presets
py main.py doctor                           # validate local setup
py main.py docs-check README.md --json      # positional docs file accepted
py main.py docs-check --docs README.md --json
py main.py demo                             # write benchmark.html + raw reports
py main.py eval --compare-baseline          # benchmark fixtures from the main CLI
py main.py check --token-estimate --json    # dry-run token/cost estimate, no API call
py main.py check --record-history           # append a local history record
py main.py history --last 30d --html trend.html
py main.py check --pr 42 --repo owner/repo
py main.py --help
```

Primary Windows-safe commands:

```powershell
py -m pip install -e .
py -m drift_gate setup
py -m drift_gate
py -m drift_gate review
py -m drift_gate check --explain
py -m drift_gate report --open
py -m drift_gate doctor
```

If Python's `Scripts` directory is on `PATH`, the shorter console command is
also available:

```bash
drift-gate setup
drift-gate
drift-gate review
```

---

## Configuration

Create `.drift-gate.yml` in your repo root:

```yaml
rules:
  - id: api-contract-sync
    when:
      any_changed:
        - "src/routes/**"
        - "openapi/**"
      min_change_intensity: signature-change
    require:
      groups:
        - name: "API 계약 문서"
          any_changed:
            - "docs/spec.md"
            - "docs/api/**"
        - name: "릴리즈 공지"
          all_changed:
            - "CHANGELOG.md"
    severity: blocker
    message: "API surface changed without synced contract/docs"

  - id: schema-migration-proof
    when:
      any_changed:
        - "db/migrations/**"
        - "prisma/schema.prisma"
    require:
      groups:
        - name: "운영 문서"
          any_changed:
            - "docs/runbook/**"
        - name: "검증 흔적"
          any_changed:
            - "tests/integration/**"
    severity: major
    message: "DB schema changed without migration note or integration test"

gate:
  fail_on_blocker: true
  fail_on_major_count: 2

ignore_paths:
  - "src/internal/**"
```

### Policy fields

| Field | Description |
|-------|-------------|
| `id` | Rule identifier. Use in `drift-ignore: <id>` to suppress |
| `when.any_changed` | Rule activates when any of these paths are changed |
| `when.min_change_intensity` | Optional patch threshold: `any`, `comment-only`, `impl-only`, `signature-change`, `export-added` |
| `require.groups` | List of requirement groups. Groups are mandatory unless `required: false` |
| `require.groups[].name` | Group name shown in report |
| `require.groups[].any_changed` | Group satisfied if any path in list is changed |
| `require.groups[].all_changed` | Group satisfied only if all paths in list are changed |
| `require.groups[].required` | Optional. Set `false` when a group should be required only by `require.cross_file` |
| `require.cross_file` | Optional relations that make named groups required only when relation-specific paths changed |
| `require.cross_file[].when_any_changed` | Relation activates when any of these paths are changed |
| `require.cross_file[].require_groups` | Existing group names required when the relation activates |
| `severity` | `blocker` / `major` / `minor` / `nit` |
| `message` | Description shown in PR comment |
| `gate.fail_on_blocker` | Exit 1 when any BLOCKER found |
| `gate.fail_on_major_count` | Exit 1 when MAJOR count ≥ N |
| `ignore_paths` | Paths excluded from **both** trigger and require evaluation |

> ⚠️ Do **not** put paths used in `require.groups` (like `docs/**`, `tests/**`) into `ignore_paths` — they would never satisfy requirements.

### Cross-file relations

Use `require.cross_file` when a document requirement should apply only to a
specific subset of a rule's trigger files. This keeps one rule deterministic
without forcing every trigger to require every possible document.

```yaml
rules:
  - id: api-contract-sync
    when:
      any_changed: ["src/routes/**", "openapi/**"]
    require:
      groups:
        - name: "API docs"
          any_changed: ["docs/api/**"]
        - name: "SDK contract"
          any_changed: ["sdk/**"]
          required: false
        - name: "Release notes"
          all_changed: ["CHANGELOG.md"]
          required: false
      cross_file:
        - name: "openapi-sdk-release"
          when_any_changed: ["openapi/**"]
          require_groups: ["SDK contract", "Release notes"]
    severity: blocker
```

In this example, route changes always require API docs. OpenAPI changes also
require SDK updates and release notes.

### Action inputs

| Input | Default | Description |
|-------|---------|-------------|
| `anthropic_api_key` | — | Optional. Anthropic API key for checklist enrichment |
| `github_token` | `github.token` | GitHub token for PR comments |
| `policy_file` | `.drift-gate.yml` | Path to policy file |
| `model` | `claude-opus-4-6` | Claude model for enrichment |
| `fail_on_blocker` | `true` | Exit 1 when the configured gate result is `fail` |
| `post_comment` | `true` | Post result as PR comment |

### Action outputs

| Output | Description |
|--------|-------------|
| `result` | `pass` / `warn` / `fail` / `skip` |
| `blocker_count` | Number of BLOCKER violations |
| `major_count` | Number of MAJOR violations |
| `violation_count` | Total violations |
| `comment_url` | URL of posted PR comment |

### JSON output schema

`drift_gate_report.json` is written to `$RUNNER_TEMP`. Full contract:

```json
{
  "summary": {
    "blocker": 1, "major": 0, "minor": 0, "nit": 0,
    "gate_decision": "fail"
  },
  "scan_metrics": {
    "scanned_files": 3,
    "skipped_ignored_files": 0,
    "skipped_binary_files": 0,
    "skipped_large_files": 0,
    "evaluated_rules": 5,
    "runtime_seconds": 0.031
  },
  "result": "fail",
  "change_types": ["api-surface"],
  "violations": [
    {
      "rule_id": "api-contract-sync",
      "severity": "BLOCKER",
      "confidence": "high",
      "change_types": ["api-surface"],
      "change_type": "api-surface",
      "message": "API surface changed without synced contract/docs",
      "trigger_files": [
        {"path": "src/routes/users.ts", "status": "modified", "previous_path": null, "patch": ""}
      ],
      "unsatisfied_groups": [
        {"name": "API 계약 문서", "required": ["docs/spec.md", "docs/api/**"], "type": "any_changed"}
      ],
      "checklist": ["관련 spec/API 문서를 변경 내용에 맞게 업데이트"],
      "ignored": false,
      "cross_file_relations": []
    }
  ],
  "skipped_rules": [
    {"rule_id": "workflow-ops-doc", "severity": "MINOR", "reason": "dev-only", "message": "..."}
  ],
  "rejected_ignores": [],
  "rule_decisions": [],
  "ignore_audit": [],
  "temporal_warnings": [],
  "gate": {"fail_on_blocker": true, "fail_on_major_count": 2}
}
```

---

## Suppressing false positives

Add to PR description:

```
drift-ignore: api-contract-sync
reason: internal refactor only, no externally visible contract change
expires: 2026-06-01
```

**`reason:` policy:**
- **BLOCKER / MAJOR**: `reason:` is **required**. Without it, the ignore is rejected — the rule stays in `violations` and appears in `rejected_ignores`. The violation still counts toward the CI gate.
- **MINOR / NIT**: `reason:` is optional.

**`expires:` policy:** optional, but if present it must be `YYYY-MM-DD`. Expired
ignores are rejected and the rule is evaluated normally.

To catch repeated suppressions over time, enable the temporal gate in local
check/report runs:

```bash
py main.py check --temporal-gate --history-path .drift-gate-history.jsonl
```

The threshold defaults to `suppression.repeated_ignore_threshold` from policy
or `3` when unset. Override it with `--temporal-threshold`.

Add to `.drift-gate.yml` to exclude paths globally:

```yaml
ignore_paths:
  - "src/internal/**"
  - "scripts/dev/**"
```

---

## Severity levels

| Level | Meaning | CI behavior |
|-------|---------|-------------|
| BLOCKER | Contract out of sync. Must fix before merge | CI fails |
| MAJOR | Docs missing or not updated. Team review needed | CI fails if ≥ N (default 2) |
| MINOR | Minor omission. PR comment only | Non-blocking |
| NIT | Informational suggestion | Non-blocking |

---

## Comparison

| | ESLint / Prettier | CodeRabbit / Qodo | **Drift Gate** |
|---|---|---|---|
| What it checks | Syntax & format | General code quality | **Contract doc sync** |
| Rulebook | Config files | Built-in heuristics | `.drift-gate.yml` |
| Blocks merge | Yes (lint errors) | No | Yes (BLOCKER) |
| Custom team rules | Code required | Limited | Edit YAML only |
| LLM required | No | Yes | **No** (optional enrichment) |

---

## Known Limitations & Roadmap

### Current Limitations

1. **Path-level classification only**: Change detection is based on file paths, not code semantics. A comment change in `src/routes/users.ts` triggers the same rule as a full API signature change. See [analysis](./고쳐야할점.md#3-현재의-핵심-한계).

2. **Content-agnostic document checks**: Rules verify that doc files are *present*, not that they're *correctly updated* to match code changes.

3. **Manual drift-ignore in PR description**: False positives require PR author to edit the description — no `.drift-ignore` file or code annotations yet.

4. **Content-agnostic history**: Historical records (JSONL/SQLite) track rule violations and gate decisions per PR, but do not validate whether contract documents were *correctly* updated — only that they were *touched*.

### Roadmap

**Immediate (1–2 weeks):**
- ✅ CI/CD: pytest on Python 3.10–3.12, multiple OS
- ✅ Test coverage: +5 new fixtures (rename, delete, empty PR, ignore_paths edge cases)
- ✅ Use `ChangedFile.patch` in the evaluator to distinguish comment-only changes from signature changes

**Short-term (1–2 months):**
- ✅ Cumulative report storage: JSONL + SQLite history via `--record-history` and `drift-gate history`
- ✅ `eval.py` benchmark against fixture PRs; `--compare-baseline` for regression gating
- Broaden change intensity heuristics and expand semantic fixtures

**Medium-term (3–6 months):**
- More language-specific contract detectors beyond the current TypeScript, Python, Go, Java, Kotlin, and Ruby semantic adapters
- Document content validation: use Claude to verify code changes are reflected in docs
- HTML/rich terminal reports for better UX

See [detailed analysis](./고쳐야할점.md) for comparison with [code-review-graph](https://github.com/tirth8205/code-review-graph) and [codiff](https://github.com/nkzw-tech/codiff).

---

## Development

```bash
pip install pyyaml pytest
pytest drift_gate/tests/ -v
```

### Running CI locally

```bash
# macOS / Linux
python -m pytest drift_gate/tests/ -v --tb=short

# Windows
python -m pytest drift_gate\tests\ -v --tb=short
```

### Running Offline Eval

Measure whether policy and classifier changes improve behavior over labeled PR
fixtures. The benchmark can compare the current patch-aware engine against a
path-only baseline, similar to how code-review-graph publishes reproducible
benchmark numbers.

```bash
python -m drift_gate.adapters.eval.runner
python -m drift_gate.adapters.eval.runner --json
python -m drift_gate.adapters.eval.runner drift_gate/tests/fixtures --out eval-report.md
python -m drift_gate.adapters.eval.runner external-fixtures --recursive --compare-baseline
python -m drift_gate.adapters.eval.runner --compare-baseline --html-out benchmark.html
python -m drift_gate.adapters.eval.runner --compare-baseline --case-report-dir benchmark-reports
python -m drift_gate.adapters.eval.runner --compare-baseline --max-fp 0 --max-fn 0 --min-f1 1.0
```

The eval runner reports exact-case pass/fail plus rule-level precision, recall,
F1, false positives, false negatives, runtime, and files/sec. Add new PR
scenarios as JSON files using the same shape as
`drift_gate/tests/fixtures/*.json`.

Use `--max-fp`, `--max-fn`, and `--min-f1` to turn fixture quality into an
explicit CI budget. This keeps false-positive reduction measurable instead of
only anecdotal.

Use `--case-report-dir` when you want raw per-case JSON artifacts for CI,
debugging, or a release note. In compare mode it writes `baseline/`,
`candidate/`, and `summary.json` so reviewers can inspect exactly why a fixture
passed or failed.

Use `--recursive` for external or real-world fixture packs organized by
category, for example `external-fixtures/api/*.json`.

Current fixture benchmark:

| Engine | Cases | Passed | Precision | Recall | F1 | FP | FN |
|---|---:|---:|---:|---:|---:|---:|---:|
| Path-only baseline | 22 | 19 | 0.824 | 1.000 | 0.903 | 3 | 0 |
| Semantic-aware candidate | 22 | 22 | 1.000 | 1.000 | 1.000 | 0 | 0 |

The HTML report is a shareable local artifact for demos and PR discussion. CI
also runs the benchmark and uploads Markdown, HTML, and raw JSON artifacts.

### Architecture notes

- **`core/`**: Pure logic, no I/O, no external dependencies. Easy to test.
- **`adapters/`**: All I/O (GitHub API, git, Claude, CLI) isolated here.
- **LLM optional**: Core gating works without Claude. Enrichment only improves checklist text.
- **Semantic signals**: Tree-sitter-backed adapters parse Python, TypeScript/JavaScript, Go, Java, Kotlin, and Ruby when grammars are installed; conservative patch heuristics remain as fallback.
- **History**: `--record-history` writes local JSONL; `history --html` renders a trend report.
- **Agent helpers**: `drift_gate.adapters.mcp.tools` exposes callable helpers for future MCP servers.
- **Hexagonal design**: Same `engine.run()` call powers CLI, GitHub Actions, and Claude Plugin.

---

## License

MIT
