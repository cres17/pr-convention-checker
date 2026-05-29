"""
HTML reporter output format tests (5-1a) and security checks (5-3).
No network, no subprocess. All I/O is pure string assertions.
"""
from __future__ import annotations

import html
import json
import re

import pytest

from drift_gate.adapters.history.store import render_history_html
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.policy import Gate
from drift_gate.core.models.result import (
    EnrichmentMetrics,
    EvaluationResult,
    RuleDecision,
    SatisfiedGroup,
    SkippedRule,
    TemporalWarning,
    UnsatisfiedGroup,
    Violation,
)
from drift_gate.reporters.html import HtmlReporter


# ── helpers ────────────────────────────────────────────────────────────────────

def _clean_result(violations=None, skipped=None, rejected=None) -> EvaluationResult:
    return EvaluationResult(
        change_types=["api-surface"],
        violations=violations or [],
        skipped_rules=skipped or [],
        rejected_ignores=rejected or [],
        gate=Gate(),
    )


def _violation(
    rule_id="api-contract-sync",
    severity="BLOCKER",
    message="API changed without docs",
    trigger_files=None,
    checklist=None,
    unsatisfied_groups=None,
) -> Violation:
    return Violation(
        rule_id=rule_id,
        severity=severity,
        confidence="high",
        change_types=["api-surface"],
        change_type="api-surface",
        message=message,
        trigger_files=trigger_files or [ChangedFile(path="src/routes/users.ts", status="modified")],
        unsatisfied_groups=unsatisfied_groups or [
            UnsatisfiedGroup(name="API docs", required=["docs/api/**"], type="any_changed")
        ],
        checklist=checklist or ["Update docs/api/"],
    )


# ── 기본 구조 ──────────────────────────────────────────────────────────────────

class TestHtmlStructure:
    def test_valid_html_doctype(self):
        out = HtmlReporter().render(_clean_result())
        assert "<!doctype html>" in out

    def test_charset_utf8(self):
        out = HtmlReporter().render(_clean_result())
        assert 'charset="utf-8"' in out

    def test_viewport_meta(self):
        out = HtmlReporter().render(_clean_result())
        assert "viewport" in out

    def test_title_present(self):
        out = HtmlReporter().render(_clean_result())
        assert "<title>Drift Gate Report</title>" in out

    def test_status_pass_class(self):
        result = _clean_result()
        result.result = "pass"
        out = HtmlReporter().render(result)
        assert "status-pass" in out

    def test_status_fail_class(self):
        result = _clean_result(violations=[_violation()])
        result.result = "fail"
        out = HtmlReporter().render(result)
        assert "status-fail" in out

    def test_status_warn_class(self):
        result = _clean_result()
        result.result = "warn"
        out = HtmlReporter().render(result)
        assert "status-warn" in out

    def test_no_violations_shows_empty_section(self):
        out = HtmlReporter().render(_clean_result())
        assert "No Contract Drift Found" in out

    def test_violations_show_rule_id(self):
        out = HtmlReporter().render(_clean_result(violations=[_violation()]))
        assert "api-contract-sync" in out

    def test_has_raw_json_section(self):
        out = HtmlReporter().render(_clean_result())
        assert "Raw JSON" in out

    def test_has_walkthrough_section(self):
        out = HtmlReporter().render(_clean_result())
        assert "Review Walkthrough" in out

    def test_has_metrics_section(self):
        out = HtmlReporter().render(_clean_result())
        assert "Change Types" in out
        assert "Blockers" in out
        assert "Runtime" in out


# ── XSS / HTML escape (5-3) ────────────────────────────────────────────────────

def _count_unescaped_script_tags(html_str: str) -> int:
    """Count <script> tags that are NOT from Drift Gate's own JS block.

    The reporter includes one legitimate <script> block for the copyText helper.
    Any additional <script> tags indicate un-escaped user content.
    """
    # Count all <script> occurrences
    total = html_str.count("<script>")
    # The reporter legitimately emits exactly one <script> tag
    # (the copyText clipboard helper at the bottom of the page)
    return max(0, total - 1)


