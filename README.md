# Spec/Contract Drift Gate

> Automatically checks if your PR's code changes are in sync with your team's contract documents — spec, runbook, CHANGELOG, .env.example, and more.

![Claude Code Plugin](https://img.shields.io/badge/Claude_Code-plugin-6C47FF)
![GitHub Action](https://img.shields.io/badge/GitHub_Actions-ready-2088FF?logo=github-actions)
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
Evaluate rules: when → require.groups (all groups must be satisfied)
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
    ├── fixtures/       # 3 sample PR scenarios
    └── test_engine.py  # 21 unit + integration tests
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

### Option A — Claude Code plugin (local preflight)

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

### Option B — GitHub Actions (automatic on every PR)

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

### Option C — CLI

```bash
pip install pyyaml
python main.py --policy .drift-gate.yml --base main
python main.py --pr 42 --repo owner/repo    # GitHub PR mode
python main.py --help
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
| `require.groups` | List of requirement groups — **all** must be satisfied |
| `require.groups[].name` | Group name shown in report |
| `require.groups[].any_changed` | Group satisfied if any path in list is changed |
| `require.groups[].all_changed` | Group satisfied only if all paths in list are changed |
| `severity` | `blocker` / `major` / `minor` / `nit` |
| `message` | Description shown in PR comment |
| `gate.fail_on_blocker` | Exit 1 when any BLOCKER found |
| `gate.fail_on_major_count` | Exit 1 when MAJOR count ≥ N |
| `ignore_paths` | Paths excluded from **both** trigger and require evaluation |

> ⚠️ Do **not** put paths used in `require.groups` (like `docs/**`, `tests/**`) into `ignore_paths` — they would never satisfy requirements.

### Action inputs

| Input | Default | Description |
|-------|---------|-------------|
| `anthropic_api_key` | — | Optional. Anthropic API key for checklist enrichment |
| `github_token` | `github.token` | GitHub token for PR comments |
| `policy_file` | `.drift-gate.yml` | Path to policy file |
| `model` | `claude-opus-4-6` | Claude model for enrichment |
| `fail_on_blocker` | `true` | Exit 1 when BLOCKER found |
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
      "ignored": false
    }
  ],
  "skipped_rules": [
    {"rule_id": "workflow-ops-doc", "severity": "MINOR", "reason": "dev-only", "message": "..."}
  ],
  "rejected_ignores": [],
  "gate": {"fail_on_blocker": true, "fail_on_major_count": 2}
}
```

---

## Suppressing false positives

Add to PR description:

```
drift-ignore: api-contract-sync
reason: internal refactor only, no externally visible contract change
```

**`reason:` policy:**
- **BLOCKER / MAJOR**: `reason:` is **required**. Without it, the ignore is rejected — the rule stays in `violations` and appears in `rejected_ignores`. The violation still counts toward the CI gate.
- **MINOR / NIT**: `reason:` is optional.

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

## Development

```bash
pip install pyyaml pytest
pytest drift_gate/tests/ -v    # 21 tests
```

---

## License

MIT
