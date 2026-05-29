# Drift Gate Example: Next.js

This example shows a Drift Gate policy for a Next.js application with API routes.

## Stack Assumptions

- API routes (Pages Router): `pages/api/**`
- API routes (App Router): `app/api/**` or `src/app/api/**`
- Auth: `pages/api/auth/**`, `lib/auth/**`, `middleware.ts`
- Config: `.env*`, `next.config.*`

## Rules

### `api-route-contract-sync` (BLOCKER)

Fires when a Next.js API route changes with route-level modifications without API documentation updates.

Works for both Pages Router (`pages/api/`) and App Router (`app/api/`).

### `env-config-sync` (MAJOR)

Fires when `.env*` or `next.config.*` changes without updating `.env.example`. Targets `config-key-added` intensity to skip formatting changes.

### `auth-security-docs` (BLOCKER)

Fires when Next.js auth routes, auth library code, or `middleware.ts` (which handles edge-runtime auth) change without security documentation updates.

### `public-page-contract-sync` (MINOR)

Fires when a new exported page or component is added. Lower severity (minor) appropriate for UI changes.

## Usage

```
drift-gate check
```
