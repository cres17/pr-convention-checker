"""
Drift Gate Core Engine — 외부 의존성 없음.
GitHub API / CLI / LLM 호출 금지.

모든 입출력은 adapters에서 처리하고 이 함수에 데이터를 전달.
"""
from typing import List, Optional, Union

from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.policy import Policy
from drift_gate.core.models.result import EvaluationResult, DriftIgnoreDirective, ScanMetrics
from drift_gate.core.classification.classifier import classify_change_types
from drift_gate.core.evaluation.evaluator import evaluate
from drift_gate.core.gating.gate import decide_gate
from drift_gate.utils.glob_matcher import matches_any


def run(
    changed_files: List[ChangedFile],
    drift_ignores: Optional[List[DriftIgnoreDirective]] = None,
    policy: Optional[Policy] = None,
    policy_path: Optional[Union[str, object]] = None,
) -> EvaluationResult:
    """
    Core 엔진 진입점.

    Args:
        changed_files: 변경 파일 목록 (adapter에서 수집)
        drift_ignores: PR description에서 파싱된 ignore 지시문
        policy: 이미 로드된 Policy 객체 (있으면 policy_path 무시)
        policy_path: .drift-gate.yml 경로 (policy가 없을 때 로드)

    Returns:
        EvaluationResult (result 필드에 gate 판정 포함)
    """
    drift_ignores = drift_ignores or []

    # Policy loading is adapter-owned; core stays free of filesystem I/O.
    if policy is None:
        result = EvaluationResult(
            change_types=[],
            violations=[],
            skipped_rules=[],
            rejected_ignores=[],
            gate=_default_gate(),
            no_policy=True,
            result="pass",
            scan_metrics=_scan_metrics(changed_files, _default_policy_for_metrics()),
        )
        return result

    # 변경 파일 없음
    if not changed_files:
        result = EvaluationResult(
            change_types=[],
            violations=[],
            skipped_rules=[],
            rejected_ignores=[],
            gate=policy.gate,
            skip=True,
            skip_reason="no-changes",
            result="pass",
            scan_metrics=_scan_metrics(changed_files, policy),
        )
        return result

    # 변경 유형 분류
    change_types = classify_change_types(changed_files)

    # docs-only / test-only → 평가 생략
    if change_types and change_types[0] in ("docs-only", "test-only"):
        result = EvaluationResult(
            change_types=change_types,
            violations=[],
            skipped_rules=[],
            rejected_ignores=[],
            gate=policy.gate,
            skip=True,
            skip_reason=change_types[0],
            result="pass",
            scan_metrics=_scan_metrics(changed_files, policy),
        )
        return result

    # 규칙 평가
    violations, skipped_rules, rejected_ignores, rule_decisions, ignore_audit = evaluate(
        policy, changed_files, drift_ignores
    )

    result = EvaluationResult(
        change_types=change_types,
        violations=violations,
        skipped_rules=skipped_rules,
        rejected_ignores=rejected_ignores,
        gate=policy.gate,
        rule_decisions=rule_decisions,
        ignore_audit=ignore_audit,
        scan_metrics=_scan_metrics(changed_files, policy),
    )

    # CI 게이트 판정
    decide_gate(result)

    return result


def _default_gate():
    from drift_gate.core.models.policy import Gate
    return Gate()


def _default_policy_for_metrics():
    return Policy()


def _scan_metrics(changed_files: List[ChangedFile], policy: Policy) -> ScanMetrics:
    return ScanMetrics(
        scanned_files=len(changed_files),
        skipped_ignored_files=sum(
            1 for f in changed_files if matches_any(f.path, policy.ignore_paths)
        ),
        skipped_binary_files=sum(
            1 for f in changed_files if "binary file skipped" in f.patch.lower()
        ),
        skipped_large_files=sum(
            1 for f in changed_files if "large file skipped" in f.patch.lower()
        ),
        evaluated_rules=len(policy.rules),
    )
