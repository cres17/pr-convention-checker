"""
Core engine 통합 테스트 — fixtures 기반.
외부 I/O 없음.
"""
import json
from pathlib import Path
import tempfile
import os
import pytest

from drift_gate.core.engine import run
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.policy import Policy
from drift_gate.core.models.result import DriftIgnoreDirective

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def fixture_to_args(data: dict):
    changed_files = [ChangedFile.from_dict(f) for f in data["changed_files"]]
    drift_ignores = [DriftIgnoreDirective.from_dict(d) for d in data.get("drift_ignores", [])]
    policy = Policy.from_dict(data["policy"])
    return changed_files, drift_ignores, policy


# ─── fixture 기반 시나리오 ────────────────────────────────────────────────────

class TestFixtureScenarios:
    def test_api_change_blocker(self):
        data = load_fixture("pr_api_change.json")
        files, ignores, policy = fixture_to_args(data)
        result = run(changed_files=files, drift_ignores=ignores, policy=policy)

        exp = data["expected"]
        assert result.result == exp["result"]
        assert result.blocker_count == exp["blocker_count"]
        assert result.major_count == exp["major_count"]
        assert sorted(v.rule_id for v in result.violations) == sorted(exp["violation_rule_ids"])

    def test_db_change_major(self):
        data = load_fixture("pr_db_change.json")
        files, ignores, policy = fixture_to_args(data)
        result = run(changed_files=files, drift_ignores=ignores, policy=policy)

        exp = data["expected"]
        assert result.result == exp["result"]
        assert result.blocker_count == exp["blocker_count"]
        assert result.major_count == exp["major_count"]
        assert sorted(v.rule_id for v in result.violations) == sorted(exp["violation_rule_ids"])

    def test_docs_only_pass(self):
        data = load_fixture("pr_docs_only.json")
        files, ignores, policy = fixture_to_args(data)
        result = run(changed_files=files, drift_ignores=ignores, policy=policy)

        exp = data["expected"]
        assert result.result == exp["result"]
        assert result.skip is True
        assert result.skip_reason == exp["skip_reason"]
        assert result.blocker_count == 0

    def test_file_delete_triggers_rule(self):
        """File deletion on monitored path should still trigger rule."""
        data = load_fixture("pr_file_delete.json")
        files, ignores, policy = fixture_to_args(data)
        result = run(changed_files=files, drift_ignores=ignores, policy=policy)

        exp = data["expected"]
        assert result.result == exp["result"]
        assert result.blocker_count == exp["blocker_count"]
        assert sorted(v.rule_id for v in result.violations) == sorted(exp["violation_rule_ids"])

    def test_file_rename_preserved(self):
        """File rename (previous_path set) should trigger rule normally."""
        data = load_fixture("pr_file_rename.json")
        files, ignores, policy = fixture_to_args(data)
        result = run(changed_files=files, drift_ignores=ignores, policy=policy)

        exp = data["expected"]
        assert result.result == exp["result"]
        assert result.major_count == exp["major_count"]
        assert sorted(v.rule_id for v in result.violations) == sorted(exp["violation_rule_ids"])

    def test_ignore_paths_excludes_from_evaluation(self):
        """Files matching ignore_paths should not trigger any rules."""
        data = load_fixture("pr_ignore_paths.json")
        files, ignores, policy = fixture_to_args(data)
        result = run(changed_files=files, drift_ignores=ignores, policy=policy)

        exp = data["expected"]
        assert result.result == exp["result"]
        assert result.blocker_count == exp["blocker_count"]
        assert result.major_count == exp["major_count"]
        assert len(result.violations) == 0

    def test_reject_ignore_blocker_no_reason(self):
        """BLOCKER drift-ignore without reason should be rejected."""
        data = load_fixture("pr_reject_ignore_blocker.json")
        files, ignores, policy = fixture_to_args(data)
        result = run(changed_files=files, drift_ignores=ignores, policy=policy)

        exp = data["expected"]
        assert result.result == exp["result"]
        assert result.blocker_count == exp["blocker_count"]
        assert len(result.rejected_ignores) == 1
        assert result.rejected_ignores[0].rule_id == "db-schema-sync"

    def test_empty_pr_passes(self):
        """PR with no changes should pass immediately."""
        data = load_fixture("pr_empty.json")
        files, ignores, policy = fixture_to_args(data)
        result = run(changed_files=files, drift_ignores=ignores, policy=policy)

        exp = data["expected"]
        assert result.result == exp["result"]
        assert result.blocker_count == exp["blocker_count"]
        assert result.major_count == exp["major_count"]
        assert len(result.violations) == 0

    def test_tests_only_pr_passes(self):
        """Tests-only changes should skip policy evaluation."""
        data = load_fixture("pr_tests_only_api_no_doc.json")
        files, ignores, policy = fixture_to_args(data)
        result = run(changed_files=files, drift_ignores=ignores, policy=policy)

        exp = data["expected"]
        assert result.result == exp["result"]
        assert result.skip is True
        assert result.skip_reason == exp["skip_reason"]
        assert result.blocker_count == 0