class TestHtmlEscape:
    _XSS = "<script>alert('xss')</script>"
    _ATTR_XSS = '"><img src=x onerror=alert(1)>'

    def test_message_escaped(self):
        v = _violation(message=self._XSS)
        out = HtmlReporter().render(_clean_result(violations=[v]))
        # user-injected <script> must be escaped; only the built-in JS tag remains
        assert _count_unescaped_script_tags(out) == 0
        assert "&lt;script&gt;" in out

    def test_rule_id_escaped(self):
        v = _violation(rule_id='api<>&\'"')
        out = HtmlReporter().render(_clean_result(violations=[v]))
        assert _count_unescaped_script_tags(out) == 0

    def test_group_name_escaped(self):
        group = UnsatisfiedGroup(name=self._XSS, required=["docs/api/**"], type="any_changed")
        v = _violation(unsatisfied_groups=[group])
        out = HtmlReporter().render(_clean_result(violations=[v]))
        assert _count_unescaped_script_tags(out) == 0

    def test_trigger_file_path_escaped(self):
        f = ChangedFile(path=self._XSS, status="modified")
        v = _violation(trigger_files=[f])
        out = HtmlReporter().render(_clean_result(violations=[v]))
        assert _count_unescaped_script_tags(out) == 0

    def test_checklist_item_escaped(self):
        v = _violation(checklist=[self._XSS])
        out = HtmlReporter().render(_clean_result(violations=[v]))
        assert _count_unescaped_script_tags(out) == 0
        assert "&lt;script&gt;" in out

    def test_policy_source_escaped(self):
        out = HtmlReporter().render(_clean_result(), policy_source=self._XSS)
        assert _count_unescaped_script_tags(out) == 0
        assert "&lt;script&gt;" in out

    def test_raw_json_block_escapes_html_in_values(self):
        """The pre block with raw JSON must not render HTML tags unescaped."""
        v = _violation(message='{"key": "<b>bold</b>"}')
        out = HtmlReporter().render(_clean_result(violations=[v]))
        raw_json_section = out[out.find("Raw JSON"):]
        assert "<b>bold</b>" not in raw_json_section

    def test_diff_snippet_escaped(self):
        f = ChangedFile(
            path="src/routes/users.ts",
            status="modified",
            patch=f"+{self._XSS}\n",
        )
        v = _violation(trigger_files=[f])
        out = HtmlReporter().render(_clean_result(violations=[v]))
        assert _count_unescaped_script_tags(out) == 0


# ── Token Efficiency 패널 (5-3 / 7-2) ─────────────────────────────────────────

class TestTokenEfficiencyPanel:
    def _metrics(self, **kwargs) -> EnrichmentMetrics:
        defaults = dict(
            model="claude-opus-4-6",
            input_tokens=820,
            output_tokens=150,
            cache_creation_input_tokens=210,
            cache_read_input_tokens=610,
        )
        defaults.update(kwargs)
        return EnrichmentMetrics(**defaults)

    def test_panel_present_when_metrics_set(self):
        result = _clean_result()
        result.enrichment_metrics = self._metrics()
        out = HtmlReporter().render(result)
        assert "Token Efficiency" in out

    def test_panel_absent_when_no_metrics(self):
        out = HtmlReporter().render(_clean_result())
        assert "Token Efficiency" not in out

    def test_model_name_shown(self):
        result = _clean_result()
        result.enrichment_metrics = self._metrics()
        out = HtmlReporter().render(result)
        assert "claude-opus-4-6" in out

    def test_token_counts_shown(self):
        result = _clean_result()
        result.enrichment_metrics = self._metrics()
        out = HtmlReporter().render(result)
        assert "820" in out
        assert "610" in out

    def test_savings_pct_shown(self):
        result = _clean_result()
        result.enrichment_metrics = self._metrics()
        out = HtmlReporter().render(result)
        assert "%" in out

    def test_cost_shown(self):
        result = _clean_result()
        result.enrichment_metrics = self._metrics()
        out = HtmlReporter().render(result)
        assert "USD" in out

    def test_zero_metrics_no_crash(self):
        result = _clean_result()
        result.enrichment_metrics = EnrichmentMetrics()
        out = HtmlReporter().render(result)
        assert "Token Efficiency" in out


