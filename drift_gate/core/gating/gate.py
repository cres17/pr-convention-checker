"""
CI 게이트 판정 — 순수 함수.
"""
from drift_gate.core.models.result import EvaluationResult


def decide_gate(result: EvaluationResult) -> str:
    """
    violations + gate 설정 → 'pass' | 'warn' | 'fail'.
    result.result 필드를 갱신하고 반환.
    """
    gate = result.gate

    if result.skip or result.no_policy:
        result.result = "pass"
        return "pass"

    blocker = result.blocker_count
    major = result.major_count
    minor = result.minor_count

    if blocker > 0 and gate.fail_on_blocker:
        decision = "fail"
    elif major >= gate.fail_on_major_count:
        decision = "fail"
    elif major > 0 or minor > 0:
        decision = "warn"
    else:
        decision = "pass"

    if any(g.decision == "undetermined" or g.verification == "partial"
           for d in result.rule_decisions for g in d.unsatisfied_groups + d.satisfied_groups):
        if gate.on_unverified == "fail":
            decision = "fail"
        elif decision == "pass":
            decision = "warn"

    result.result = decision
    return decision