# ─── unit: glob matcher ────────────────────────────────────────────────────────

class TestGlobMatcher:
    def test_exact_path(self):
        from drift_gate.utils.glob_matcher import match_glob
        assert match_glob("prisma/schema.prisma", "prisma/schema.prisma")
        assert not match_glob("prisma/schema.prisma", "prisma/other.prisma")

    def test_single_star(self):
        from drift_gate.utils.glob_matcher import match_glob
        assert match_glob("src/routes/users.ts", "src/routes/*")
        assert not match_glob("src/routes/v1/users.ts", "src/routes/*")

    def test_double_star_dir(self):
        from drift_gate.utils.glob_matcher import match_glob
        assert match_glob("db/migrations/0001.sql", "db/migrations/**")
        assert match_glob("db/migrations/v2/0001.sql", "db/migrations/**")

    def test_double_star_anywhere(self):
        from drift_gate.utils.glob_matcher import match_glob
        assert match_glob("src/auth/middleware.ts", "**/auth/**")
        assert match_glob("app/auth/rbac.py", "**/auth/**")

    def test_dot_extension_glob(self):
        from drift_gate.utils.glob_matcher import match_glob
        assert match_glob("utils/helper.test.ts", "**/*.test.*")
        assert not match_glob("utils/helper.ts", "**/*.test.*")


# ─── unit: classification ──────────────────────────────────────────────────────

class TestClassifier:
    def test_api_surface(self):
        from drift_gate.core.classification.classifier import get_file_change_types
        assert "api-surface" in get_file_change_types("src/routes/users.ts")
        assert "api-surface" in get_file_change_types("openapi/spec.yaml")

    def test_db_schema(self):
        from drift_gate.core.classification.classifier import get_file_change_types
        assert "db-schema" in get_file_change_types("db/migrations/001.sql")
        assert "db-schema" in get_file_change_types("prisma/schema.prisma")

    def test_env_config_dotenv_variants(self):
        from drift_gate.core.classification.classifier import get_file_change_types
        assert "env-config" in get_file_change_types(".env.development")
        assert "env-config" in get_file_change_types(".env.test")

    def test_docs_only_classification(self):
        from drift_gate.core.classification.classifier import classify_change_types
        files = [
            ChangedFile(path="docs/spec.md", status="modified"),
            ChangedFile(path="README.md", status="modified"),
        ]
        assert classify_change_types(files) == ["docs-only"]

    def test_mixed_not_docs_only(self):
        from drift_gate.core.classification.classifier import classify_change_types
        files = [
            ChangedFile(path="docs/spec.md", status="modified"),
            ChangedFile(path="src/routes/users.ts", status="modified"),
        ]
        result = classify_change_types(files)
        assert "docs-only" not in result
        assert "api-surface" in result


# ─── unit: drift-ignore policy ────────────────────────────────────────────────

