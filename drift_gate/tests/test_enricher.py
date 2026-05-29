"""
Unit tests for ClaudeEnricher.
Covers: successful enrichment, API failure fallback, docs draft fallback,
prompt caching payload structure, and _SYSTEM_PROMPT separation.
All tests use monkeypatching — no real network calls.
"""
import json
import urllib.error
import urllib.request
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from drift_gate.adapters.claude.enricher import (
    ClaudeEnricher,
    _SYSTEM_PROMPT,
    _build_prompt,
    _fallback_draft,
)
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.policy import Gate, Policy
from drift_gate.core.models.result import (
    EnrichmentMetrics,
    EvaluationResult,
    MODEL_PRICING,
    ScanMetrics,
    UnsatisfiedGroup,
    Violation,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_violation(rule_id: str = "api-contract-sync") -> Violation:
    return Violation(
        rule_id=rule_id,
        severity="BLOCKER",
        confidence="high",
        change_types=["api-surface"],
        change_type="api-surface",
        message="API changed without docs",
        trigger_files=[ChangedFile(path="src/routes/users.ts", status="modified")],
        unsatisfied_groups=[
            UnsatisfiedGroup(
                name="API 계약 문서",
                required=["docs/spec.md"],
                type="any_changed",
            )
        ],
        checklist=["[ ] Update docs/spec.md"],
    )


def _make_result(violations=None) -> EvaluationResult:
    if violations is None:
        violations = [_make_violation()]
    return EvaluationResult(
        change_types=["api-surface"],
        violations=violations,
        skipped_rules=[],
        rejected_ignores=[],
        gate=Gate(),
        rule_decisions=[],
        ignore_audit=[],
        scan_metrics=ScanMetrics(scanned_files=1, skipped_ignored_files=0, evaluated_rules=1),
        result="fail",
    )


def _make_api_response(
    text: str,
    usage: dict | None = None,
) -> MagicMock:
    """Return a mock that mimics urllib.request.urlopen context manager."""
    if usage is None:
        usage = {
            "input_tokens": 820,
            "output_tokens": 150,
            "cache_creation_input_tokens": 210,
            "cache_read_input_tokens": 610,
        }
    resp_data = json.dumps({"content": [{"text": text}], "usage": usage}).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = resp_data
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ── fallback: API failure ─────────────────────────────────────────────────────

class TestEnrichFallback:
    def test_network_error_returns_original_result(self):
        enricher = ClaudeEnricher(api_key="test-key")
        result = _make_result()
        original_checklist = list(result.violations[0].checklist)

        with patch("urllib.request.urlopen", side_effect=OSError("network down")):
            enriched = enricher.enrich(result)

        assert enriched is result
        assert enriched.violations[0].checklist == original_checklist

    def test_http_401_returns_original_result(self):
        enricher = ClaudeEnricher(api_key="bad-key")
        result = _make_result()

        http_err = urllib.error.HTTPError(
            url="https://api.anthropic.com/v1/messages",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=BytesIO(b'{"error": {"message": "invalid key"}}'),
        )
        with patch("urllib.request.urlopen", side_effect=http_err):
            enriched = enricher.enrich(result)

        assert enriched is result

    def test_malformed_json_response_returns_original(self):
        enricher = ClaudeEnricher(api_key="test-key")
        result = _make_result()

        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not-json!!!"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            enriched = enricher.enrich(result)

        assert enriched is result

    def test_empty_violations_returns_immediately(self):
        enricher = ClaudeEnricher(api_key="test-key")
        result = _make_result(violations=[])

        with patch("urllib.request.urlopen") as mock_open:
            enriched = enricher.enrich(result)
            mock_open.assert_not_called()

        assert enriched is result


# ── successful enrichment ─────────────────────────────────────────────────────

class TestEnrichSuccess:
    def test_checklist_replaced_on_match(self):
        enricher = ClaudeEnricher(api_key="test-key")
        result = _make_result()

        response_text = (
            "### [BLOCKER] api-contract-sync\n"
            "왜 필요한가: API 계약 변경 시 문서가 동기화돼야 합니다.\n\n"
            "체크리스트:\n"
            "- [ ] docs/spec.md 업데이트\n"
            "- [ ] CHANGELOG.md 엔트리 추가\n\n"
            "Changed contract summary: GET /users 엔드포인트 변경\n"
            "Missing docs explanation: 스펙 문서가 누락됨\n"
            "Docs update draft: ## API 변경\n자세한 내용 작성\n"
            "False positive candidate: 낮음\n"
        )
        with patch("urllib.request.urlopen", return_value=_make_api_response(response_text)):
            enriched = enricher.enrich(result)

        v = enriched.violations[0]
        assert "docs/spec.md 업데이트" in v.checklist
        assert "CHANGELOG.md 엔트리 추가" in v.checklist
        assert v.changed_contract_summary == "GET /users 엔드포인트 변경"
        assert "스펙 문서가 누락됨" in v.missing_docs_explanation

    def test_no_section_match_keeps_original_checklist(self):
        enricher = ClaudeEnricher(api_key="test-key")
        result = _make_result()
        original_checklist = list(result.violations[0].checklist)

        # API returns content but no section for our rule_id
        response_text = "### [BLOCKER] some-other-rule\n체크리스트:\n- [ ] other item\n"
        with patch("urllib.request.urlopen", return_value=_make_api_response(response_text)):
            enriched = enricher.enrich(result)

        assert enriched.violations[0].checklist == original_checklist


# ── docs draft fallback ───────────────────────────────────────────────────────

class TestDocsDraftFallback:
    def test_fallback_draft_contains_trigger_path(self):
        v = _make_violation()
        draft = _fallback_draft(v)
        assert "src/routes/users.ts" in draft

    def test_fallback_draft_contains_group_name(self):
        v = _make_violation()
        draft = _fallback_draft(v)
        assert "API 계약 문서" in draft

    def test_fallback_draft_contains_required_file(self):
        v = _make_violation()
        draft = _fallback_draft(v)
        assert "docs/spec.md" in draft

    def test_generate_docs_draft_uses_fallback_on_api_failure(self):
        enricher = ClaudeEnricher(api_key="test-key")
        result = _make_result()

        with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
            drafts = enricher.generate_docs_draft(result)

        assert "api-contract-sync" in drafts
        assert "src/routes/users.ts" in drafts["api-contract-sync"]

    def test_generate_docs_draft_returns_empty_on_no_violations(self):
        enricher = ClaudeEnricher(api_key="test-key")
        result = _make_result(violations=[])

        with patch("urllib.request.urlopen") as mock_open:
            drafts = enricher.generate_docs_draft(result)
            mock_open.assert_not_called()

        assert drafts == {}


# ── prompt caching payload structure ─────────────────────────────────────────

class TestPromptCachingPayload:
    def _capture_payload(self, enricher: ClaudeEnricher, result: EvaluationResult) -> dict:
        captured = {}

        class FakeResp:
            def read(self):
                return json.dumps({"content": [{"text": "### [BLOCKER] api-contract-sync\n체크리스트:\n"}]}).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        original_request = urllib.request.Request

        def fake_urlopen(req):
            captured["payload"] = json.loads(req.data.decode())
            captured["headers"] = dict(req.headers)
            return FakeResp()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            enricher.enrich(result)

        return captured

    def test_system_field_present(self):
        enricher = ClaudeEnricher(api_key="key")
        result = _make_result()
        captured = self._capture_payload(enricher, result)
        assert "system" in captured.get("payload", {}), "payload must have 'system' field"

    def test_system_is_list_with_cache_control(self):
        enricher = ClaudeEnricher(api_key="key")
        result = _make_result()
        captured = self._capture_payload(enricher, result)
        system = captured["payload"]["system"]
        assert isinstance(system, list)
        assert system[0].get("cache_control") == {"type": "ephemeral"}

    def test_system_text_matches_system_prompt_constant(self):
        enricher = ClaudeEnricher(api_key="key")
        result = _make_result()
        captured = self._capture_payload(enricher, result)
        system_text = captured["payload"]["system"][0]["text"]
        assert system_text == _SYSTEM_PROMPT

    def test_user_message_does_not_repeat_system_instructions(self):
        enricher = ClaudeEnricher(api_key="key")
        result = _make_result()
        captured = self._capture_payload(enricher, result)
        user_content = captured["payload"]["messages"][0]["content"]
        assert "팀 계약 문서와 코드 변경의 정합성 점검 분析가" not in user_content
        assert "정책 위반 목록" in user_content

    def test_prompt_caching_beta_header_present(self):
        enricher = ClaudeEnricher(api_key="key")
        result = _make_result()
        captured = self._capture_payload(enricher, result)
        # Headers are stored title-cased by urllib
        headers_lower = {k.lower(): v for k, v in captured.get("headers", {}).items()}
        assert "anthropic-beta" in headers_lower
        assert "prompt-caching" in headers_lower["anthropic-beta"]

    def test_api_key_in_header(self):
        enricher = ClaudeEnricher(api_key="my-secret-key")
        result = _make_result()
        captured = self._capture_payload(enricher, result)
        headers_lower = {k.lower(): v for k, v in captured.get("headers", {}).items()}
        assert headers_lower.get("x-api-key") == "my-secret-key"


# ── _build_prompt (user message only) ────────────────────────────────────────

class TestBuildPrompt:
    def test_contains_violation_summary(self):
        prompt = _build_prompt("## 정책 위반 목록\n\n[BLOCKER] api-contract-sync")
        assert "정책 위반 목록" in prompt

    def test_does_not_contain_system_instructions(self):
        prompt = _build_prompt("violations here")
        assert "출력하세요" not in prompt
        assert "체크리스트:" not in prompt


# ── EnrichmentMetrics model ───────────────────────────────────────────────────

class TestEnrichmentMetrics:
    def test_estimated_uncached_input_tokens(self):
        m = EnrichmentMetrics(
            model="claude-opus-4-6",
            input_tokens=820,
            output_tokens=150,
            cache_creation_input_tokens=210,
            cache_read_input_tokens=610,
        )
        assert m.estimated_uncached_input_tokens == 820 + 610

    def test_saved_input_tokens_equals_cache_read(self):
        m = EnrichmentMetrics(
            model="claude-opus-4-6",
            input_tokens=820,
            cache_read_input_tokens=610,
        )
        assert m.saved_input_tokens == 610

    def test_estimated_savings_pct(self):
        m = EnrichmentMetrics(
            model="claude-opus-4-6",
            input_tokens=820,
            cache_read_input_tokens=610,
        )
        # savings = 610 * 0.9 / (820 + 610) * 100
        expected = round(610 * 0.9 / (820 + 610) * 100, 1)
        assert m.estimated_savings_pct == expected

    def test_estimated_savings_pct_zero_when_no_cache(self):
        m = EnrichmentMetrics(model="claude-opus-4-6", input_tokens=500)
        assert m.estimated_savings_pct == 0.0

    def test_estimated_savings_pct_zero_when_all_zero(self):
        m = EnrichmentMetrics()
        assert m.estimated_savings_pct == 0.0

    def test_estimated_cost_usd_uses_model_pricing(self):
        m = EnrichmentMetrics(
            model="claude-opus-4-6",
            input_tokens=1_000_000,
            output_tokens=0,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )
        cost = m.estimated_cost_usd()
        assert cost["input_usd"] == pytest.approx(15.0)
        assert cost["cache_read_usd"] == pytest.approx(0.0)

    def test_estimated_cost_usd_cache_read_cheaper_than_input(self):
        m = EnrichmentMetrics(
            model="claude-opus-4-6",
            input_tokens=0,
            cache_read_input_tokens=1_000_000,
        )
        cost = m.estimated_cost_usd()
        pricing = MODEL_PRICING["claude-opus-4-6"]
        assert cost["cache_read_usd"] == pytest.approx(pricing["cache_read"])
        assert cost["cache_read_usd"] < pricing["input"]

    def test_estimated_cost_unknown_model_uses_default(self):
        # Unknown model should not raise; uses fallback pricing
        m = EnrichmentMetrics(
            model="claude-unknown-future",
            input_tokens=1_000_000,
        )
        cost = m.estimated_cost_usd()
        assert cost["input_usd"] > 0

    def test_to_dict_contains_all_fields(self):
        m = EnrichmentMetrics(
            model="claude-opus-4-6",
            input_tokens=820,
            output_tokens=150,
            cache_creation_input_tokens=210,
            cache_read_input_tokens=610,
        )
        d = m.to_dict()
        for key in (
            "model", "input_tokens", "output_tokens",
            "cache_creation_input_tokens", "cache_read_input_tokens",
            "estimated_uncached_input_tokens", "saved_input_tokens",
            "estimated_savings_pct", "estimated_cost",
        ):
            assert key in d, f"missing key: {key}"

    def test_format_report_contains_key_fields(self):
        m = EnrichmentMetrics(
            model="claude-opus-4-6",
            input_tokens=820,
            output_tokens=150,
            cache_creation_input_tokens=210,
            cache_read_input_tokens=610,
        )
        report = m.format_report()
        assert "input_tokens: 820" in report
        assert "cache_read_input_tokens: 610" in report
        assert "estimated_savings:" in report


# ── usage parsing in enrich() ─────────────────────────────────────────────────

class TestEnrichUsageParsing:
    def _response_text(self) -> str:
        return (
            "### [BLOCKER] api-contract-sync\n"
            "체크리스트:\n"
            "- [ ] docs/spec.md 업데이트\n"
        )

    def test_enrich_stores_enrichment_metrics_on_success(self):
        enricher = ClaudeEnricher(api_key="test-key")
        result = _make_result()

        with patch("urllib.request.urlopen", return_value=_make_api_response(self._response_text())):
            enriched = enricher.enrich(result)

        assert enriched.enrichment_metrics is not None
        assert enriched.enrichment_metrics.input_tokens == 820
        assert enriched.enrichment_metrics.cache_read_input_tokens == 610
        assert enriched.enrichment_metrics.output_tokens == 150

    def test_enrich_metrics_model_matches_enricher_model(self):
        enricher = ClaudeEnricher(api_key="test-key", model="claude-sonnet-4-6")
        result = _make_result()

        with patch("urllib.request.urlopen", return_value=_make_api_response(self._response_text())):
            enriched = enricher.enrich(result)

        assert enriched.enrichment_metrics is not None
        assert enriched.enrichment_metrics.model == "claude-sonnet-4-6"

    def test_enrich_metrics_none_on_api_failure(self):
        enricher = ClaudeEnricher(api_key="bad-key")
        result = _make_result()

        with patch("urllib.request.urlopen", side_effect=OSError("network down")):
            enriched = enricher.enrich(result)

        assert enriched.enrichment_metrics is None

    def test_enrich_metrics_with_zero_cache(self):
        """Verify metrics work when cache_read=0 (cache miss / first call)."""
        enricher = ClaudeEnricher(api_key="test-key")
        result = _make_result()
        no_cache_usage = {
            "input_tokens": 1430,
            "output_tokens": 150,
            "cache_creation_input_tokens": 1430,
            "cache_read_input_tokens": 0,
        }
        resp = _make_api_response(self._response_text(), usage=no_cache_usage)
        with patch("urllib.request.urlopen", return_value=resp):
            enriched = enricher.enrich(result)

        assert enriched.enrichment_metrics is not None
        assert enriched.enrichment_metrics.estimated_savings_pct == 0.0

    def test_to_dict_includes_enrichment_metrics(self):
        enricher = ClaudeEnricher(api_key="test-key")
        result = _make_result()

        with patch("urllib.request.urlopen", return_value=_make_api_response(self._response_text())):
            enriched = enricher.enrich(result)

        d = enriched.to_dict()
        assert "enrichment_metrics" in d
        assert d["enrichment_metrics"]["input_tokens"] == 820
        assert d["enrichment_metrics"]["estimated_savings_pct"] > 0

    def test_to_dict_no_enrichment_metrics_key_when_none(self):
        result = _make_result()
        # No enrichment done
        d = result.to_dict()
        assert "enrichment_metrics" not in d


# ── dry-run estimate (no API call) ────────────────────────────────────────────

class TestDryRunEstimate:
    def test_estimate_dry_run_returns_metrics_without_api(self):
        """estimate_dry_run must not call the API."""
        enricher = ClaudeEnricher(api_key="", model="claude-opus-4-6")
        result = _make_result()

        with patch("urllib.request.urlopen") as mock_open:
            metrics = enricher.estimate_dry_run(result)
            mock_open.assert_not_called()

        assert metrics is not None
        assert metrics.input_tokens > 0

    def test_estimate_dry_run_model_set(self):
        enricher = ClaudeEnricher(api_key="", model="claude-sonnet-4-6")
        result = _make_result()
        metrics = enricher.estimate_dry_run(result)
        assert metrics.model == "claude-sonnet-4-6"

    def test_estimate_dry_run_cache_read_is_system_prompt_estimate(self):
        """Warm-cache assumption: system prompt (~200 tokens) is a cache hit."""
        enricher = ClaudeEnricher(api_key="", model="claude-opus-4-6")
        result = _make_result()
        metrics = enricher.estimate_dry_run(result)
        assert metrics.cache_read_input_tokens == 200

    def test_estimate_dry_run_savings_pct_positive(self):
        """A warm-cache estimate should show positive savings."""
        enricher = ClaudeEnricher(api_key="", model="claude-opus-4-6")
        result = _make_result()
        metrics = enricher.estimate_dry_run(result)
        assert metrics.estimated_savings_pct > 0

    def test_from_text_estimate_scales_with_text_length(self):
        """Longer text should produce more estimated input tokens."""
        short = EnrichmentMetrics.from_text_estimate("short text")
        long_ = EnrichmentMetrics.from_text_estimate("x" * 4000)
        assert long_.input_tokens > short.input_tokens

    def test_from_text_estimate_empty_text(self):
        """Empty prompt text should produce at least 1 token (not divide by zero)."""
        m = EnrichmentMetrics.from_text_estimate("")
        assert m.input_tokens >= 1

    def test_estimate_dry_run_cost_positive(self):
        enricher = ClaudeEnricher(api_key="", model="claude-opus-4-6")
        result = _make_result()
        metrics = enricher.estimate_dry_run(result)
        cost = metrics.estimated_cost_usd()
        assert cost["total_usd"] > 0

    def test_format_report_dry_run(self):
        enricher = ClaudeEnricher(api_key="", model="claude-opus-4-6")
        result = _make_result()
        metrics = enricher.estimate_dry_run(result)
        report = metrics.format_report()
        assert "Claude token efficiency" in report
        assert "estimated_savings" in report
