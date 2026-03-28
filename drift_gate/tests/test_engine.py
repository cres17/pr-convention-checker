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


# ─── unit: policy loader ───────────────────────────────────────────────────────

class TestPolicyLoader:
    def test_load_valid(self):
        import yaml
        from drift_gate.core.policy.loader import load_policy
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
        from drift_gate.core.policy.loader import load_policy, PolicyLoadError
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
        from drift_gate.core.policy.loader import load_policy
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
