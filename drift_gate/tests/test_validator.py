"""
policy validator + 엣지 케이스 테스트.
"""
import os
import tempfile
import pytest
import yaml

from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.policy import Policy
from drift_gate.core.engine import run
from drift_gate.core.policy.validator import validate, PolicyValidationError
from drift_gate.adapters.policy_loader import load_policy
from drift_gate.core.policy.loader import PolicyLoadError


# ─── validator unit tests ─────────────────────────────────────────────────────

class TestValidator:

    def _policy(self, **overrides) -> Policy:
        base = {
            "rules": [{
                "id": "test-rule",
                "when": {"any_changed": ["src/routes/**"]},
                "require": {"groups": [
                    {"name": "docs", "any_changed": ["docs/spec.md"]}
                ]},
                "severity": "major",
            }],
            "gate": {},
            "ignore_paths": [],
        }
        base.update(overrides)
        return Policy.from_dict(base)

    def test_valid_policy_no_errors(self):
        vr = validate(self._policy())
        assert vr.ok
        assert vr.warnings == []

    def test_policy_enrichment_config_parses(self):
        policy = Policy.from_dict({
            "rules": [{
                "id": "test-rule",
                "when": {"any_changed": ["src/**"]},
                "require": {"groups": [{
                    "name": "docs",
                    "any_changed": ["docs/**"],
                }]},
                "severity": "major",
            }],
            "enrichment": {
                "provider": "claude",
                "mode": "comment-only",
            },
        })

        assert policy.enrichment.enabled
        assert policy.enrichment.provider == "claude"

    def test_cross_file_relation_validates_group_references(self):
        policy = Policy.from_dict({
            "rules": [{
                "id": "api-cross-file",
                "when": {"any_changed": ["openapi/**"]},
                "require": {
                    "groups": [
                        {
                            "name": "SDK contract",
                            "any_changed": ["sdk/**"],
                            "required": False,
                        },
                    ],
                    "cross_file": [{
                        "name": "openapi-sdk",
                        "when_any_changed": ["openapi/**"],
                        "require_groups": ["SDK contract"],
                    }],
                },
                "severity": "major",
            }],
        })

        assert validate(policy).ok

    def test_cross_file_relation_rejects_unknown_group(self):
        policy = Policy.from_dict({
            "rules": [{
                "id": "api-cross-file",
                "when": {"any_changed": ["openapi/**"]},
                "require": {
                    "groups": [
                        {"name": "API docs", "any_changed": ["docs/api/**"]},
                    ],
                    "cross_file": [{
                        "name": "openapi-sdk",
                        "when_any_changed": ["openapi/**"],
                        "require_groups": ["SDK contract"],
                    }],
                },
                "severity": "major",
            }],
        })

        vr = validate(policy)

        assert not vr.ok
        assert any("정의되지 않은 require group" in error for error in vr.errors)

    def test_duplicate_rule_id(self):
        policy = Policy.from_dict({
            "rules": [
                {"id": "dup", "when": {"any_changed": ["a/**"]},
                 "require": {"groups": [{"name": "g", "any_changed": ["b/**"]}]},
                 "severity": "minor"},
                {"id": "dup", "when": {"any_changed": ["c/**"]},
                 "require": {"groups": [{"name": "g", "any_changed": ["d/**"]}]},
                 "severity": "minor"},
            ]
        })
        vr = validate(policy)
        assert not vr.ok
        assert any("중복" in e for e in vr.errors)

    def test_invalid_severity(self):
        policy = Policy.from_dict({
            "rules": [{
                "id": "bad-sev",
                "when": {"any_changed": ["src/**"]},
                "require": {"groups": [{"name": "g", "any_changed": ["docs/**"]}]},
                "severity": "critical",   # 잘못된 값
            }]
        })
        vr = validate(policy)
        assert not vr.ok
        assert any("severity" in e for e in vr.errors)

    def test_empty_when_any_changed(self):
        policy = Policy.from_dict({
            "rules": [{
                "id": "empty-when",
                "when": {},
                "require": {"groups": [{"name": "g", "any_changed": ["docs/**"]}]},
                "severity": "minor",
            }]
        })
        vr = validate(policy)
        assert not vr.ok
        assert any("when" in e for e in vr.errors)

    def test_invalid_min_change_intensity(self):
        policy = Policy.from_dict({
            "rules": [{
                "id": "bad-intensity",
                "when": {
                    "any_changed": ["src/**"],
                    "min_change_intensity": "huge",
                },
                "require": {"groups": [
                    {"name": "g", "any_changed": ["docs/**"]}
                ]},
                "severity": "minor",
            }]
        })
        vr = validate(policy)
        assert not vr.ok
        assert any("min_change_intensity" in e for e in vr.errors)

    def test_when_pattern_covered_by_ignore_paths_warns(self):
        policy = Policy.from_dict({
            "rules": [{
                "id": "dead-rule",
                "when": {"any_changed": ["src/internal/**"]},
                "require": {"groups": [{"name": "g", "any_changed": ["docs/**"]}]},
                "severity": "minor",
            }],
            "ignore_paths": ["src/internal/**"],
        })
        vr = validate(policy)
        # errors 없음, warnings 있음
        assert vr.ok
        assert any("활성화" in w for w in vr.warnings)

    def test_require_path_covered_by_ignore_paths_warns(self):
        policy = Policy.from_dict({
            "rules": [{
                "id": "blocked-require",
                "when": {"any_changed": ["src/routes/**"]},
                "require": {"groups": [{"name": "docs", "any_changed": ["docs/spec.md"]}]},
                "severity": "blocker",
            }],
            "ignore_paths": ["docs/spec.md"],
        })
        vr = validate(policy)
        assert vr.ok  # error 아님, warning
        assert any("충족" in w for w in vr.warnings)

    def test_raise_if_errors(self):
        policy = Policy.from_dict({
            "rules": [{
                "id": "bad",
                "when": {"any_changed": ["src/**"]},
                "require": {"groups": [{"name": "g", "any_changed": ["docs/**"]}]},
                "severity": "invalid-severity",
            }]
        })
        vr = validate(policy)
        with pytest.raises(PolicyValidationError):
            vr.raise_if_errors()

    def test_loader_surfaces_errors(self):
        data = {"rules": [{"id": "dup", "when": {"any_changed": ["a/**"]},
                           "require": {"groups": [{"name":"g","any_changed":["b/**"]}]},
                           "severity": "critical"}]}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", delete=False, encoding="utf-8"
        ) as f:
            yaml.dump(data, f, allow_unicode=True)
            path = f.name
        try:
            with pytest.raises(PolicyLoadError):
                load_policy(path)
        finally:
            os.unlink(path)


