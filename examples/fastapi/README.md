# Drift Gate Example: FastAPI

This example shows a Drift Gate policy for a Python FastAPI application.

## Stack Assumptions

- Routers: `app/routers/**` and `app/api/**`
- Pydantic schemas: `app/schemas/**`
- DB migrations: `alembic/versions/**`
- Auth dependencies: `app/auth/**` and `app/core/security.py`
- Config: `app/core/config.py` and `.env*`

## Rules

### `api-contract-sync` (BLOCKER)

Fires when a FastAPI router file or `app/main.py` changes with route-level modifications and the OpenAPI spec docs are not updated.

Uses `min_change_intensity: route-contract-change` — the rule only triggers when the diff contains a route decorator (`@router.get`, `@router.post`, etc.) or response model change.

### `db-migration-runbook` (MAJOR)

Fires when an Alembic migration version is added or an ORM model changes without a runbook.

### `env-config-sync` (MAJOR)

Fires when `app/core/config.py` (Pydantic `BaseSettings`) or `.env*` files change without `.env.example` and deployment docs being updated.

### `auth-security-docs` (BLOCKER)

Fires when auth logic or security dependencies change without a security documentation update.

### `schema-contract-sync` (MAJOR)

Fires when Pydantic request/response schemas change (which affects the API contract) without updating API documentation.

## Usage

```
drift-gate check
```
