"""
JSON 리포트 생성기 — EvaluationResult → dict/str.
"""
import json
from drift_gate.core.models.result import EvaluationResult


class JsonReporter:
    def render(self, result: EvaluationResult) -> dict:
        """EvaluationResult → JSON-serializable dict."""
        return result.to_dict()

    def render_str(self, result: EvaluationResult, indent: int = 2) -> str:
        return json.dumps(self.render(result), ensure_ascii=False, indent=indent)