# ─── edge cases: renamed / deleted files ──────────────────────────────────────

class TestEdgeCases:

    def _api_policy(self) -> Policy:
        return Policy.from_dict({
            "rules": [{
                "id": "api-contract-sync",
                "when": {"any_changed": ["src/routes/**"]},
                "require": {"groups": [
                    {"name": "API 계약 문서", "any_changed": ["docs/spec.md"]},
                ]},
                "severity": "blocker",
                "message": "API surface changed without docs",
            }],
            "gate": {"fail_on_blocker": True, "fail_on_major_count": 2},
        })

    def test_renamed_file_triggers_when_via_previous_path(self):
        """이전 경로가 when 패턴에 매칭되면 규칙 활성화."""
        policy = self._api_policy()
        files = [
            ChangedFile(
                path="src/routes/users_v2.ts",
                status="renamed",
                previous_path="src/routes/users.ts",
            )
        ]
        result = run(changed_files=files, policy=policy)
        assert len(result.violations) == 1

    def test_renamed_file_can_satisfy_require(self):
        """rename 이후 경로가 require 조건을 충족하면 통과."""
        policy = self._api_policy()
        files = [
            ChangedFile(path="src/routes/users.ts", status="modified"),
            ChangedFile(
                path="docs/spec.md",
                status="renamed",
                previous_path="docs/spec_old.md",
            ),
        ]
        result = run(changed_files=files, policy=policy)
        assert result.violations == []

    def test_deleted_file_does_not_satisfy_all_changed(self):
        """삭제된 파일은 all_changed 충족으로 보지 않음."""
        policy = Policy.from_dict({
            "rules": [{
                "id": "changelog-required",
                "when": {"any_changed": ["src/routes/**"]},
                "require": {"groups": [
                    {"name": "릴리즈 공지", "all_changed": ["CHANGELOG.md"]},
                ]},
                "severity": "blocker",
                "message": "CHANGELOG missing",
            }],
            "gate": {},
        })
        files = [
            ChangedFile(path="src/routes/users.ts", status="modified"),
            ChangedFile(path="CHANGELOG.md", status="deleted"),   # 삭제됨
        ]
        result = run(changed_files=files, policy=policy)
        assert len(result.violations) == 1

    def test_deleted_file_does_not_satisfy_any_changed(self):
        """삭제된 파일은 any_changed 충족으로도 보지 않음."""
        policy = self._api_policy()
        files = [
            ChangedFile(path="src/routes/users.ts", status="modified"),
            ChangedFile(path="docs/spec.md", status="deleted"),   # 삭제됨
        ]
        result = run(changed_files=files, policy=policy)
        assert len(result.violations) == 1

    def test_ignore_paths_excludes_from_require_satisfaction(self):
        """ignore_paths에 포함된 파일은 require.groups 충족에 사용 불가."""
        policy = Policy.from_dict({
            "rules": [{
                "id": "api-contract-sync",
                "when": {"any_changed": ["src/routes/**"]},
                "require": {"groups": [
                    {"name": "docs", "any_changed": ["docs/spec.md"]},
                ]},
                "severity": "blocker",
                "message": "test",
            }],
            "gate": {},
            "ignore_paths": ["docs/spec.md"],   # require 경로를 ignore — 버그 패턴
        })
        files = [
            ChangedFile(path="src/routes/users.ts", status="modified"),
            ChangedFile(path="docs/spec.md", status="modified"),
        ]
        result = run(changed_files=files, policy=policy)
        # docs/spec.md가 ignore_paths에 포함되어 있으므로 require 충족 불가 → 위반
        assert len(result.violations) == 1

    def test_ignore_paths_excludes_from_trigger(self):
        """ignore_paths에 포함된 파일은 when 트리거에도 사용 불가."""
        policy = Policy.from_dict({
            "rules": [{
                "id": "api-contract-sync",
                "when": {"any_changed": ["src/routes/**"]},
                "require": {"groups": [
                    {"name": "docs", "any_changed": ["docs/spec.md"]},
                ]},
                "severity": "blocker",
                "message": "test",
            }],
            "gate": {},
            "ignore_paths": ["src/routes/**"],   # trigger 경로를 ignore
        })
        files = [
            ChangedFile(path="src/routes/users.ts", status="modified"),
        ]
        result = run(changed_files=files, policy=policy)
        # src/routes/users.ts가 ignore_paths에 포함 → rule 활성화 안 됨 → 통과
        assert result.violations == []


