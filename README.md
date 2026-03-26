# pr-convention-checker

> Automatically checks if your PR follows the conventions documented in `CLAUDE.md`, `SKILLS.md`, or any team guideline file.

![Claude Code Plugin](https://img.shields.io/badge/Claude_Code-plugin-6C47FF)
![GitHub Action](https://img.shields.io/badge/GitHub_Actions-ready-2088FF?logo=github-actions)
![License](https://img.shields.io/badge/license-MIT-blue)

Unlike generic AI reviewers (CodeRabbit, Qodo), this tool checks only **your team's own documented rules** — not general best practices. Your `CLAUDE.md` is the rulebook. Change the doc, change the check.

---

## How it works

```
PR opened / /check-conventions invoked
        │
        ▼
Read convention files (CLAUDE.md, SKILLS.md, ...)
        │
        ▼
Fetch PR diff (GitHub MCP or gh CLI or git diff)
        │
        ▼
Claude: "Does this diff violate any documented rule?"
        │
        ▼
Output findings grouped by severity

  BLOCKER → merge blocked
  MAJOR   → team discussion needed
  MINOR   → fix or follow-up issue
  NIT     → style preference, non-blocking
```

---

## Installation

### Option A — Claude Code plugin (no API key needed)

Uses your existing Claude subscription. Run manually before pushing.

```bash
# In your project root
git clone https://github.com/cres17/pr-convention-checker .claude-plugins/pr-convention-checker
```

Then invoke:
```
/check-conventions
/check-conventions main        # compare against main
/check-conventions 42          # review PR #42
```

### Option B — GitHub Actions (automatic on every PR)

Requires an `ANTHROPIC_API_KEY` secret. Runs automatically on every PR.

```yaml
# .github/workflows/convention-check.yml
name: Convention Check

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  pull-requests: write
  contents: read

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: cres17/pr-convention-checker@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
```

Add the secret: `Settings → Secrets → Actions → ANTHROPIC_API_KEY`

---

## Configuration

Create `.convention-checker.yml` in your repo root to customize behavior:

```yaml
convention_files:
  - CLAUDE.md
  - SKILLS.md
  - docs/api-guidelines.md   # add any file

exclude_paths:
  - "**/*.test.ts"
  - "**/*.spec.ts"
  - ".github/**"
  - "dist/**"

severity_map:
  blocker: ["must", "반드시", "never", "always"]
  major:   ["should", "required", "권장"]
  nit:     ["prefer", "가급적"]
```

Without this file, defaults apply (CLAUDE.md + SKILLS.md, test files excluded).

### Action inputs

| Input | Default | Description |
|---|---|---|
| `anthropic_api_key` | — | **Required.** Anthropic API key |
| `model` | `claude-opus-4-6` | Claude model to use |
| `convention_files` | _(from config)_ | Comma-separated file paths |
| `fail_on_blocker` | `true` | Exit 1 when BLOCKER found |
| `post_comment` | `true` | Post result as PR comment |

---

## Suppressing false positives

Add an inline comment to skip a specific line:

```typescript
const route = '/users/create'  // convention-ignore: legacy endpoint, tracked in #123
```

To skip a block:
```typescript
// convention-ignore-start
function legacyHandler() { ... }
// convention-ignore-end
```

---

## Security

| Concern | How it's handled |
|---|---|
| API key | GitHub encrypted secret — never in logs |
| Code sent to Anthropic | Same as any Claude-based review tool |
| Fork PRs | GitHub does not expose secrets to fork workflows by default |
| Sensitive lines | `password`, `secret`, `token` values are redacted before sending |

---

## Comparison

| | ESLint / Prettier | CodeRabbit / Qodo | **pr-convention-checker** |
|---|---|---|---|
| What it checks | Syntax & format | General code quality | **Your documented conventions** |
| Rulebook | Config files | Built-in heuristics | `CLAUDE.md` / `SKILLS.md` |
| Custom rules | Code required | Limited | Edit your markdown doc |
| Understands design patterns | No | Partially | Yes |

---

## License

MIT
