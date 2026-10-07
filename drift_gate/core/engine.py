"""
Drift Gate Core Engine — 외부 의존성 없음.
GitHub API / CLI / LLM 호출 금지.

모든 입출력은 adapters에서 처리하고 이 함수에 데이터를 전달.
"""
from typing import List, Optional, Union

from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.policy import Policy
from drift_gate.core.models.evaluation_context import EvaluationContext
from drift_gate.core.models.result import EvaluationResult, DriftIgnoreDirective, ScanMetrics
from drift_gate.core.classification.classifier import classify_change_types
from drift_gate.core.evaluation.evaluator import evaluate
from drift_gate.core.gating.gate import decide_gate
from drift_gate.core.change_paths import is_ignored, triggers
from drift_gate.core.policy.validator import validate


def run(
    changed_files: List[ChangedFile],
    drift_ignores: Optional[List[DriftIgnoreDirective]] = None,
    policy: Optional[Policy] = None,
    policy_path: Optional[Union[str, object]] = None,
    context: Optional[EvaluationContext] = None,
    contract_proofs: bool = False,
) -> EvaluationResult:
    """
    Core 엔진 진입점.

    Args:
        changed_files: 변경 파일 목록 (adapter에서 수집)
        drift_ignores: PR description에서 파싱된 ignore 지시문
        policy: 이미 로드된 Policy 객체 (있으면 policy_path 무시)
        policy_path: 이전 API 호환 인자. 경로만 전달하는 호출은 거부합니다.
            정책 파일은 adapter에서 로드해 policy로 전달해야 합니다.
        context: 명시적 UTC 평가 날짜. 만료가 있는 ignore는 이 입력이 필요합니다.

    Returns:
        EvaluationResult (result 필드에 gate 판정 포함)
    """
    drift_ignores = drift_ignores or []
    if type(contract_proofs) is not bool:
        raise ValueError('contract_proofs must be boolean')
    if context is not None and not isinstance(context, EvaluationContext):
        raise ValueError('context must be an EvaluationContext')

    if policy is None and policy_path is not None:
        raise ValueError("Load policy_path in the adapter and pass the Policy as policy.")

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
        return _with_contract_diagnostics(result, contract_proofs)

    # Direct callers receive the same deterministic policy contract as loaders.
    validate(policy).raise_if_errors()

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
        return _with_contract_diagnostics(result, contract_proofs)

    # 변경 유형 분류
    change_types = classify_change_types(changed_files)

    # docs-only / test-only → 평가 생략
    explicit_trigger = any(triggers(f, r.when.any_changed) and not is_ignored(f, policy.ignore_paths)
                           for f in changed_files for r in policy.rules)
    if change_types and change_types[0] in ("docs-only", "test-only") and not explicit_trigger:
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
        return _with_contract_diagnostics(result, contract_proofs)

    # 규칙 평가
    from drift_gate.core.evaluation.analysis_session import AnalysisSession
    session = AnalysisSession()
    violations, skipped_rules, rejected_ignores, rule_decisions, ignore_audit = evaluate(
        policy, changed_files, drift_ignores, context=context, session=session
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

    result.scan_metrics.evaluated_rules = sum(d.status in ('pass', 'fail', 'rejected-ignore', 'undetermined') for d in rule_decisions)

    # CI 게이트 판정
    decide_gate(result)
    return _with_contract_diagnostics(result, contract_proofs, session)


def _with_contract_diagnostics(result, enabled, session=None):
    if enabled:
        from drift_gate.core.compat.legacy_result import ContractDiagnostics
        result.contract_diagnostics = ContractDiagnostics(session.shadow_contract_proofs if session else (),
            session.contract_records_seen if session else 0, session.limit if session else 128)
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
            1 for f in changed_files if is_ignored(f, policy.ignore_paths)
        ),
        skipped_binary_files=sum(
            1 for f in changed_files if "binary file skipped" in f.patch.lower()
        ),
        skipped_large_files=sum(
            1 for f in changed_files if "large file skipped" in f.patch.lower()
        ),
        evaluated_rules=0,
        analysis_notes=[{"path": f.path, "method": f.analysis_method, "reason": f.analysis_reason}
                        for f in changed_files if f.analysis_method != "not-analyzed"],
    )
