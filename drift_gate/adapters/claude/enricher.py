"""
Claude API adapter — violation별 체크리스트/근거 보강 (선택적).
core 로직에 필수 의존 없음.
API 키 없으면 fallback checklist 유지.
"""
import json
import re
import urllib.request
import urllib.error
from typing import List, Optional, Tuple

from drift_gate.core.models.result import EnrichmentMetrics, EvaluationResult, Violation

DEFAULT_MODEL = "claude-opus-4-6"

_SYSTEM_PROMPT = (
    "팀 계약 문서와 코드 변경의 정합성 점검 분석가입니다.\n"
    "각 위반 항목에 대해 아래 형식으로 출력하세요:\n\n"
    "### [SEVERITY] rule-id\n"
    "왜 필요한가: <1-2문장>\n\n"
    "체크리스트:\n"
    "- [ ] <액션 1>\n"
    "- [ ] <액션 2>\n\n"
    "Changed contract summary: <변경된 계약 요약>\n"
    "Missing docs explanation: <왜 해당 문서가 필요한지>\n"
    "Docs update draft: <문서에 붙일 수 있는 짧은 초안>\n"
    "False positive candidate: <오탐 가능성이 있으면 근거, 아니면 낮음>"
)


class ClaudeEnricher:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self._api_key = api_key
        self._model = model

    def enrich(self, result: EvaluationResult) -> EvaluationResult:
        """
        violations에 Claude 생성 체크리스트를 병합.
        실패 시 fallback checklist 유지 — 예외 전파 안 함.
        usage 메타데이터를 result.enrichment_metrics에 기록.
        """
        if not result.violations:
            return result

        summary = _build_summary(result.violations)
        prompt = _build_prompt(summary)

        try:
            enrichment, metrics = self._call_api(prompt)
        except Exception:
            return result  # fallback 유지

        if metrics is not None:
            result.enrichment_metrics = metrics

        if not enrichment:
            return result

        for v in result.violations:
            section = _extract_section(enrichment, v.rule_id)
            if section:
                items = _parse_checklist(section)
                if items:
                    v.checklist = items
                v.changed_contract_summary = (
                    _extract_field(section, "Changed contract summary")
                    or _extract_field(section, "변경 계약 요약")
                    or v.changed_contract_summary
                )
                v.missing_docs_explanation = (
                    _extract_field(section, "Missing docs explanation")
                    or _extract_field(section, "문서 누락 설명")
                    or v.missing_docs_explanation
                )
                v.docs_update_draft = (
                    _extract_field(section, "Docs update draft")
                    or _extract_field(section, "문서 업데이트 초안")
                    or v.docs_update_draft
                )
                v.false_positive_note = (
                    _extract_field(section, "False positive candidate")
                    or _extract_field(section, "false positive 후보")
                    or v.false_positive_note
                )

        return result

    def estimate_dry_run(self, result: EvaluationResult) -> EnrichmentMetrics:
        """Return estimated token metrics without making an API call.

        Useful for cost planning before enabling Claude enrichment.
        The estimate is based on prompt text length; actual tokens depend on
        the model tokeniser and will differ from real API usage.
        """
        summary = _build_summary(result.violations)
        prompt = _build_prompt(summary)
        return EnrichmentMetrics.from_text_estimate(prompt, model=self._model)

    def generate_docs_draft(self, result: EvaluationResult) -> dict[str, str]:
        """Generate a brief Markdown draft for each violation's missing documentation.

        For each violation, calls the Claude API to produce a short Markdown draft
        that can be copy-pasted into the missing document. Falls back gracefully to
        an empty dict on API failure.

        Returns:
            A dict mapping rule_id -> draft_text (Markdown string).
        """
        if not result.violations:
            return {}

        drafts: dict[str, str] = {}
        for v in result.violations:
            prompt = _build_draft_prompt(v)
            try:
                text, _ = self._call_api(prompt)
            except Exception:
                text = None

            if text:
                drafts[v.rule_id] = text.strip()
                # Also attach to violation checklist with a prefix so it surfaces
                # in reports that don't have a separate drafts field
                if not any(item.startswith("Draft:") for item in v.checklist):
                    v.checklist.append(f"Draft: {text.strip()[:200]}")
            else:
                # Deterministic fallback: generate a minimal draft from violation data
                drafts[v.rule_id] = _fallback_draft(v)

        return drafts

    def _call_api(self, prompt: str) -> Tuple[Optional[str], Optional[EnrichmentMetrics]]:
        """Call Claude API and return (response_text, usage_metrics).

        Returns a tuple of (text, metrics). Either may be None on partial failure.
        Note: API key value is never logged.
        """
        # System prompt is static (~200 tokens) — mark ephemeral so repeated calls
        # within the same 5-min cache window avoid re-billing the fixed prefix.
        payload = json.dumps({
            "model": self._model,
            "max_tokens": 2048,
            "system": [
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "prompt-caching-2024-07-31",
            },
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            text = data.get("content", [{}])[0].get("text")
            usage_raw = data.get("usage", {})
            metrics = EnrichmentMetrics(
                model=self._model,
                input_tokens=usage_raw.get("input_tokens", 0),
                output_tokens=usage_raw.get("output_tokens", 0),
                cache_creation_input_tokens=usage_raw.get("cache_creation_input_tokens", 0),
                cache_read_input_tokens=usage_raw.get("cache_read_input_tokens", 0),
            )
            return text, metrics


def _build_summary(violations: List[Violation]) -> str:
    lines = []
    for v in violations:
        lines.append(
            f"[{v.severity}] {v.rule_id}\n"
            f"  메시지: {v.message}\n"
            f"  변경 유형: {', '.join(v.change_types)}\n"
            f"  트리거 파일: {', '.join(f.path for f in v.trigger_files)}\n"
            f"  불충족 묶음: {'; '.join(g.name for g in v.unsatisfied_groups)}"
        )
    return "\n\n".join(lines)


def _build_prompt(summary: str) -> str:
    return f"## 정책 위반 목록\n\n{summary}"


def _extract_section(content: str, rule_id: str) -> Optional[str]:
    m = re.search(
        r"###[^\n]*" + re.escape(rule_id) + r"[^\n]*\n(.*?)(?=###|\Z)",
        content,
        re.DOTALL,
    )
    return m.group(1).strip() if m else None


def _parse_checklist(section: str) -> List[str]:
    return [
        m.group(1).strip()
        for m in re.finditer(r"-\s*\[\s*\]\s*(.+)", section)
    ]


def _build_draft_prompt(violation: Violation) -> str:
    trigger_paths = ", ".join(f.path for f in violation.trigger_files) or "unknown"
    groups = "; ".join(g.name for g in violation.unsatisfied_groups) or "required docs"
    required_files = ", ".join(
        item
        for g in violation.unsatisfied_groups
        for item in g.required
    ) or "documentation files"
    return (
        "You are a technical writer helping a software team document a contract change.\n\n"
        f"Rule violated: {violation.rule_id}\n"
        f"Severity: {violation.severity}\n"
        f"Message: {violation.message}\n"
        f"Changed files: {trigger_paths}\n"
        f"Missing documentation: {groups}\n"
        f"Required files: {required_files}\n\n"
        "Write a brief Markdown draft (under 200 words) that could be added to the missing "
        "documentation files. Focus on what changed, why it matters, and what consumers need "
        "to know. Use headings and bullet points. Output only the Markdown draft, no preamble."
    )


def _fallback_draft(violation: Violation) -> str:
    """Return a minimal deterministic draft when Claude API is unavailable."""
    trigger_paths = ", ".join(f.path for f in violation.trigger_files) or "unknown"
    groups = "\n".join(
        f"- **{g.name}**: {', '.join(g.required)}"
        for g in violation.unsatisfied_groups
    ) or "- Required documentation files"
    return (
        f"## Change Summary\n\n"
        f"The following files were changed: `{trigger_paths}`\n\n"
        f"## Documentation Required\n\n"
        f"{groups}\n\n"
        f"## What to Document\n\n"
        f"- Describe what changed and why\n"
        f"- List any breaking changes or migration steps\n"
        f"- Update the relevant contract/spec sections\n"
    )


def _extract_field(section: str, label: str) -> str:
    pattern = (
        rf"{re.escape(label)}\s*:\s*(.*?)(?=\n[A-Z가-힣][^:\n]{{1,80}}\s*:|\n체크리스트\s*:|\n---|\Z)"
    )
    match = re.search(pattern, section, re.DOTALL | re.IGNORECASE)
    if not match:
        return ""
    return match.group(1).strip()
