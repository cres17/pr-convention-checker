# Drift Gate Example: Express API

This example shows a Drift Gate policy for a Node.js Express REST API.

## Stack Assumptions

- Routes: `src/routes/**` and `src/controllers/**`
- OpenAPI spec: `openapi/openapi.yaml`
- DB migrations: `db/migrations/**`
- Auth middleware: `src/middleware/auth*` and `src/auth/**`
- Config: `.env*` and `config/**`

## Rules

### `api-contract-sync` (BLOCKER)

Fires when an Express route handler or OpenAPI file changes and the `openapi/openapi.yaml` spec and `CHANGELOG.md` are not updated.

Uses `min_change_intensity: route-contract-change` to skip test-only or comment-only changes to route files.

### `db-migration-runbook` (MAJOR)

Fires when a DB migration or ORM model changes without a runbook in `docs/runbooks/` or `RUNBOOK.md`.

### `env-config-sync` (MAJOR)

Fires when `.env*` or `config/**` changes without updating `.env.example` and deployment docs.

Uses `min_change_intensity: config-key-added` to ignore whitespace or comment-only config edits.

### `auth-security-docs` (BLOCKER)

Fires when auth middleware or RBAC code changes without a security documentation update.

## Usage

Place `.drift-gate.yml` at the root of your Express API repo. Run:

```
drift-gate check
```

Or in GitHub Actions:

```yaml
- uses: your-org/pr-convention-checker@v1
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    repo: ${{ github.repository }}
    pr_number: ${{ github.event.pull_request.number }}
```