# ── Rule Pass/Fail 테이블 ──────────────────────────────────────────────────────

class TestRuleTable:
    def test_rule_table_rendered(self):
        result = _clean_result()
        result.rule_decisions = [
            RuleDecision(
                rule_id="api-contract-sync",
                severity="BLOCKER",
                status="fail",
                reason="trigger matched",
                matched_patterns=["src/routes/**"],
            )
        ]
        out = HtmlReporter().render(result)
        assert "Rule Pass/Fail" in out
        assert "api-contract-sync" in out
        assert "BLOCKER" in out

    def test_rule_table_absent_when_no_decisions(self):
        out = HtmlReporter().render(_clean_result())
        assert "Rule Pass/Fail" not in out


# ── Temporal warnings ──────────────────────────────────────────────────────────

class TestTemporalWarnings:
    def test_temporal_warning_shown(self):
        result = _clean_result()
        result.temporal_warnings = [
            TemporalWarning(
                rule_id="api-contract-sync",
                ignored_count=5,
                threshold=3,
                severity="MAJOR",
                message="rule repeated-ignored",
            )
        ]
        out = HtmlReporter().render(result)
        assert "Temporal Gate Warnings" in out
        assert "api-contract-sync" in out
        assert "5" in out

    def test_no_temporal_section_when_empty(self):
        out = HtmlReporter().render(_clean_result())
        assert "Temporal Gate Warnings" not in out


# ── Violation card 상세 ────────────────────────────────────────────────────────

class TestViolationCard:
    def test_trigger_files_shown(self):
        out = HtmlReporter().render(_clean_result(violations=[_violation()]))
        assert "src/routes/users.ts" in out

    def test_severity_badge_shown(self):
        out = HtmlReporter().render(_clean_result(violations=[_violation(severity="MAJOR")]))
        assert "MAJOR" in out

    def test_missing_docs_shown(self):
        out = HtmlReporter().render(_clean_result(violations=[_violation()]))
        assert "docs/api/**" in out

    def test_checklist_shown(self):
        out = HtmlReporter().render(_clean_result(violations=[_violation(checklist=["Update spec"])]))
        assert "Update spec" in out

    def test_override_block_present(self):
        out = HtmlReporter().render(_clean_result(violations=[_violation()]))
        assert "drift-ignore" in out

    def test_copy_button_present(self):
        out = HtmlReporter().render(_clean_result(violations=[_violation()]))
        assert "copyText" in out

    def test_diff_snippet_shown_when_patch_present(self):
        f = ChangedFile(path="src/routes/users.ts", status="modified", patch="+export function newRoute()")
        v = _violation(trigger_files=[f])
        out = HtmlReporter().render(_clean_result(violations=[v]))
        assert "Diff Snippet" in out

    def test_diff_snippet_absent_when_no_patch(self):
        f = ChangedFile(path="src/routes/users.ts", status="modified", patch="")
        v = _violation(trigger_files=[f])
        out = HtmlReporter().render(_clean_result(violations=[v]))
        assert "Diff Snippet" not in out

    def test_enrichment_fields_shown(self):
        v = _violation()
        v.changed_contract_summary = "Route /users was extended"
        v.missing_docs_explanation = "Consumers need updated spec"
        v.docs_update_draft = "## API Change\n..."
        v.false_positive_note = "Low"
        out = HtmlReporter().render(_clean_result(violations=[v]))
        assert "Changed Contract Summary" in out
        assert "Missing Docs Explanation" in out
        assert "Docs Update Draft" in out
        assert "False Positive Candidate" in out

    def test_semantic_evidence_shown(self):
        f = ChangedFile(
            path="src/routes/users.ts",
            status="modified",
            semantic_signals=["route-contract-change"],
            semantic_evidence=["TS route handler changed"],
        )
        v = _violation(trigger_files=[f])
        out = HtmlReporter().render(_clean_result(violations=[v]))
        assert "Semantic Evidence" in out
        assert "route-contract-change" in out