# ─── local git adapter edge cases ─────────────────────────────────────────────

class TestGitAdapter:

    def test_local_git_adapter_preserves_patch(self, monkeypatch):
        """로컬 CLI 모드도 GitHub PR API처럼 ChangedFile.patch를 채운다."""
        from drift_gate.adapters.git.client import GitAdapter

        calls = []

        def fake_check_output(args, text=True, encoding=None, errors=None, stderr=None):
            calls.append(args)
            if "--name-status" in args:
                return "M\tsrc/routes/users.ts\n"
            return (
                "diff --git a/src/routes/users.ts b/src/routes/users.ts\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
            )

        monkeypatch.setattr("subprocess.check_output", fake_check_output)

        files = GitAdapter().get_changed_files("main")

        assert len(files) == 1
        assert files[0].path == "src/routes/users.ts"
        assert files[0].patch.startswith("diff --git")
        assert calls[1] == [
            "git", "diff", "--find-renames", "main",
            "--", "src/routes/users.ts",
        ]

    def test_git_adapter_skips_binary_and_large_patches(self, monkeypatch):
        from drift_gate.adapters.git.client import GitAdapter

        def fake_check_output(args, **kwargs):
            if "--name-status" in args:
                return "M\tassets/logo.png\nM\tsrc/big.py\n"
            if "assets/logo.png" in args:
                return "binary data"
            return "x" * 100

        monkeypatch.setattr("subprocess.check_output", fake_check_output)
        monkeypatch.setenv("DRIFT_GATE_MAX_PATCH_BYTES", "10")

        files = GitAdapter().get_changed_files("main")

        assert files[0].patch == "[binary file skipped]"
        assert files[1].patch == "[large file skipped]"

    def test_core_scan_metrics_supports_large_pr(self):
        files = [
            ChangedFile(path=f"docs/file_{i}.md", status="modified")
            for i in range(125)
        ]
        result = run(changed_files=files, policy=Policy.from_dict({
            "rules": [{
                "id": "api-contract-sync",
                "when": {"any_changed": ["src/routes/**"]},
                "require": {"groups": [{
                    "name": "docs",
                    "any_changed": ["docs/**"],
                }]},
                "severity": "major",
            }],
        }))

        assert result.scan_metrics.scanned_files == 125
        assert result.scan_metrics.evaluated_rules == 1


# ─── patch intensity classifier ───────────────────────────────────────────────

