# Detector Guide

This guide explains how Drift Gate classifies changed files, what semantic signals each detector extracts, and how to write rules targeting each detector type.

---

## Change Type Classification

Drift Gate assigns one or more **change types** to each pull request based on the file paths that changed. Classification happens in `drift_gate/core/classification/classifier.py`.

### Detector Types

| Change Type | Description | Default Path Patterns |
|---|---|---|
| `api-surface` | REST/RPC routes, OpenAPI specs, protobuf definitions | `src/routes/**`, `openapi/**`, `proto/**` |
| `db-schema` | Database migrations, ORM schema files | `db/migrations/**`, `prisma/schema.prisma`, `**/models.py` |
| `env-config` | Environment variables, application config | `.env*`, `config/**`, `**/settings.py` |
| `workflow-ci` | CI/CD workflows, Docker, infrastructure | `.github/workflows/**`, `Dockerfile*`, `infra/**` |
| `auth-permission` | Auth, RBAC, permissions, policies | `**/auth/**`, `**/rbac/**`, `**/permissions/**` |
| `docs-only` | Exclusive: all files are documentation | `docs/**`, `**/*.md`, `**/*.rst` |
| `test-only` | Exclusive: all files are tests | `tests/**`, `**/*.test.*` |

`docs-only` and `test-only` are **exclusive** classifications. They are only assigned when _every_ changed file matches the pattern. If even one code file is present, neither applies.

---

## How Classification Triggers

Classification is purely path-based. For each changed file, the classifier checks whether its path matches any known pattern using the project's glob matcher (`utils/glob_matcher.py`). The `**` wildcard matches any number of path segments.

**Example**: `src/routes/users.ts` matches `src/routes/**`, so the PR gets the `api-surface` change type.

Multiple change types can apply to a single PR. For example, a PR that modifies both `src/routes/users.ts` and `db/migrations/001_add_users.sql` gets both `api-surface` and `db-schema`.

---

## Semantic Signals

Beyond path matching, Drift Gate extracts **semantic signals** from the diff content using heuristic pattern matching in `drift_gate/adapters/ast/analyzer.py`. These signals feed into `min_change_intensity` thresholds and enrich reports.

### How Semantic Signals are Extracted

For each changed file, the analyzer scans only the **added lines** (`+` prefix in the unified diff). It applies language-specific and path-based regex patterns.

#### TypeScript / JavaScript (`.ts`, `.tsx`, `.js`, `.jsx`)

| Signal | Heuristic Pattern | What it Detects |
|---|---|---|
| `route-contract-change` | `(router\|app).(get\|post\|put\|patch\|delete)(` | Express/Fastify route handler added |
| `route-contract-change` | `z.object\|response_model\|requestBody\|responses\|parameters\|operationId` | Schema/OpenAPI annotation changed |
| `class-interface-type-changed` | `export\s+(class\|interface\|type\|enum)` | Public type declaration added |
| `public-export-added` | `export\s+(default\s+)?(async\s+)?(function\|class\|const\|...)` | Public export added |
| `public-cli-change` | `(program\|commander).(command\|option)(` | CLI option or command changed |

#### Python (`.py`)

| Signal | Heuristic Pattern | What it Detects |
|---|---|---|
| `route-contract-change` | `@\w+.(get\|post\|put\|patch\|delete)(` | FastAPI/Flask route decorator |
| `route-contract-change` | `response_model\|requestBody\|...` | Pydantic schema or OpenAPI annotation |
| `function-signature-changed` | `def\s+\w+\s*(` | New function signature |
| `class-interface-type-changed` | `(class\|type\|data\s+class)\s+\w+` | Class or type declaration |
| `public-cli-change` | `add_argument\|add_parser\|@click.(command\|option\|argument)` | argparse or Click CLI change |

#### Go (`.go`)

| Signal | Heuristic Pattern | What it Detects |
|---|---|---|
| `function-signature-changed` | `func\s+\w+\s*(` | Function signature |
| `class-interface-type-changed` | `type\s+\w+\s+(struct\|interface)` | Struct or interface declaration |

#### Java / Kotlin (`.java`, `.kt`, `.kts`)

| Signal | Heuristic Pattern | What it Detects |
|---|---|---|
| `class-interface-type-changed` | `(public\|private\|protected\|fun\|class\|interface\|data\s+class)` | Public type or function |

#### Ruby (`.rb`)

| Signal | Heuristic Pattern | What it Detects |
|---|---|---|
| `function-signature-changed` | `(def\|class\|module)\s+\w+` | Public class, module, or method |

#### Path-based (any language)

| Signal | Trigger | What it Detects |
|---|---|---|
| `public-cli-change` | `pyproject.toml` or `package.json` with `scripts`/`entry_points` | Package entrypoint changed |
| `env-key-added` | Any file with `BaseSettings\|SettingsConfigDict\|envSchema\|configSchema\|env_prefix` | Config schema change |
| `route-contract-change` | Files under `sdk/`, `client/`, `clients/` with public exports | SDK/client contract changed |
| `openapi-operation-changed` | Files containing `openapi`/`swagger` with `operationId:` | OpenAPI operation changed |
| `db-model-schema-changed` | Files in `prisma/`, `models`, `schema` with model/table declarations | DB schema changed |