class TestDriftIgnorePolicy:
    def _make_policy(self, severity: str) -> Policy:
        return Policy.from_dict({
            "rules": [{
                "id": "test-rule",
                "when": {"any_changed": ["src/routes/**"]},
                "require": {"groups": [
                    {"name": "API 계약 문서", "any_changed": ["docs/spec.md"]}
                ]},
                "severity": severity,
                "message": "test",
            }],
            "gate": {"fail_on_blocker": True, "fail_on_major_count": 2},
        })

    def test_blocker_with_reason_skipped(self):
        policy = self._make_policy("blocker")
        files = [ChangedFile(path="src/routes/users.ts", status="modified")]
        ignores = [DriftIgnoreDirective(rule_id="test-rule", reason="internal refactor")]
        result = run(changed_files=files, drift_ignores=ignores, policy=policy)

        assert result.violations == []
        assert len(result.skipped_rules) == 1
        assert result.skipped_rules[0].rule_id == "test-rule"
        assert result.rejected_ignores == []

    def test_blocker_without_reason_rejected(self):
        policy = self._make_policy("blocker")
        files = [ChangedFile(path="src/routes/users.ts", status="modified")]
        ignores = [DriftIgnoreDirective(rule_id="test-rule", reason=None)]
        result = run(changed_files=files, drift_ignores=ignores, policy=policy)

        assert len(result.violations) == 1
        assert len(result.rejected_ignores) == 1
        assert result.rejected_ignores[0].rule_id == "test-rule"
        assert result.skipped_rules == []

    def test_minor_without_reason_skipped(self):
        policy = self._make_policy("minor")
        files = [ChangedFile(path="src/routes/users.ts", status="modified")]
        ignores = [DriftIgnoreDirective(rule_id="test-rule", reason=None)]
        result = run(changed_files=files, drift_ignores=ignores, policy=policy)

        assert result.violations == []
        assert len(result.skipped_rules) == 1
        assert result.rejected_ignores == []

    def test_expired_ignore_rejected(self):
        policy = self._make_policy("blocker")
        files = [ChangedFile(path="src/routes/users.ts", status="modified")]
        ignores = [
            DriftIgnoreDirective(
                rule_id="test-rule",
                reason="temporary exception",
                expires="2000-01-01",
            )
        ]
        result = run(changed_files=files, drift_ignores=ignores, policy=policy)

        assert len(result.violations) == 1
        assert len(result.rejected_ignores) == 1
        assert "expired" in result.rejected_ignores[0].reason

    def test_future_expiring_ignore_skipped(self):
        policy = self._make_policy("blocker")
        files = [ChangedFile(path="src/routes/users.ts", status="modified")]
        ignores = [
            DriftIgnoreDirective(
                rule_id="test-rule",
                reason="temporary exception",
                expires="2999-01-01",
            )
        ]
        result = run(changed_files=files, drift_ignores=ignores, policy=policy)

        assert result.violations == []
        assert len(result.skipped_rules) == 1
        assert result.rejected_ignores == []

    def test_parse_drift_ignore_expires(self):
        from drift_gate.adapters.github.client import parse_drift_ignores

        ignores = parse_drift_ignores(
            "drift-ignore: test-rule\n"
            "reason: temporary exception\n"
            "expires: 2999-01-01\n"
            "approved-by: @team/api\n"
        )

        assert ignores[0].rule_id == "test-rule"
        assert ignores[0].reason == "temporary exception"
        assert ignores[0].expires == "2999-01-01"
        assert ignores[0].approved_by == "@team/api"

    def test_rule_can_disallow_ignore(self):
        policy = Policy.from_dict({
            "rules": [{
                "id": "test-rule",
                "when": {"any_changed": ["src/routes/**"]},
                "require": {"groups": [
                    {"name": "API docs", "any_changed": ["docs/spec.md"]},
                ]},
                "severity": "blocker",
                "allow_ignore": False,
            }],
        })
        files = [ChangedFile(path="src/routes/users.ts", status="modified")]
        ignores = [DriftIgnoreDirective(rule_id="test-rule", reason="temporary")]

        result = run(changed_files=files, drift_ignores=ignores, policy=policy)

        assert len(result.violations) == 1
        assert result.rejected_ignores[0].reason == "this rule does not allow drift-ignore"
        assert result.ignore_audit[0].action == "rejected"

    def test_suppression_requires_codeowners_approval(self):
        policy = Policy.from_dict({
            "rules": [{
                "id": "test-rule",
                "when": {"any_changed": ["src/routes/**"]},
                "require": {"groups": [
                    {"name": "API docs", "any_changed": ["docs/spec.md"]},
                ]},
                "severity": "blocker",
            }],
            "suppression": {"require_codeowners_approval": True},
        })
        files = [ChangedFile(path="src/routes/users.ts", status="modified")]
        ignores = [DriftIgnoreDirective(rule_id="test-rule", reason="temporary")]

        result = run(changed_files=files, drift_ignores=ignores, policy=policy)

        assert len(result.violations) == 1
        assert result.rejected_ignores[0].reason == "CODEOWNERS approval is required"

        approved = [
            DriftIgnoreDirective(
                rule_id="test-rule",
                reason="temporary",
                approved_by="@team/api",
            )
        ]
        approved_result = run(changed_files=files, drift_ignores=approved, policy=policy)
        assert approved_result.violations == []
        assert approved_result.ignore_audit[0].approved_by == "@team/api"

    def test_suppression_allowed_rules(self):
        policy = Policy.from_dict({
            "rules": [{
                "id": "test-rule",
                "when": {"any_changed": ["src/routes/**"]},
                "require": {"groups": [
                    {"name": "API docs", "any_changed": ["docs/spec.md"]},
                ]},
                "severity": "blocker",
            }],
            "suppression": {"allowed_rules": ["other-rule"]},
        })
        files = [ChangedFile(path="src/routes/users.ts", status="modified")]
        ignores = [DriftIgnoreDirective(rule_id="test-rule", reason="temporary")]

        result = run(changed_files=files, drift_ignores=ignores, policy=policy)

        assert len(result.violations) == 1
        assert result.rejected_ignores[0].reason == "rule is not listed in suppression.allowed_rules"