class TestChangeIntensity:

    def _policy(self, min_change_intensity: str = "signature-change") -> Policy:
        return Policy.from_dict({
            "rules": [{
                "id": "api-contract-sync",
                "when": {
                    "any_changed": ["src/routes/**"],
                    "min_change_intensity": min_change_intensity,
                },
                "require": {"groups": [
                    {"name": "API 계약 문서", "any_changed": ["docs/spec.md"]},
                ]},
                "severity": "blocker",
                "message": "API surface changed without docs",
            }],
            "gate": {"fail_on_blocker": True, "fail_on_major_count": 2},
        })

    def test_comment_only_patch_does_not_trigger_signature_rule(self):
        files = [ChangedFile(
            path="src/routes/users.ts",
            status="modified",
            patch=(
                "diff --git a/src/routes/users.ts b/src/routes/users.ts\n"
                "@@ -1 +1 @@\n"
                "-// old note\n"
                "+// new note\n"
            ),
        )]

        result = run(changed_files=files, policy=self._policy())

        assert result.violations == []
        assert result.result == "pass"

    def test_signature_patch_triggers_signature_rule(self):
        files = [ChangedFile(
            path="src/routes/users.ts",
            status="modified",
            patch=(
                "diff --git a/src/routes/users.ts b/src/routes/users.ts\n"
                "@@ -1 +1 @@\n"
                "-export function getUser(id: string) {\n"
                "+export function getUser(id: string, includePosts: boolean) {\n"
            ),
        )]

        result = run(changed_files=files, policy=self._policy())

        assert len(result.violations) == 1
        assert result.violations[0].change_intensity == "signature-change"

    def test_impl_patch_triggers_impl_rule(self):
        files = [ChangedFile(
            path="src/routes/users.ts",
            status="modified",
            patch=(
                "diff --git a/src/routes/users.ts b/src/routes/users.ts\n"
                "@@ -1 +1 @@\n"
                "-  return getUser(id)\n"
                "+  return getUserFromCache(id)\n"
            ),
        )]

        result = run(
            changed_files=files,
            policy=self._policy(min_change_intensity="impl-only"),
        )

        assert len(result.violations) == 1
        assert result.violations[0].change_intensity == "impl-only"

    def test_env_key_patch_triggers_config_key_rule(self):
        files = [ChangedFile(
            path="src/config/env.ts",
            status="modified",
            patch=(
                "diff --git a/src/config/env.ts b/src/config/env.ts\n"
                "@@ -1 +1,2 @@\n"
                " export const port = process.env.PORT\n"
                "+export const stripeKey = process.env.STRIPE_SECRET_KEY\n"
            ),
        )]

        policy = Policy.from_dict({
            "rules": [{
                "id": "env-config-sync",
                "when": {
                    "any_changed": ["src/config/**"],
                    "min_change_intensity": "config-key-added",
                },
                "require": {"groups": [
                    {"name": "Example env", "all_changed": [".env.example"]},
                ]},
                "severity": "major",
                "message": "config key added without example env",
            }],
            "gate": {"fail_on_blocker": True, "fail_on_major_count": 1},
        })

        result = run(changed_files=files, policy=policy)

        assert len(result.violations) == 1
        assert result.violations[0].change_intensity == "config-key-added"

    def test_route_patch_triggers_route_contract_rule(self):
        files = [ChangedFile(
            path="src/routes/billing.ts",
            status="modified",
            patch=(
                "diff --git a/src/routes/billing.ts b/src/routes/billing.ts\n"
                "@@ -1 +1,2 @@\n"
                " router.get('/billing', listBilling)\n"
                "+router.post('/billing/:id/refund', refundPayment)\n"
            ),
        )]

        policy = self._policy(min_change_intensity="route-contract-change")

        result = run(changed_files=files, policy=policy)

        assert len(result.violations) == 1
        assert result.violations[0].change_intensity == "route-contract-change"

    def test_route_method_and_path_param_change_triggers_route_contract_rule(self):
        files = [ChangedFile(
            path="src/routes/users.ts",
            status="modified",
            patch=(
                "diff --git a/src/routes/users.ts b/src/routes/users.ts\n"
                "@@ -1 +1 @@\n"
                "-router.get('/users/:id', getUser)\n"
                "+router.patch('/users/:userId', updateUser)\n"
            ),
        )]

        result = run(
            changed_files=files,
            policy=self._policy(min_change_intensity="route-contract-change"),
        )

        assert len(result.violations) == 1
        assert result.violations[0].change_intensity == "route-contract-change"

    def test_request_response_schema_change_triggers_route_contract_rule(self):
        files = [ChangedFile(
            path="src/routes/users.ts",
            status="modified",
            patch=(
                "diff --git a/src/routes/users.ts b/src/routes/users.ts\n"
                "@@ -1 +1 @@\n"
                "+export interface CreateUserRequest { email: string; plan: string }\n"
            ),
        )]

        result = run(
            changed_files=files,
            policy=self._policy(min_change_intensity="route-contract-change"),
        )

        assert len(result.violations) == 1
        assert result.violations[0].change_intensity == "route-contract-change"

    def test_sdk_client_contract_change_triggers_api_rule(self):
        files = [ChangedFile(
            path="sdk/users.ts",
            status="modified",
            patch=(
                "diff --git a/sdk/users.ts b/sdk/users.ts\n"
                "@@ -1 +1 @@\n"
                "+export function getUser(id: string, includePosts: boolean) {}\n"
            ),
        )]
        policy = Policy.from_dict({
            "rules": [{
                "id": "sdk-contract-sync",
                "when": {
                    "any_changed": ["sdk/**"],
                    "min_change_intensity": "signature-change",
                },
                "require": {"groups": [
                    {"name": "SDK docs", "any_changed": ["docs/sdk/**"]},
                ]},
                "severity": "major",
            }],
            "gate": {"fail_on_blocker": True, "fail_on_major_count": 1},
        })

        result = run(changed_files=files, policy=policy)

        assert len(result.violations) == 1
        assert "api-surface" in result.violations[0].change_types

    def test_db_patch_triggers_db_schema_rule(self):
        files = [ChangedFile(
            path="db/migrations/20260520_add_plan.sql",
            status="modified",
            patch=(
                "diff --git a/db/migrations/20260520_add_plan.sql b/db/migrations/20260520_add_plan.sql\n"
                "@@ -1 +1 @@\n"
                "+ALTER TABLE users ADD COLUMN plan_id TEXT;\n"
            ),
        )]
        policy = Policy.from_dict({
            "rules": [{
                "id": "db-schema-sync",
                "when": {
                    "any_changed": ["db/migrations/**"],
                    "min_change_intensity": "db-schema-change",
                },
                "require": {"groups": [
                    {"name": "Runbook", "any_changed": ["docs/runbook/**"]},
                ]},
                "severity": "major",
                "message": "DB schema changed without runbook",
            }],
            "gate": {"fail_on_blocker": True, "fail_on_major_count": 1},
        })

        result = run(changed_files=files, policy=policy)

        assert len(result.violations) == 1
        assert result.violations[0].change_intensity == "db-schema-change"

    def test_db_nullable_default_and_index_change_triggers_db_schema_rule(self):
        files = [ChangedFile(
            path="db/migrations/20260520_index_users.sql",
            status="modified",
            patch=(
                "diff --git a/db/migrations/20260520_index_users.sql b/db/migrations/20260520_index_users.sql\n"
                "@@ -1 +1,2 @@\n"
                "+ALTER TABLE users ALTER COLUMN email SET NOT NULL;\n"
                "+CREATE UNIQUE INDEX users_email_idx ON users(email);\n"
            ),
        )]
        policy = Policy.from_dict({
            "rules": [{
                "id": "db-schema-sync",
                "when": {
                    "any_changed": ["db/migrations/**"],
                    "min_change_intensity": "db-schema-change",
                },
                "require": {"groups": [
                    {"name": "Runbook", "any_changed": ["docs/runbook/**"]},
                ]},
                "severity": "major",
            }],
            "gate": {"fail_on_blocker": True, "fail_on_major_count": 1},
        })

        result = run(changed_files=files, policy=policy)

        assert len(result.violations) == 1
        assert result.violations[0].change_intensity == "db-schema-change"

    def test_auth_patch_triggers_auth_policy_rule(self):
        files = [ChangedFile(
            path="src/auth/rbac.ts",
            status="modified",
            patch=(
                "diff --git a/src/auth/rbac.ts b/src/auth/rbac.ts\n"
                "@@ -1 +1 @@\n"
                "+permissions.admin.refund = true\n"
            ),
        )]
        policy = Policy.from_dict({
            "rules": [{
                "id": "auth-security-sync",
                "when": {
                    "any_changed": ["src/auth/**"],
                    "min_change_intensity": "auth-policy-change",
                },
                "require": {"groups": [
                    {"name": "Security docs", "any_changed": ["docs/security/**"]},
                ]},
                "severity": "blocker",
                "message": "Auth policy changed without security docs",
            }],
            "gate": {"fail_on_blocker": True, "fail_on_major_count": 2},
        })

        result = run(changed_files=files, policy=policy)

        assert len(result.violations) == 1
        assert result.violations[0].change_intensity == "auth-policy-change"

    def test_ci_secret_patch_triggers_ci_secret_rule(self):
        files = [ChangedFile(
            path=".github/workflows/deploy.yml",
            status="modified",
            patch=(
                "diff --git a/.github/workflows/deploy.yml b/.github/workflows/deploy.yml\n"
                "@@ -1 +1 @@\n"
                "+      DEPLOY_TOKEN: ${{ secrets.PROD_DEPLOY_TOKEN }}\n"
            ),
        )]
        policy = Policy.from_dict({
            "rules": [{
                "id": "workflow-secret-sync",
                "when": {
                    "any_changed": [".github/workflows/**"],
                    "min_change_intensity": "ci-secret-change",
                },
                "require": {"groups": [
                    {"name": "Ops docs", "any_changed": ["docs/ops/**"]},
                ]},
                "severity": "major",
                "message": "Workflow secret changed without ops docs",
            }],
            "gate": {"fail_on_blocker": True, "fail_on_major_count": 1},
        })

        result = run(changed_files=files, policy=policy)

        assert len(result.violations) == 1
        assert result.violations[0].change_intensity == "ci-secret-change"

    def test_env_secret_rename_and_config_schema_triggers_config_rule(self):
        files = [ChangedFile(
            path="src/config/settings.py",
            status="modified",
            patch=(
                "diff --git a/src/config/settings.py b/src/config/settings.py\n"
                "@@ -1 +1,3 @@\n"
                "-OLD_SECRET_KEY = os.environ.get('OLD_SECRET_KEY')\n"
                "+NEW_SECRET_KEY = os.environ.get('NEW_SECRET_KEY')\n"
                "+class Settings(BaseSettings):\n"
                "+    api_key: str\n"
            ),
        )]
        policy = Policy.from_dict({
            "rules": [{
                "id": "env-config-sync",
                "when": {
                    "any_changed": ["src/config/**", "**/settings.py"],
                    "min_change_intensity": "config-key-added",
                },
                "require": {"groups": [
                    {"name": "Example env", "all_changed": [".env.example"]},
                ]},
                "severity": "major",
            }],
            "gate": {"fail_on_blocker": True, "fail_on_major_count": 1},
        })

        result = run(changed_files=files, policy=policy)

        assert len(result.violations) == 1
        assert result.violations[0].change_intensity == "config-key-added"

    def test_deploy_docker_and_terraform_changes_trigger_ci_rule(self):
        files = [
            ChangedFile(
                path=".github/workflows/deploy.yml",
                status="modified",
                patch=(
                    "diff --git a/.github/workflows/deploy.yml b/.github/workflows/deploy.yml\n"
                    "@@ -1 +1 @@\n"
                    "+      - run: kubectl rollout restart deployment/api\n"
                ),
            ),
            ChangedFile(
                path="Dockerfile",
                status="modified",
                patch=(
                    "diff --git a/Dockerfile b/Dockerfile\n"
                    "@@ -1 +1 @@\n"
                    "+FROM python:3.12-slim\n"
                ),
            ),
            ChangedFile(
                path="terraform/main.tf",
                status="modified",
                patch=(
                    "diff --git a/terraform/main.tf b/terraform/main.tf\n"
                    "@@ -1 +1 @@\n"
                    "+resource \"aws_ecs_service\" \"api\" {}\n"
                ),
            ),
        ]
        policy = Policy.from_dict({
            "rules": [{
                "id": "workflow-secret-sync",
                "when": {
                    "any_changed": [".github/workflows/**", "Dockerfile", "terraform/**"],
                    "min_change_intensity": "ci-secret-change",
                },
                "require": {"groups": [
                    {"name": "Ops docs", "any_changed": ["docs/ops/**"]},
                ]},
                "severity": "major",
            }],
            "gate": {"fail_on_blocker": True, "fail_on_major_count": 1},
        })

        result = run(changed_files=files, policy=policy)

        assert len(result.violations) == 1
        assert result.violations[0].change_intensity == "ci-secret-change"

    def test_auth_middleware_and_policy_file_change_trigger_auth_rule(self):
        files = [ChangedFile(
            path="src/auth/middleware.ts",
            status="modified",
            patch=(
                "diff --git a/src/auth/middleware.ts b/src/auth/middleware.ts\n"
                "@@ -1 +1,2 @@\n"
                "+export const authMiddleware = requireAuth({ role: 'admin' })\n"
                "+policy: allow-admin-refunds\n"
            ),
        )]
        policy = Policy.from_dict({
            "rules": [{
                "id": "auth-security-sync",
                "when": {
                    "any_changed": ["src/auth/**"],
                    "min_change_intensity": "auth-policy-change",
                },
                "require": {"groups": [
                    {"name": "Security docs", "any_changed": ["docs/security/**"]},
                ]},
                "severity": "blocker",
            }],
            "gate": {"fail_on_blocker": True, "fail_on_major_count": 2},
        })

        result = run(changed_files=files, policy=policy)

        assert len(result.violations) == 1
        assert result.violations[0].change_intensity == "auth-policy-change"

    def test_cli_breaking_behavior_triggers_cli_rule(self):
        files = [ChangedFile(
            path="main.py",
            status="modified",
            patch=(
                "diff --git a/main.py b/main.py\n"
                "@@ -1 +1 @@\n"
                "+parser.add_argument('--config', required=True)\n"
            ),
        )]
        policy = Policy.from_dict({
            "rules": [{
                "id": "cli-public-interface-sync",
                "when": {
                    "any_changed": ["main.py"],
                    "min_change_intensity": "public-cli-change",
                },
                "require": {"groups": [
                    {"name": "CLI docs", "any_changed": ["docs/cli/**"]},
                ]},
                "severity": "major",
            }],
            "gate": {"fail_on_blocker": True, "fail_on_major_count": 1},
        })

        result = run(changed_files=files, policy=policy)

        assert len(result.violations) == 1
        assert result.violations[0].change_intensity == "public-cli-change"

    def test_public_cli_patch_triggers_cli_rule(self):
        files = [ChangedFile(
            path="main.py",
            status="modified",
            patch=(
                "diff --git a/main.py b/main.py\n"
                "@@ -1 +1,2 @@\n"
                " parser = argparse.ArgumentParser()\n"
                "+parser.add_argument('--dry-run', action='store_true')\n"
            ),
        )]
        policy = Policy.from_dict({
            "rules": [{
                "id": "cli-public-interface-sync",
                "when": {
                    "any_changed": ["main.py"],
                    "min_change_intensity": "public-cli-change",
                },
                "require": {"groups": [
                    {"name": "CLI docs", "any_changed": ["docs/cli/**", "README.md"]},
                ]},
                "severity": "major",
                "message": "CLI changed without docs",
            }],
            "gate": {"fail_on_blocker": True, "fail_on_major_count": 1},
        })

        result = run(changed_files=files, policy=policy)

        assert len(result.violations) == 1
        violation = result.violations[0]
        assert violation.change_type == "cli-public-interface"
        assert violation.change_intensity == "public-cli-change"
        assert "CLI users" in violation.blast_radius
        assert "README/help documentation" in violation.blast_radius

    def test_semantic_signal_overrides_patch_fallback(self):
        files = [ChangedFile(
            path="src/routes/users.ts",
            status="modified",
            patch="",
            semantic_signals=["route-contract-change"],
        )]

        result = run(
            changed_files=files,
            policy=self._policy(min_change_intensity="route-contract-change"),
        )

        assert len(result.violations) == 1
        assert result.violations[0].change_intensity == "route-contract-change"


