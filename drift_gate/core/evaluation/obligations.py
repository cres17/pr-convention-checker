"""Analyze and evaluate every declared contract partition without changing legacy gates."""
from dataclasses import replace

from drift_gate.core.contracts.delta import compare_facts
from drift_gate.core.contracts.input_identity import source_identity
from drift_gate.core.contracts.discovery import DiscoveryState
from drift_gate.core.contracts.planner import (
    ContractAssessment, DocumentBindings, ObligationOutcome, ObligationPlan, PlanEvaluation,
    PlanReason, PlanRequest, Truth, contract_scopes, delta_applicability, plan_contracts,
)
from drift_gate.core.contracts.profiles import DEFAULT_REGISTRY
from drift_gate.core.evaluation.analysis_session import AnalysisSession
from drift_gate.core.evaluation.api_schema import (
    UnknownResponse, api_schema_requirement, response_changes,
)
from drift_gate.core.evaluation.environment import environment_fact_outcome
from drift_gate.core.evaluation.routes import analyze_route_facts, route_document_requirement
from drift_gate.core.evaluation.static_routers import UnsupportedContract
from drift_gate.core.models.facts import ContractFamily, ExactDelta, ExactFacts, FactBasis, ReasonCode, UnknownFacts
from drift_gate.core.models.policy import Group
from drift_gate.utils.glob_matcher import matches_any


def _selected_files(paths, files):
    files = tuple(files)
    by_path = {file.path: file for file in files}
    if len(by_path) != len(files) or set(by_path) != set(paths):
        raise ValueError('source files do not match the declared scope')
    return by_path


def _response_files(scope, discovery, by_path):
    # Closed, inactive response domains certify absence of explicit response_model
    # within this profile. Ordinary route-only modules must not erase that absence.
    return [by_path[domain.source_path] for domain in discovery.domains
            if domain.source_path in scope.source_paths and domain.family == scope.family
            and (domain.activated or domain.state == DiscoveryState.OPEN)]


def _environment_pair(scope, files):
    observations = []
    for side in ('before', 'after'):
        rows = [environment_fact_outcome(
                '' if file.status == ('added' if side == 'before' else 'deleted') else getattr(file, side + '_source'),
                scope_id=scope.id, evidence_ref=f'{side}:{file.path}:legacy-selected-input') for file in files]
        basis = FactBasis(scope.id, scope.family, *scope.profile_ref,
                          tuple(ref for row in rows for ref in row.basis.evidence_refs))
        known = frozenset(key for row in rows for key in row.must)
        reasons = tuple(reason for row in rows for reason in getattr(row, 'reasons', ()))
        observations.append(UnknownFacts(basis, known, reasons) if reasons else ExactFacts(basis, known))
    return observations


def assess_contracts(request, discovery, source_files, session=None):
    scopes = contract_scopes(request, discovery)
    by_path = _selected_files(request.source_paths, source_files)
    if not discovery.source_digest or source_identity(by_path.values()) != discovery.source_digest:
        raise ValueError('source observations differ from discovery')
    session = session or AnalysisSession()
    assessments = []
    supported_refs = {profile.ref for profile in DEFAULT_REGISTRY.profiles}
    for scope in scopes:
        files = [by_path[path] for path in scope.source_paths]
        unsupported = any(ReasonCode.UNSUPPORTED_PROFILE in domain.reasons for domain in discovery.domains
                          if domain.source_path in scope.source_paths and domain.family == scope.family)
        if scope.profile_ref not in supported_refs or unsupported:
            assessments.append(ContractAssessment(scope, Truth.UNKNOWN))
            continue
        if scope.family == ContractFamily.API_RESPONSE:
            try:
                registration = analyze_route_facts(files, session)
                if not isinstance(registration.before, ExactFacts) or not isinstance(registration.after, ExactFacts):
                    raise UnsupportedContract('response identity scope is not closed')
                changes = response_changes(_response_files(scope, discovery, by_path), session)
                state = (Truth.TRUE if any(not isinstance(shape, UnknownResponse) for shape in changes.values())
                         else Truth.UNKNOWN if changes else Truth.FALSE)
            except UnsupportedContract:
                state = Truth.UNKNOWN
            assessments.append(ContractAssessment(scope, state))
            continue
        if scope.family == ContractFamily.ENV_KEY:
            before, after = _environment_pair(scope, files)
        else:
            pair = analyze_route_facts(files, session)
            before, after = [replace(row, basis=FactBasis(scope.id, scope.family, *scope.profile_ref,
                                                        row.basis.evidence_refs)) for row in (pair.before, pair.after)]
        delta = compare_facts(before, after)
        assessments.append(ContractAssessment(scope, delta_applicability(delta, scope.family), delta))
    return tuple(assessments)


def _combine(states, *, require_all):
    truths = [state for state, _ in states]
    decisive = Truth.FALSE if require_all else Truth.TRUE
    truth = (decisive if decisive in truths else Truth.UNKNOWN if Truth.UNKNOWN in truths
             else Truth.TRUE if require_all else Truth.FALSE)
    # A decisive witness does not erase unknown document alternatives from coverage.
    return truth, all(complete for _, complete in states)


