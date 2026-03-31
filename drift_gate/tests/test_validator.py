"""
policy validator + 엣지 케이스 테스트.
"""
import os
import tempfile
import pytest
import yaml

from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.policy import Policy
from drift_gate.core.models.result import DriftIgnoreDirective
from drift_gate.core.engine import run
from drift_gate.core.policy.validator import validate, PolicyValidationError
from drift_gate.core.policy.loader import load_policy, PolicyLoadError


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