# ─── Claude enricher fallback ─────────────────────────────────────────────────

class TestClaudeEnricherFallback:

    def test_fallback_checklist_preserved_on_api_failure(self):
        """ClaudeEnricher API 실패 시 기존 fallback checklist 유지."""
        from drift_gate.adapters.claude.enricher import ClaudeEnricher
        from drift_gate.core.models.result import (
            EvaluationResult, Violation, UnsatisfiedGroup,
        )
        from drift_gate.core.models.policy import Gate

        v = Violation(
            rule_id="test",
            severity="BLOCKER",
            confidence="high",
            change_types=["api-surface"],
            change_type="api-surface",
            message="test",
            trigger_files=[],
            unsatisfied_groups=[
                UnsatisfiedGroup(name="API 계약 문서", required=["docs/spec.md"], type="any_changed")
            ],
            checklist=["관련 spec/API 문서를 변경 내용에 맞게 업데이트"],
        )
        result = EvaluationResult(
            change_types=["api-surface"],
            violations=[v],
            skipped_rules=[],
            rejected_ignores=[],
            gate=Gate(),
            result="fail",
        )

        # 잘못된 API key → 실패해도 checklist 유지 확인
        enricher = ClaudeEnricher(api_key="invalid-key")
        enriched = enricher.enrich(result)

        assert enriched.violations[0].checklist == ["관련 spec/API 문서를 변경 내용에 맞게 업데이트"]

    def test_enricher_parses_extended_fields(self, monkeypatch):
        from drift_gate.adapters.claude.enricher import ClaudeEnricher
        from drift_gate.core.models.result import (
            EvaluationResult, Violation, UnsatisfiedGroup,
        )
        from drift_gate.core.models.policy import Gate

        v = Violation(
            rule_id="api-contract-sync",
            severity="BLOCKER",
            confidence="high",
            change_types=["api-surface"],
            change_type="api-surface",
            message="API changed",
            trigger_files=[],
            unsatisfied_groups=[
                UnsatisfiedGroup(name="API docs", required=["docs/api/**"], type="any_changed")
            ],
            checklist=["fallback"],
        )
        result = EvaluationResult(
            change_types=["api-surface"],
            violations=[v],
            skipped_rules=[],
            rejected_ignores=[],
            gate=Gate(),
            result="fail",
        )

        def fake_call(self, prompt):
            text = (
                "### [BLOCKER] api-contract-sync\n"
                "체크리스트:\n"
                "- [ ] Update docs/api/users.md\n"
                "Changed contract summary: User response changed.\n"
                "Missing docs explanation: API docs must mention the response.\n"
                "Docs update draft: Add a response field note.\n"
                "False positive candidate: Low.\n"
            )
            return text, None  # (text, metrics) — metrics not needed in this test

        monkeypatch.setattr(ClaudeEnricher, "_call_api", fake_call)

        enriched = ClaudeEnricher(api_key="key").enrich(result)
        violation = enriched.violations[0]

        assert violation.checklist == ["Update docs/api/users.md"]
        assert violation.changed_contract_summary == "User response changed."
        assert "API docs" in violation.missing_docs_explanation
        assert violation.docs_update_draft == "Add a response field note."
        assert violation.false_positive_note == "Low."