---

## Change Intensity Levels

Change intensity describes **how deeply** a file was changed. Rules can require a minimum intensity before triggering, reducing false positives from trivial changes.

Set `min_change_intensity` in the `when:` clause of a rule.

### Intensity Values (ordered low to high)

| Level | Description | When to Use |
|---|---|---|
| `comment-only` | Only comments/docstrings changed | Skip evaluation entirely for docs-in-code changes |
| `impl-only` | Implementation lines changed, no signature change | Skip for pure internal refactors |
| `signature-change` | Function/method signature changed | Trigger on public API boundary changes |
| `export-added` | New public export added | Trigger when new symbols become public |
| `docs-only` | Only documentation files changed | Equivalent to `docs-only` change type |
| `tests-only` | Only test files changed | Equivalent to `test-only` change type |
| `config-key-added` | New configuration key or env variable added | Trigger when deployment config changes |
| `route-contract-change` | Route handler or schema changed | Trigger API contract rules |
| `db-schema-change` | DB model or migration changed | Trigger DB runbook rules |
| `auth-policy-change` | Auth/RBAC/permission policy changed | Trigger security docs rules |
| `ci-secret-change` | CI secret or deployment credential changed | Trigger ops runbook rules |
| `public-cli-change` | CLI command or flag changed | Trigger README/help doc rules |

### Example Usage

```yaml
rules:
  - id: api-contract-sync
    when:
      any_changed: ["src/routes/**"]
      min_change_intensity: route-contract-change
    require:
      groups:
        - name: "OpenAPI spec"
          any_changed: ["openapi/**"]
    severity: blocker
```

This rule only triggers when the diff actually contains route-level changes, not when test files in `src/routes/` are modified.

---

## Writing Rules for Each Detector Type

### API Surface Rule

```yaml
rules:
  - id: api-contract-sync
    when:
      any_changed: ["src/routes/**", "openapi/**", "proto/**"]
      min_change_intensity: route-contract-change
    require:
      groups:
        - name: "API contract docs"
          any_changed: ["docs/spec.md", "docs/api/**"]
        - name: "Changelog"
          all_changed: ["CHANGELOG.md"]
    severity: blocker
    message: "API surface changed without updated contract documentation"
```

### DB Schema Rule

```yaml
rules:
  - id: db-migration-runbook
    when:
      any_changed: ["db/migrations/**", "prisma/schema.prisma"]
      min_change_intensity: db-schema-change
    require:
      groups:
        - name: "DB runbook"
          any_changed: ["docs/runbooks/**", "runbook.md"]
    severity: major
    message: "DB migration added without a runbook"
```

### Env Config Rule

```yaml
rules:
  - id: env-config-sync
    when:
      any_changed: [".env*", "config/**"]
      min_change_intensity: config-key-added
    require:
      groups:
        - name: ".env.example"
          all_changed: [".env.example"]
        - name: "Deployment docs"
          any_changed: ["docs/deployment.md", "docs/config.md"]
    severity: major
    message: "New env key added without updating .env.example or deployment docs"
```

### CI/Workflow Rule

```yaml
rules:
  - id: ci-secret-runbook
    when:
      any_changed: [".github/workflows/**", "Dockerfile*"]
      min_change_intensity: ci-secret-change
    require:
      groups:
        - name: "Ops runbook"
          any_changed: ["docs/ops/**", "runbook.md"]
    severity: major
    message: "CI/CD secret or deploy step changed without an ops runbook update"
```

### Auth/Permission Rule

```yaml
rules:
  - id: auth-security-docs
    when:
      any_changed: ["**/auth/**", "**/rbac/**", "**/permissions/**"]
      min_change_intensity: auth-policy-change
    require:
      groups:
        - name: "Security docs"
          any_changed: ["docs/security/**", "SECURITY.md"]
    severity: blocker
    message: "Auth/permission policy changed without security documentation update"
```

---

## Suppressing False Positives

If a rule triggers too broadly, use these techniques:

1. **Add `min_change_intensity`** to require a meaningful change before the rule fires.
2. **Narrow the `any_changed` patterns** in the `when:` clause.
3. **Add paths to `ignore_paths`** to exclude internal/test directories from trigger matching.

```yaml
ignore_paths:
  - "src/internal/**"
  - "src/**/__tests__/**"
```

Note: `ignore_paths` applies to both trigger (`when`) and requirement (`require`) matching. Do not add paths that are used as `require.groups` patterns.

## Cross-file Relations

Use `require.cross_file` when one trigger path implies extra documentation
requirements. Groups with `required: false` are optional by default and become
required only when a relation references them.

```yaml
rules:
  - id: api-contract-sync
    when:
      any_changed: ["src/routes/**", "openapi/**"]
      min_change_intensity: route-contract-change
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

The relation above means route changes require API docs, while OpenAPI changes
also require SDK contract updates and release notes. Activated relation names
are emitted in JSON, Markdown, and HTML evidence.