def _environment_document(assessment, file):
    delta = assessment.delta
    lower = delta.added if isinstance(delta, ExactDelta) else delta.added_must
    upper = delta.added if isinstance(delta, ExactDelta) else delta.added_may
    if file.document_input_state == 'missing':
        keys = set()
    elif file.document_input_state == 'unavailable' or file.documented_env_keys is None:
        return Truth.UNKNOWN, False
    else:
        keys = set(file.documented_env_keys)
    if lower - keys:
        return Truth.FALSE, upper is not None
    if upper is not None and upper <= keys:
        return Truth.TRUE, True
    return Truth.UNKNOWN, False


def _document_outcome(obligation, file, discovery, by_path, session):
    assessment = obligation.assessment
    if assessment.delta is None and assessment.scope.family != ContractFamily.API_RESPONSE:
        return Truth.UNKNOWN, False
    if file.document_input_state == 'unavailable' or file.status == 'deleted' and file.document_input_state != 'missing':
        return Truth.UNKNOWN, False
    if assessment.scope.family == ContractFamily.ENV_KEY:
        return _environment_document(assessment, file)
    group = Group(name=obligation.binding.id, any_changed=[file.path])
    if assessment.scope.family == ContractFamily.API_ROUTE:
        delta = assessment.delta
        if not isinstance(delta, ExactDelta):
            return Truth.UNKNOWN, False
        check = route_document_requirement(group, [file], set(delta.added), set(delta.removed), session)
    else:
        check = api_schema_requirement(group, _response_files(assessment.scope, discovery, by_path), [file], session)
    truth = {'satisfied': Truth.TRUE, 'violated': Truth.FALSE, 'undetermined': Truth.UNKNOWN}.get(check.decision)
    if truth is None:
        raise ValueError('contract checker did not return a content decision')
    return truth, check.verification in {'verified', 'not-applicable'}


def evaluate_contract_plan(plan, source_files, documents, session=None):
    if not isinstance(plan, ObligationPlan):
        raise ValueError('expected a typed obligation plan')
    by_path = _selected_files(plan.request.source_paths, source_files)
    if not plan.discovery.source_digest or source_identity(by_path.values()) != plan.discovery.source_digest:
        raise ValueError('source observations differ from plan')
    session = session or AnalysisSession()
    documents = tuple(documents)
    if len({file.path for file in documents}) != len(documents):
        raise ValueError('duplicate document paths')
    outcomes = []
    for obligation in plan.obligations:
        assessment, binding = obligation.assessment, obligation.binding
        reasons = list(assessment.reason_codes)
        if assessment.applicability == Truth.UNKNOWN:
            reasons.append(PlanReason.ANALYSIS_OPEN)
        if binding is None:
            truth, complete = Truth.UNKNOWN, False
            reasons.append(PlanReason.UNMAPPED_DOCUMENT)
        elif assessment.applicability == Truth.FALSE:
            truth, complete = Truth.UNKNOWN, False  # Requirement is not evaluated for N/A.
        else:
            selections = []
            for selector in binding.selectors:
                candidates = [file for file in documents if matches_any(file.path, [selector])]
                states = [_document_outcome(obligation, file, plan.discovery, by_path, session)
                          for file in candidates]
                if any(marker in selector for marker in '*?['):
                    # These observations do not certify enumeration of a glob.
                    # Retain a possible unseen document alternative: it can
                    # weaken F to U, but cannot erase a known positive witness.
                    states.append((Truth.UNKNOWN, False))
                # Missing selection is not an authenticated absent document.
                selections.append(_combine(states, require_all=False) if states else (Truth.UNKNOWN, False))
            truth, complete = _combine(selections, require_all=binding.require_all)
            if not complete:
                reasons.append(PlanReason.DOCUMENT_OPEN)
        outcomes.append(ObligationOutcome(obligation, truth, complete, tuple(reasons)))
    result = PlanEvaluation(plan, tuple(outcomes), source_identity(documents))
    from drift_gate.core.evaluation.contract_proof import prove_contract_evaluation
    prove_contract_evaluation(result)  # Invalid shadow IR terminates; never projects a pass.
    return result


def inspect_contract_plan(request, source_files, documents=(), *, session=None):
    """Explicit internal API; callers supply bounded source/document observations."""
    from drift_gate.core.contracts.discovery import discover_contracts
    if not isinstance(request, PlanRequest):
        raise ValueError('expected a typed plan request')
    source_files = tuple(source_files)
    _selected_files(request.source_paths, source_files)
    session = session or AnalysisSession()
    discovery = discover_contracts(source_files, session=session)
    plan = plan_contracts(request, discovery, assess_contracts(request, discovery, source_files, session))
    return evaluate_contract_plan(plan, source_files, documents, session)


def shadow_legacy_plan(group, source_files, documents, session):
    """Legacy selectors declare no new profile/document mapping. Keep it visibly unmapped."""
    request = PlanRequest('legacy-selector-shadow', group.name or 'unnamed',
                          tuple(file.path for file in source_files),
                          DocumentBindings('contract-document-bindings-v1'))
    evaluation = inspect_contract_plan(request, source_files, documents, session=session)
    session.record_contract_plan(evaluation)
    return evaluation.plan
