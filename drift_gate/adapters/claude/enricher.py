"""
Claude API adapter — violation별 체크리스트/근거 보강 (선택적).
core 로직에 필수 의존 없음.
API 키 없으면 fallback checklist 유지.
"""
import json
import re
import urllib.request
import urllib.error
from typing import List, Optional

from drift_gate.core.models.result import EvaluationResult, Violation

DEFAULT_MODEL = "claude-opus-4-6"


class ClaudeEnricher:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self._api_key = api_key
        self._model = model

    def enrich(self, result: EvaluationResult) -> EvaluationResult:
        """
        violations에 Claude 생성 체크리스트를 병합.
        실패 시 fallback checklist 유지 — 예외 전파 안 함.
        """
        if not result.violations:
            return result

        summary = _build_summary(result.violations)
        prompt = _build_prompt(summary)

        try:
            enrichment = self._call_api(prompt)
        except Exception:
            return result  # fallback 유지

        if not enrichment:
            return result

        for v in result.violations:
            section = _extract_section(enrichment, v.rule_id)
            if section:
                items = _parse_checklist(section)
                if items:
                    v.checklist = items

        return result

    def _call_api(self, prompt: str) -> Optional[str]:
        payload = json.dumps({
            "model": self._model,
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            return data.get("content", [{}])[0].get("text")


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
    return (
        "팀 계약 문서와 코드 변경의 정합성 점검 분석가입니다.\n"
        "각 위반 항목에 대해 아래 형식으로 출력하세요:\n\n"
        "### [SEVERITY] rule-id\n"
        "왜 필요한가: <1-2문장>\n\n"
        "체크리스트:\n"
        "- [ ] <액션 1>\n"
        "- [ ] <액션 2>\n\n"
        "---\n\n"
        "## 정책 위반 목록\n\n"
        f"{summary}"
    )


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