class TestCrossFileRelations:
    def test_optional_group_required_when_relation_triggers(self):
        policy = Policy.from_dict({
            "rules": [{
                "id": "openapi-sdk-release-sync",
                "when": {"any_changed": ["openapi/**"]},
                "require": {
                    "groups": [
                        {
                            "name": "API docs",
                            "any_changed": ["docs/api/**"],
                            "required": False,
                        },
                        {
                            "name": "SDK contract",
                            "any_changed": ["sdk/**"],
                            "required": False,
                        },
                        {
                            "name": "Release notes",
                            "all_changed": ["CHANGELOG.md"],
                            "required": False,
                        },
                    ],
                    "cross_file": [{
                        "name": "openapi-sdk-release",
                        "when_any_changed": ["openapi/**"],
                        "require_groups": ["SDK contract", "Release notes"],
                    }],
                },
                "severity": "major",
            }],
        })
        files = [
            ChangedFile(path="openapi/spec.yaml", status="modified"),
            ChangedFile(path="sdk/client.ts", status="modified"),
        ]

        result = run(changed_files=files, policy=policy)

        assert result.result == "warn"
        assert len(result.violations) == 1
        violation = result.violations[0]
        assert violation.cross_file_relations == ["openapi-sdk-release"]
        assert [g.name for g in violation.unsatisfied_groups] == [
            "openapi-sdk-release: Release notes"
        ]

    def test_optional_group_does_not_fail_without_relation_trigger(self):
        policy = Policy.from_dict({
            "rules": [{
                "id": "route-doc-sync",
                "when": {"any_changed": ["src/routes/**"]},
                "require": {
                    "groups": [
                        {"name": "API docs", "any_changed": ["docs/api/**"]},
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
        files = [
            ChangedFile(path="src/routes/users.py", status="modified"),
            ChangedFile(path="docs/api/users.md", status="modified"),
        ]

        result = run(changed_files=files, policy=policy)

        assert result.result == "pass"
        assert result.violations == []


# ─── unit: policy loader ───────────────────────────────────────────────────────

class TestPolicyLoader:
    def test_load_valid(self):
        import yaml
        from drift_gate.adapters.policy_loader import load_policy
        data = {
            "rules": [{
                "id": "test",
                "when": {"any_changed": ["src/**"]},
                "require": {"groups": [{"name": "docs", "any_changed": ["docs/**"]}]},
                "severity": "minor",
            }]
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", delete=False, encoding="utf-8"
        ) as f:
            yaml.dump(data, f, allow_unicode=True)
            path = f.name
        try:
            policy = load_policy(path)
            assert len(policy.rules) == 1
            assert policy.rules[0].id == "test"
        finally:
            os.unlink(path)

    def test_missing_require_groups(self):
        import yaml
        from drift_gate.adapters.policy_loader import load_policy
        from drift_gate.core.policy.loader import PolicyLoadError
        data = {
            "rules": [{
                "id": "bad",
                "when": {"any_changed": ["src/**"]},
                "require": {},
                "severity": "minor",
            }]
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yml", delete=False, encoding="utf-8"
        ) as f:
            yaml.dump(data, f, allow_unicode=True)
            path = f.name
        try:
            with pytest.raises(PolicyLoadError, match="require.groups"):
                load_policy(path)
        finally:
            os.unlink(path)

    def test_file_not_found(self):
        from drift_gate.adapters.policy_loader import load_policy
        with pytest.raises(FileNotFoundError):
            load_policy("/nonexistent/.drift-gate.yml")


# ─── unit: reporters ───────────────────────────────────────────────────────────

class TestReporters:
    def _make_result(self, fixture_name: str):
        data = load_fixture(fixture_name)
        files, ignores, policy = fixture_to_args(data)
        return run(changed_files=files, drift_ignores=ignores, policy=policy)

    def test_markdown_has_marker(self):
        from drift_gate.reporters.markdown import MarkdownReporter
        result = self._make_result("pr_api_change.json")
        md = MarkdownReporter().render(result)
        assert "<!-- drift-gate-v1 -->" in md
        assert "BLOCKER" in md
        assert "Triggered" in md
        assert "Missing docs/contracts" in md
        assert "Matched policy pattern" in md
        assert "Suggested fix" in md
        assert "src/routes/users.ts" in md
        assert "docs/spec.md" in md

    def test_markdown_explain_mode(self):
        from drift_gate.reporters.markdown import MarkdownReporter
        result = self._make_result("pr_api_change.json")
        md = MarkdownReporter().render(result, explain=True)

        assert "Explain evaluation" in md
        assert "Rule decisions" in md
        assert "api-contract-sync" in md
        assert "intensity" in md

    def test_json_schema(self):
        from drift_gate.reporters.json_reporter import JsonReporter
        result = self._make_result("pr_api_change.json")
        d = JsonReporter().render(result)

        assert "summary" in d
        assert "gate_decision" in d["summary"]
        assert "violations" in d
        assert "rejected_ignores" in d
        assert "skipped_rules" in d

        if d["violations"]:
            v = d["violations"][0]
            assert "change_type" in v   # singular
            assert "change_types" in v  # array
            assert "checklist" in v
            assert "confidence" in v
            assert "trigger_patterns" in v
            assert "blast_radius" in v

    def test_html_report_contains_pr_review_sections(self):
        from drift_gate.reporters.html import HtmlReporter
        result = self._make_result("pr_api_change.json")
        html = HtmlReporter().render(result)

        assert "<!doctype html>" in html
        assert "Drift Gate Report" in html
        assert "api-contract-sync" in html
        assert "Trigger files" in html
        assert "Matched patterns" in html
        assert "Violation Navigation" in html
        assert "Missing docs" in html
        assert "Diff Snippet" in html
        assert "Raw JSON" in html
        assert "Review Walkthrough" in html
        assert "Blast radius" in html
        assert "Rule Pass/Fail" in html
        assert "Policy Source" in html

    def test_html_report_renders_policy_source(self):
        from drift_gate.reporters.html import HtmlReporter
        result = self._make_result("pr_api_change.json")
        html = HtmlReporter().render(result, policy_source="rules:\n  - id: api-contract-sync\n")

        assert "Policy Source" in html
        assert "api-contract-sync" in html

    def test_html_report_renders_semantic_evidence(self):
        from drift_gate.reporters.html import HtmlReporter
        from drift_gate.core.models.changed_file import ChangedFile
        from drift_gate.core.models.policy import Gate
        from drift_gate.core.models.result import EvaluationResult, Violation, UnsatisfiedGroup

        result = EvaluationResult(
            change_types=["api-surface"],
            violations=[
                Violation(
                    rule_id="api-contract-sync",
                    severity="BLOCKER",
                    confidence="high",
                    change_types=["api-surface"],
                    change_type="api-surface",
                    message="API changed",
                    trigger_files=[
                        ChangedFile(
                            path="src/routes/users.ts",
                            status="modified",
                            semantic_signals=["route-contract-change"],
                            semantic_evidence=["TS/JS route handler changed"],
                        )
                    ],
                    unsatisfied_groups=[
                        UnsatisfiedGroup(
                            name="API docs",
                            required=["docs/api/**"],
                            type="any_changed",
                        )
                    ],
                    checklist=[],
                )
            ],
            skipped_rules=[],
            rejected_ignores=[],
            gate=Gate(),
        )
        html = HtmlReporter().render(result)

        assert "Semantic Evidence" in html
        assert "route-contract-change" in html
        assert "TS/JS route handler changed" in html

    def test_markdown_report_contains_anchor_group_status_and_raw_evidence(self):
        from drift_gate.reporters.markdown import MarkdownReporter
        result = self._make_result("pr_api_change.json")
        md = MarkdownReporter().render(result, explain=True)

        assert '<a id="rule-api-contract-sync"></a>' in md
        assert "Docs group status" in md
        assert "Raw evidence" in md
        assert "[`api-contract-sync`](#rule-api-contract-sync)" in md

    def test_markdown_no_policy(self):
        from drift_gate.reporters.markdown import MarkdownReporter
        from drift_gate.core.models.policy import Gate
        from drift_gate.core.models.result import EvaluationResult
        result = EvaluationResult(
            change_types=[], violations=[], skipped_rules=[],
            rejected_ignores=[], gate=Gate(), no_policy=True,
        )
        md = MarkdownReporter().render(result)
        assert ".drift-gate.yml" in md

    def test_html_escapes_user_content(self):
        """HTML reporter must escape user-controlled content (XSS prevention).

        The reporter includes one legitimate <script> tag for the copyText helper.
        Any additional <script> tags indicate un-escaped user content.
        """
        from drift_gate.reporters.html import HtmlReporter
        from drift_gate.core.models.changed_file import ChangedFile
        from drift_gate.core.models.policy import Gate
        from drift_gate.core.models.result import EvaluationResult, Violation, UnsatisfiedGroup

        xss_payload = "<script>alert('xss')</script>"
        result = EvaluationResult(
            change_types=["api-surface"],
            violations=[
                Violation(
                    rule_id="api-contract-sync",
                    severity="BLOCKER",
                    confidence="high",
                    change_types=["api-surface"],
                    change_type="api-surface",
                    message=xss_payload,
                    trigger_files=[ChangedFile(path="src/routes/xss.ts", status="modified")],
                    unsatisfied_groups=[
                        UnsatisfiedGroup(name=xss_payload, required=["docs/api/**"], type="any_changed")
                    ],
                    checklist=[xss_payload],
                )
            ],
            skipped_rules=[],
            rejected_ignores=[],
            gate=Gate(),
        )
        html_out = HtmlReporter().render(result)
        # Only the built-in copyText <script> tag should remain; user content must be escaped
        assert html_out.count("<script>") == 1, "User-injected <script> must be escaped"
        assert "&lt;script&gt;" in html_out

    def test_html_enrichment_metrics_panel(self):
        """HTML reporter renders token efficiency panel when enrichment_metrics present."""
        from drift_gate.reporters.html import HtmlReporter
        from drift_gate.core.models.policy import Gate
        from drift_gate.core.models.result import EvaluationResult, EnrichmentMetrics

        result = EvaluationResult(
            change_types=[], violations=[], skipped_rules=[],
            rejected_ignores=[], gate=Gate(),
            enrichment_metrics=EnrichmentMetrics(
                model="claude-opus-4-6",
                input_tokens=820,
                output_tokens=150,
                cache_creation_input_tokens=210,
                cache_read_input_tokens=610,
            ),
        )
        html_out = HtmlReporter().render(result)
        assert "Token Efficiency" in html_out
        assert "820" in html_out


# ─── 대용량 PR (4-4) ──────────────────────────────────────────────────────────

class TestLargePR:
    """Verify engine correctness and no crash on 100+ changed files."""

    def test_large_pr_fixture_loads_and_evaluates(self):
        data = json.loads((FIXTURES / "pr_large_100_files.json").read_text(encoding="utf-8"))
        files = [ChangedFile.from_dict(f) for f in data["changed_files"]]
        assert len(files) >= 99

        from drift_gate.core.models.policy import Policy
        from drift_gate.core.models.result import DriftIgnoreDirective
        ignores = [DriftIgnoreDirective.from_dict(d) for d in data.get("drift_ignores", [])]
        policy = Policy.from_dict(data["policy"])

        result = run(changed_files=files, drift_ignores=ignores, policy=policy)
        exp = data["expected"]
        assert result.result == exp["result"]
        assert result.blocker_count == exp["blocker_count"]
        assert sorted(v.rule_id for v in result.violations) == sorted(exp["violation_rule_ids"])

    def test_large_pr_scan_metrics_populated(self):
        data = json.loads((FIXTURES / "pr_large_100_files.json").read_text(encoding="utf-8"))
        files = [ChangedFile.from_dict(f) for f in data["changed_files"]]
        from drift_gate.core.models.policy import Policy
        from drift_gate.core.models.result import DriftIgnoreDirective
        policy = Policy.from_dict(data["policy"])
        result = run(changed_files=files, drift_ignores=[], policy=policy)
        assert result.scan_metrics.scanned_files >= 99

    def test_large_pr_no_crash_on_empty_patches(self):
        """All 99 files have empty patch — engine must not raise."""
        data = json.loads((FIXTURES / "pr_large_100_files.json").read_text(encoding="utf-8"))
        files = [ChangedFile.from_dict(f) for f in data["changed_files"]]
        from drift_gate.core.models.policy import Policy
        policy = Policy.from_dict(data["policy"])
        result = run(changed_files=files, drift_ignores=[], policy=policy)
        assert result.result in ("pass", "warn", "fail")
