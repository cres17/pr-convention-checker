# Drift Gate Example: Django + DRF

This example shows a Drift Gate policy for a Django application using Django REST Framework.

## Stack Assumptions

- Views and ViewSets: `**/views.py`, `**/viewsets.py`
- URL routing: `**/urls.py`
- Serializers: `**/serializers.py`
- DB migrations: `**/migrations/**`
- Settings: `**/settings.py`
- Auth/permissions: `**/permissions.py`, `**/authentication.py`

## Rules

### `api-contract-sync` (BLOCKER)

Fires when a Django view, viewset, or URL file changes with route-level modifications without API documentation updates.

### `db-migration-runbook` (MAJOR)

Fires when a Django migration or model changes without a runbook. The `min_change_intensity: db-schema-change` threshold ensures that only migrations with actual schema changes trigger the rule.

### `env-config-sync` (MAJOR)

Fires when Django `settings.py` or `.env*` files change without updating `.env.example`. Requires `config-key-added` intensity to skip whitespace or comment edits.

### `serializer-contract-sync` (MAJOR)

Fires when DRF serializers change (which affects the API's request/response contract) without API documentation updates.

### `auth-security-docs` (BLOCKER)

Fires when Django auth or permission classes change without security documentation updates.

## Usage

```
drift-gate check
```
