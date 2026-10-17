"""Starter policy text; choosing a preset does not change existing policies."""
POLICY_TEMPLATE = """# Drift Gate policy
rules:
  - id: api-contract-sync
    when:
      any_changed:
        - "src/routes/**"
        - "openapi/**"
      min_change_intensity: signature-change
    require:
      groups:
        - name: "API docs"
          any_changed:
            - "docs/spec.md"
            - "docs/api/**"
        - name: "Release notes"
          all_changed:
            - "CHANGELOG.md"
    severity: blocker
    message: "API surface changed without synced contract docs"

  - id: env-config-sync
    when:
      any_changed:
        - ".env"
        - ".env.*"
        - "src/config/**"
        - "config/**"
    require:
      groups:
        - name: "Example env"
          all_changed:
            - ".env.example"
        - name: "Deployment docs"
          any_changed:
            - "docs/deployment/**"
            - "docs/runbook/**"
    severity: major
    message: "Environment/config changed without docs or .env.example update"

  - id: db-schema-sync
    when:
      any_changed:
        - "db/migrations/**"
        - "prisma/schema.prisma"
      min_change_intensity: db-schema-change
    require:
      groups:
        - name: "Migration runbook"
          any_changed:
            - "docs/runbook/**"
            - "docs/database/**"
        - name: "Verification"
          any_changed:
            - "tests/integration/**"
            - "tests/e2e/**"
    severity: major
    message: "DB schema changed without migration docs or verification"

  - id: auth-security-sync
    when:
      any_changed:
        - "src/auth/**"
        - "**/rbac/**"
        - "**/permissions/**"
      min_change_intensity: auth-policy-change
    require:
      groups:
        - name: "Security docs"
          any_changed:
            - "docs/security/**"
            - "SECURITY.md"
        - name: "Release notes"
          all_changed:
            - "CHANGELOG.md"
    severity: blocker
    message: "Auth policy changed without security docs"

  - id: workflow-secret-sync
    when:
      any_changed:
        - ".github/workflows/**"
      min_change_intensity: ci-secret-change
    require:
      groups:
        - name: "Ops docs"
          any_changed:
            - "docs/ops/**"
            - "docs/runbook/**"
    severity: major
    message: "Workflow secret changed without ops docs"

  - id: cli-public-interface-sync
    when:
      any_changed:
        - "commands/**"
        - "cli/**"
        - "src/cli/**"
        - "**/cli.py"
        - "main.py"
        - "pyproject.toml"
      min_change_intensity: public-cli-change
    require:
      groups:
        - name: "CLI docs"
          any_changed:
            - "README.md"
            - "docs/cli/**"
        - name: "Release notes"
          all_changed:
            - "CHANGELOG.md"
    severity: major
    message: "Public CLI interface changed without docs or release notes"

gate:
  fail_on_blocker: true
  fail_on_major_count: 2

ignore_paths:
  - "**/__pycache__/**"
  - "**/*.pyc"
"""

POLICY_PRESETS = {
    "api": """# Drift Gate policy: API contract sync
rules:
  - id: api-contract-sync
    when:
      any_changed:
        - "src/routes/**"
        - "app/api/**"
        - "openapi/**"
      min_change_intensity: signature-change
    require:
      groups:
        - name: "API docs"
          any_changed:
            - "docs/spec.md"
            - "docs/api/**"
        - name: "Release notes"
          all_changed:
            - "CHANGELOG.md"
    severity: blocker
    message: "API surface changed without synced contract docs"

gate:
  fail_on_blocker: true
  fail_on_major_count: 2

ignore_paths:
  - "**/__pycache__/**"
  - "**/*.pyc"
""",
    "auth": """# Drift Gate policy: auth/security sync
rules:
  - id: auth-security-sync
    when:
      any_changed:
        - "src/auth/**"
        - "**/rbac/**"
        - "**/permissions/**"
      min_change_intensity: auth-policy-change
    require:
      groups:
        - name: "Security docs"
          any_changed:
            - "docs/security/**"
            - "SECURITY.md"
        - name: "Release notes"
          all_changed:
            - "CHANGELOG.md"
    severity: blocker
    message: "Auth policy changed without security docs"

gate:
  fail_on_blocker: true
  fail_on_major_count: 2

ignore_paths:
  - "**/__pycache__/**"
  - "**/*.pyc"
""",
    "ci": """# Drift Gate policy: workflow/secret sync
rules:
  - id: workflow-secret-sync
    when:
      any_changed:
        - ".github/workflows/**"
      min_change_intensity: ci-secret-change
    require:
      groups:
        - name: "Ops docs"
          any_changed:
            - "docs/ops/**"
            - "docs/runbook/**"
    severity: major
    message: "Workflow secret changed without ops docs"

gate:
  fail_on_blocker: true
  fail_on_major_count: 2

ignore_paths:
  - "**/__pycache__/**"
  - "**/*.pyc"
""",
    "db": """# Drift Gate policy: database migration sync
rules:
  - id: db-schema-sync
    when:
      any_changed:
        - "db/migrations/**"
        - "prisma/schema.prisma"
      min_change_intensity: db-schema-change
    require:
      groups:
        - name: "Migration runbook"
          any_changed:
            - "docs/runbook/**"
            - "docs/database/**"
        - name: "Verification"
          any_changed:
            - "tests/integration/**"
            - "tests/e2e/**"
    severity: major
    message: "DB schema changed without migration docs or verification"

gate:
  fail_on_blocker: true
  fail_on_major_count: 2

ignore_paths:
  - "**/__pycache__/**"
  - "**/*.pyc"
""",
    "env": """# Drift Gate policy: env/config sync
rules:
  - id: env-config-sync
    when:
      any_changed:
        - ".env"
        - ".env.*"
        - "src/config/**"
        - "config/**"
      min_change_intensity: config-key-added
    require:
      groups:
        - name: "Example env"
          all_changed:
            - ".env.example"
        - name: "Deployment docs"
          any_changed:
            - "docs/deployment/**"
            - "docs/runbook/**"
    severity: major
    message: "Environment/config changed without docs or .env.example update"

gate:
  fail_on_blocker: true
  fail_on_major_count: 2

ignore_paths:
  - "**/__pycache__/**"
  - "**/*.pyc"
""",
}
POLICY_PRESETS["fullstack"] = POLICY_TEMPLATE
POLICY_PRESETS['focused-python'] = '''# Explicit content checks for selected Python modules.
# Adjust source selectors and document ownership before using this in a project.
# This is not service-wide discovery or schema compatibility checking.
rules:
  - id: env-sample-content
    when:
      any_changed: ["src/config/**"]
      trigger: {family: env-key, predicate: key-changed, scope: selected-modules, on_unknown: review}
    require:
      groups:
        - name: Environment sample keys
          all_changed: [".env.example"]
          content: env-keys
    severity: blocker
    message: "추가한 환경 변수 키는 .env.example에 넣고, 코드에서 지운 키는 .env.example에서도 정리한 뒤 다시 검사하세요."
  - id: api-route-content
    when:
      any_changed: ["src/api/**"]
      trigger: {family: api-route, predicate: route-changed, scope: selected-modules, on_unknown: review}
    require:
      groups:
        - name: API route documentation
          all_changed: ["docs/openapi.json"]
          content: api-routes
    severity: blocker
    message: "추가·제거한 메서드와 경로를 연결된 API 문서에 반영한 뒤 다시 검사하세요."
gate:
  fail_on_blocker: true
  fail_on_major_count: 2
  on_unverified: warn
ignore_paths: ["**/__pycache__/**", "**/*.pyc"]
'''