# ─── Markdown reporter edge cases ────────────────────────────────────────────

class TestMarkdownReporterEdgeCases:

    def test_rejected_ignores_section_present(self):
        from drift_gate.reporters.markdown import MarkdownReporter
        from drift_gate.core.models.result import (
            EvaluationResult, Violation, UnsatisfiedGroup,
            RejectedIgnore,
        )
        from drift_gate.core.models.policy import Gate

        result = EvaluationResult(
            change_types=["api-surface"],
            violations=[
                Violation(
                    rule_id="api-contract-sync",
                    severity="BLOCKER",
                    confidence="high",
                    change_types=["api-surface"],
                    change_type="api-surface",
                    message="test",
                    trigger_files=[ChangedFile(path="src/routes/a.ts", status="modified")],
                    unsatisfied_groups=[
                        UnsatisfiedGroup(name="API 계약 문서", required=["docs/spec.md"], type="any_changed")
                    ],
                    checklist=["docs 업데이트"],
                )
            ],
            skipped_rules=[],
            rejected_ignores=[
                RejectedIgnore(rule_id="api-contract-sync", severity="BLOCKER", message="test")
            ],
            gate=Gate(),
            result="fail",
        )
        md = MarkdownReporter().render(result)
        assert "거부된 ignore" in md
        assert "api-contract-sync" in md

    def test_medium_confidence_shows_추정_label(self):
        from drift_gate.reporters.markdown import MarkdownReporter
        from drift_gate.core.models.result import (
            EvaluationResult, Violation, UnsatisfiedGroup,
        )
        from drift_gate.core.models.policy import Gate

        result = EvaluationResult(
            change_types=["api-surface"],
            violations=[
                Violation(
                    rule_id="test-rule",
                    severity="MAJOR",
                    confidence="medium",   # ← 추정 라벨 트리거
                    change_types=["api-surface"],
                    change_type="api-surface",
                    message="test",
                    trigger_files=[ChangedFile(path="src/routes/a.ts", status="renamed")],
                    unsatisfied_groups=[
                        UnsatisfiedGroup(name="docs", required=["docs/spec.md"], type="any_changed")
                    ],
                    checklist=[],
                )
            ],
            skipped_rules=[],
            rejected_ignores=[],
            gate=Gate(),
            result="warn",
        )
        md = MarkdownReporter().render(result)
        assert "[추정]" in md

    def test_skipped_rules_section_present(self):
        from drift_gate.reporters.markdown import MarkdownReporter
        from drift_gate.core.models.result import EvaluationResult, SkippedRule
        from drift_gate.core.models.policy import Gate

        result = EvaluationResult(
            change_types=[],
            violations=[],
            skipped_rules=[
                SkippedRule(rule_id="workflow-ops-doc", severity="MINOR",
                            reason="dev-only", message="test")
            ],
            rejected_ignores=[],
            gate=Gate(),
            result="pass",
        )
        md = MarkdownReporter().render(result)
        assert "적용된 ignore" in md
        assert "workflow-ops-doc" in md
