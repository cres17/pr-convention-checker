# Drift Gate Example: Prisma

This example shows a Drift Gate policy for a project using Prisma ORM with schema migrations.

## Stack Assumptions

- Prisma schema: `prisma/schema.prisma`
- Migrations: `prisma/migrations/**`
- Seed: `prisma/seed.ts`

## Rules

### `db-migration-runbook` (BLOCKER)

Fires when `prisma/schema.prisma` or a migration file changes at `db-schema-change` intensity (meaning actual model/table definitions were modified). Requires both a runbook and a changelog entry.

This is a blocker because schema migrations directly affect production data and require coordinated deployment.

### `db-seed-sync` (MINOR)

Fires when the Prisma schema changes to remind the team to check whether the seed script also needs updating. Minor severity because seed scripts are not always required to match the schema.

### `env-config-sync` (MAJOR)

Fires when `.env*` files change without updating `.env.example`. Important in Prisma projects because `DATABASE_URL` and other connection variables are commonly set here.

### `api-contract-sync` (MAJOR)

Fires when `prisma/schema.prisma` changes to remind the team to update any downstream GraphQL or REST API schema that is generated from or mirrors the Prisma models.

## Usage

```
drift-gate check
```