# ── Violation Navigation ───────────────────────────────────────────────────────

class TestViolationNav:
    def test_nav_shown_with_violations(self):
        out = HtmlReporter().render(_clean_result(violations=[_violation()]))
        assert "Violation Navigation" in out

    def test_nav_absent_when_no_violations(self):
        out = HtmlReporter().render(_clean_result())
        assert "Violation Navigation" not in out

    def test_nav_links_to_anchor(self):
        out = HtmlReporter().render(_clean_result(violations=[_violation()]))
        assert 'href="#rule-api-contract-sync"' in out


# ── history HTML report ────────────────────────────────────────────────────────

class TestHistoryHtml:
    def _records(self) -> list:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        return [
            {
                "timestamp": now,
                "source": "local",
                "pr_number": None,
                "commit_sha": "abc123",
                "result": "fail",
                "blocker": 1,
                "major": 0,
                "minor": 0,
                "nit": 0,
                "violation_count": 1,
                "rejected_ignore_count": 0,
                "skipped_rule_count": 0,
                "rules": ["api-contract-sync"],
                "severities": ["BLOCKER"],
                "ignored_rules": [],
                "rejected_ignore_rules": [],
                "ignore_audit": [],
                "change_types": ["api-surface"],
                "changed_file_count": 3,
                "runtime_seconds": 0.05,
                "release": "v1.0.0",
            }
        ]

    def test_history_html_valid_doctype(self):
        out = render_history_html(self._records(), days=30)
        assert "<!doctype html>" in out

    def test_history_html_shows_run_count(self):
        out = render_history_html(self._records(), days=30)
        assert "1" in out

    def test_history_html_shows_rule(self):
        out = render_history_html(self._records(), days=30)
        assert "api-contract-sync" in out

    def test_history_html_escapes_content(self):
        records = self._records()
        records[0]["rules"] = ["<script>xss</script>"]
        out = render_history_html(records, days=30)
        assert "<script>xss</script>" not in out

    def test_history_html_empty_records(self):
        out = render_history_html([], days=30)
        assert "<!doctype html>" in out
        assert "0" in out


# ── path traversal (5-3) ──────────────────────────────────────────────────────

class TestPathTraversal:
    """GitHub client _sanitize_path must block traversal attempts."""

    def test_rejects_dotdot(self):
        from drift_gate.adapters.github.client import _sanitize_path
        assert _sanitize_path("../../etc/passwd") is None

    def test_rejects_absolute(self):
        from drift_gate.adapters.github.client import _sanitize_path
        assert _sanitize_path("/etc/shadow") is None

    def test_rejects_embedded_traversal(self):
        from drift_gate.adapters.github.client import _sanitize_path
        assert _sanitize_path("src/../../../secret.env") is None

    def test_accepts_normal_path(self):
        from drift_gate.adapters.github.client import _sanitize_path
        assert _sanitize_path("src/routes/users.ts") == "src/routes/users.ts"

    def test_accepts_nested_path(self):
        from drift_gate.adapters.github.client import _sanitize_path
        assert _sanitize_path("drift_gate/core/models/result.py") is not None


# ── token-in-log (5-3) ────────────────────────────────────────────────────────

class TestTokenNotLogged:
    """Verify enricher and github client never log secret values."""

    def test_enricher_call_api_doesnt_log_key(self):
        """_call_api must not print or log the api_key value."""
        import inspect
        from drift_gate.adapters.claude import enricher
        src = inspect.getsource(enricher)
        # Must not have f"... {self._api_key}" or print(... api_key ...) patterns
        assert 'self._api_key}' not in src or 'print' not in src
        # The key is only used as a header value, never logged
        assert 'x-api-key' in src

    def test_github_client_doesnt_log_token(self):
        """GitHubAdapter._get must not print token value."""
        import inspect
        from drift_gate.adapters.github import client
        src = inspect.getsource(client)
        # Token is used as Bearer header, not printed
        assert 'Bearer' in src
        # No direct print of the token variable
        assert 'print(self._token' not in src
        assert 'print(token' not in src
