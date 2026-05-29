# Drift Gate Example: GitHub Actions CI/CD Deploy Repo

This example shows a Drift Gate policy for a repository whose primary purpose is managing CI/CD pipelines, infrastructure, and deployment workflows.

## Stack Assumptions

- Deploy workflows: `.github/workflows/deploy*.yml`, `.github/workflows/release*.yml`
- All CI workflows: `.github/workflows/**`
- Infrastructure: `infra/**`, `terraform/**`, `helm/**`, `k8s/**`
- Docker: `Dockerfile*`, `docker-compose*.yml`
- Config: `.env*`

## Rules

### `deploy-workflow-runbook` (BLOCKER)

Fires when a deploy or release workflow changes with secret-level modifications (`ci-secret-change` intensity). Requires both an ops runbook and a changelog entry.

This is a blocker because deploy workflow changes can affect production environments and require coordinated ops documentation.

### `ci-secret-ops-docs` (MAJOR)

Fires when any CI workflow file changes at `ci-secret-change` intensity (e.g., adding a new `env:` key, adding `secrets:` references) without ops or security documentation.

### `infra-runbook` (MAJOR)

Fires when Terraform, Helm, or Kubernetes configuration changes without an ops runbook. Infrastructure changes often require manual rollback procedures.

### `docker-image-ops-docs` (MINOR)

Fires when Dockerfile or docker-compose changes to remind the team to keep container documentation current. Minor severity because Dockerfile changes are frequent and usually safe.

### `env-config-sync` (MAJOR)

Fires when workflow `env:` or `.env*` files change with new keys without environment documentation updates.

## Ignoring CI-Only Workflows

The `ignore_paths` section excludes `.github/workflows/ci.yml` (the test/lint workflow) since changes to CI-only workflows typically don't require runbooks.

## Usage

```
drift-gate check
```
