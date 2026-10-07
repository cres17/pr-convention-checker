"""Immutable obligation plans with explicit bindings and mandatory open guards.

This is an internal versioned migration API. It neither reinterprets legacy
YAML nor certifies service closure, source authenticity, or proof witnesses.
"""
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json

from drift_gate.core.contracts.discovery import DiscoveryDomain, DiscoveryResult
from drift_gate.core.models.facts import (
    BoundedDelta, ContractFamily, ExactDelta, UnknownDelta,
)


class Truth(str, Enum):
    TRUE = 'T'
    FALSE = 'F'
    UNKNOWN = 'U'


class PlanReason(str, Enum):
    MISSING_ASSESSMENT = 'missing_contract_assessment'
    UNMAPPED_DOCUMENT = 'unmapped_contract_document'
    ANALYSIS_OPEN = 'contract_analysis_open'
    DOCUMENT_OPEN = 'contract_document_open'


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('expected nonempty text')


def _texts(values, *, allow_empty=False):
    if not isinstance(values, (tuple, list)) or (not values and not allow_empty):
        raise ValueError('expected text entries')
    for value in values:
        _text(value)
    if len(set(values)) != len(values):
        raise ValueError('duplicate text entries')
    return tuple(sorted(values))


def _profile(ref):
    if ref is None:
        return None
    if not isinstance(ref, (tuple, list)) or len(ref) != 2:
        raise ValueError('invalid profile reference')
    for item in ref:
        _text(item)
    return tuple(ref)


def _digest(parts):
    return sha256(json.dumps(parts, ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()


@dataclass(frozen=True)
class DocumentBinding:
    id: str
    profile_ref: tuple[str, str]
    selectors: tuple[str, ...]
    require_all: bool = False

    def __post_init__(self):
        _text(self.id)
        ref = _profile(self.profile_ref)
        if ref is None or type(self.require_all) is not bool:
            raise ValueError('binding requires a profile and boolean selector mode')
        object.__setattr__(self, 'profile_ref', ref)
        object.__setattr__(self, 'selectors', _texts(self.selectors))


@dataclass(frozen=True)
class DocumentBindings:
    schema: str
    entries: tuple[DocumentBinding, ...] = ()

    def __post_init__(self):
        if self.schema != 'contract-document-bindings-v1':
            raise ValueError('unsupported document binding schema')
        if not isinstance(self.entries, (tuple, list)) or any(not isinstance(item, DocumentBinding) for item in self.entries):
            raise ValueError('expected typed document bindings')
        if len({item.id for item in self.entries}) != len(self.entries) or len({item.profile_ref for item in self.entries}) != len(self.entries):
            raise ValueError('duplicate binding ID or ambiguous profile binding')
        object.__setattr__(self, 'entries', tuple(sorted(self.entries, key=lambda item: item.id)))


@dataclass(frozen=True)
class PlanRequest:
    rule_id: str
    group_id: str
    source_paths: tuple[str, ...]
    bindings: DocumentBindings
    relation_id: str = ''

    def __post_init__(self):
        _text(self.rule_id); _text(self.group_id)
        if not isinstance(self.bindings, DocumentBindings) or not isinstance(self.relation_id, str):
            raise ValueError('request requires versioned bindings and a relation label')
        object.__setattr__(self, 'source_paths', _texts(self.source_paths))

    @property
    def ref(self):
        return _digest((self.rule_id, self.group_id, self.relation_id, self.source_paths))


@dataclass(frozen=True)
class ContractScope:
    request_ref: str
    family: ContractFamily
    profile_ref: tuple[str, str] | None
    source_paths: tuple[str, ...]

    def __post_init__(self):
        _text(self.request_ref)
        if not isinstance(self.family, ContractFamily):
            raise ValueError('scope requires a typed family')
        object.__setattr__(self, 'profile_ref', _profile(self.profile_ref))
        object.__setattr__(self, 'source_paths', _texts(self.source_paths))

    @property
    def id(self):
        return 'selected-profile-modules:' + _digest((self.request_ref, self.family.value, self.profile_ref, self.source_paths))


def contract_scopes(request, discovery):
    if not isinstance(request, PlanRequest) or not isinstance(discovery, DiscoveryResult):
        raise ValueError('expected typed request and discovery')
    if request.source_paths != discovery.source_paths:
        raise ValueError('request and discovery source scopes differ')
    keys = {(domain.family, domain.profile_ref) for domain in discovery.candidates}
    # Include inactive modules in an activated profile partition. This prevents
    # file-to-file key moves from becoming spurious additions.
    return tuple(sorted((ContractScope(request.ref, family, profile,
                        tuple(domain.source_path for domain in discovery.domains
                              if (domain.family, domain.profile_ref) == (family, profile)))
                         for family, profile in keys), key=lambda item: item.id))


def delta_applicability(delta, family):
    if (not isinstance(family, ContractFamily) or family == ContractFamily.API_RESPONSE
        or not isinstance(delta, (ExactDelta, BoundedDelta, UnknownDelta)) or delta.basis.family != family):
        raise ValueError('delta family mismatch')
    if isinstance(delta, ExactDelta):
        added_must, removed_must = delta.added, delta.removed
        added_may, removed_may = delta.added, delta.removed
    else:
        added_must, removed_must = delta.added_must, delta.removed_must
        added_may, removed_may = delta.added_may, delta.removed_may
    if added_must or (family == ContractFamily.API_ROUTE and removed_must):
        return Truth.TRUE
    if added_may == frozenset() and (family == ContractFamily.ENV_KEY or removed_may == frozenset()):
        return Truth.FALSE
    return Truth.UNKNOWN


@dataclass(frozen=True)
class ContractAssessment:
    scope: ContractScope
    applicability: Truth
    delta: ExactDelta | BoundedDelta | UnknownDelta | None = None
    reason_codes: tuple[PlanReason, ...] = ()

    def __post_init__(self):
        if not isinstance(self.scope, ContractScope) or not isinstance(self.applicability, Truth):
            raise ValueError('assessment requires a typed scope and applicability')
        if not isinstance(self.reason_codes, (tuple, list)) or any(not isinstance(item, PlanReason) for item in self.reason_codes):
            raise ValueError('assessment requires typed reason codes')
        object.__setattr__(self, 'reason_codes', tuple(sorted(set(self.reason_codes), key=lambda item: item.value)))
        if self.delta is not None:
            if not isinstance(self.delta, (ExactDelta, BoundedDelta, UnknownDelta)):
                raise ValueError('expected a typed delta')
            basis = self.delta.basis
            if self.scope.profile_ref is None or basis.domain != (self.scope.id, self.scope.family, *self.scope.profile_ref):
                raise ValueError('assessment delta scope/profile mismatch')
            if delta_applicability(self.delta, self.scope.family) != self.applicability:
                raise ValueError('assessment contradicts its delta')
        elif self.scope.family != ContractFamily.API_RESPONSE and self.applicability != Truth.UNKNOWN:
            raise ValueError('identity applicability requires a delta')


@dataclass(frozen=True)
class ContractObligation:
    assessment: ContractAssessment
    binding: DocumentBinding | None

    def __post_init__(self):
        if not isinstance(self.assessment, ContractAssessment):
            raise ValueError('obligation requires an assessment')
        if self.binding is not None and (not isinstance(self.binding, DocumentBinding)
                                         or self.binding.profile_ref != self.assessment.scope.profile_ref):
            raise ValueError('obligation binding profile mismatch')

    @property
    def id(self):
        return 'contract:' + self.assessment.scope.id


@dataclass(frozen=True)
class ObligationPlan:
    request: PlanRequest
    discovery: DiscoveryResult
    obligations: tuple[ContractObligation, ...]
    guards: tuple[DiscoveryDomain, ...]  # Exact open domains, not optional hints.

    def __post_init__(self):
        scopes = contract_scopes(self.request, self.discovery)
        if not isinstance(self.obligations, (tuple, list)) or any(not isinstance(item, ContractObligation) for item in self.obligations):
            raise ValueError('expected typed obligations')
        actual = {item.assessment.scope.id: item.assessment.scope for item in self.obligations}
        if len(actual) != len(self.obligations) or actual != {scope.id: scope for scope in scopes}:
            raise ValueError('obligation scope omitted, duplicated, or substituted')
        expected_bindings = {item.profile_ref: item for item in self.request.bindings.entries}
        declared_profiles = {domain.profile_ref for domain in self.discovery.domains if domain.profile_ref is not None}
        if expected_bindings.keys() - declared_profiles:
            raise ValueError('binding references a profile outside the declared discovery')
        for obligation in self.obligations:
            if obligation.binding != expected_bindings.get(obligation.assessment.scope.profile_ref):
                raise ValueError('declared document binding omitted or substituted')
        if not isinstance(self.guards, (tuple, list)) or tuple(self.guards) != self.discovery.open_domains:
            raise ValueError('mandatory open discovery guards omitted or substituted')
        object.__setattr__(self, 'obligations', tuple(sorted(self.obligations, key=lambda item: item.id)))
        object.__setattr__(self, 'guards', tuple(self.guards))


def plan_contracts(request, discovery, assessments=()):
    scopes = contract_scopes(request, discovery)
    if not isinstance(assessments, (tuple, list)) or any(not isinstance(item, ContractAssessment) for item in assessments):
        raise ValueError('expected typed assessments')
    supplied = {item.scope.id: item for item in assessments}
    expected = {scope.id: scope for scope in scopes}
    if len(supplied) != len(assessments) or any(expected.get(item.scope.id) != item.scope for item in assessments):
        raise ValueError('assessment outside the declared scope or duplicate assessment')
    bindings = {item.profile_ref: item for item in request.bindings.entries}
    declared_profiles = {domain.profile_ref for domain in discovery.domains if domain.profile_ref is not None}
    if bindings.keys() - declared_profiles:
        raise ValueError('binding references a profile outside the declared discovery')
    obligations = tuple(ContractObligation(supplied.get(scope.id, ContractAssessment(
                                         scope, Truth.UNKNOWN, reason_codes=(PlanReason.MISSING_ASSESSMENT,))),
                                         bindings.get(scope.profile_ref)) for scope in scopes)
    return ObligationPlan(request, discovery, obligations, discovery.open_domains)


def conditional(applicability, requirement):
    if not isinstance(applicability, Truth) or not isinstance(requirement, Truth):
        raise ValueError('conditional requires typed truth values')
    if applicability == Truth.FALSE or requirement == Truth.TRUE:
        return Truth.TRUE
    return Truth.FALSE if applicability == Truth.TRUE and requirement == Truth.FALSE else Truth.UNKNOWN


@dataclass(frozen=True)
class ObligationOutcome:
    obligation: ContractObligation
    requirement: Truth
    requirement_complete: bool
    reason_codes: tuple[PlanReason, ...] = ()

    def __post_init__(self):
        if not isinstance(self.obligation, ContractObligation) or not isinstance(self.requirement, Truth) or type(self.requirement_complete) is not bool:
            raise ValueError('outcome requires typed obligation, truth, and completeness')
        if self.requirement == Truth.UNKNOWN and self.requirement_complete:
            raise ValueError('unknown requirement cannot be complete')
        if not isinstance(self.reason_codes, (tuple, list)) or any(not isinstance(item, PlanReason) for item in self.reason_codes):
            raise ValueError('outcome requires typed reason codes')
        if self.obligation.binding is None and self.requirement != Truth.UNKNOWN:
            raise ValueError('unmapped document cannot establish a requirement')
        object.__setattr__(self, 'reason_codes', tuple(sorted(set(self.reason_codes), key=lambda item: item.value)))

    @property
    def truth(self):
        return conditional(self.obligation.assessment.applicability, self.requirement)

    @property
    def complete(self):
        applicability = self.obligation.assessment.applicability
        return applicability == Truth.FALSE or applicability == Truth.TRUE and self.requirement_complete


@dataclass(frozen=True)
class PlanEvaluation:
    plan: ObligationPlan
    outcomes: tuple[ObligationOutcome, ...]
    document_digest: str = ''

    def __post_init__(self):
        if (not isinstance(self.document_digest, str) or self.document_digest and
            (len(self.document_digest) != 64 or any(c not in '0123456789abcdef' for c in self.document_digest))):
            raise ValueError('invalid document observation identity')
        if not isinstance(self.plan, ObligationPlan) or not isinstance(self.outcomes, (tuple, list)):
            raise ValueError('evaluation requires a plan and outcomes')
        if any(not isinstance(item, ObligationOutcome) for item in self.outcomes):
            raise ValueError('expected typed outcomes')
        actual = {item.obligation.id: item.obligation for item in self.outcomes}
        if len(actual) != len(self.outcomes) or actual != {item.id: item for item in self.plan.obligations}:
            raise ValueError('outcomes omitted, duplicated, or substituted')
        object.__setattr__(self, 'outcomes', tuple(sorted(self.outcomes, key=lambda item: item.obligation.id)))

    @property
    def truth(self):
        states = [item.truth for item in self.outcomes] + [Truth.UNKNOWN for _ in self.plan.guards]
        if Truth.FALSE in states:
            return Truth.FALSE
        return Truth.UNKNOWN if Truth.UNKNOWN in states else Truth.TRUE

    @property
    def complete_within_selection(self):
        return self.plan.discovery.complete_within_selection and all(item.complete for item in self.outcomes)

    def to_dict(self):
        return {'schema': 'contract-obligation-evaluation-v1', 'request_ref': self.plan.request.ref,
                'rule_id': self.plan.request.rule_id, 'group_id': self.plan.request.group_id,
                'relation_id': self.plan.request.relation_id, 'source_paths': list(self.plan.request.source_paths),
                'discovery': self.plan.discovery.to_dict(),
                'document_digest': self.document_digest,
                'truth': self.truth.value, 'complete_within_selection': self.complete_within_selection,
                'service_scope_certified': False, 'proof_dag_attached': False,
                'binding_schema': self.plan.request.bindings.schema,
                'bindings': [{'id': item.id, 'profile_ref': list(item.profile_ref),
                              'selectors': list(item.selectors), 'require_all': item.require_all}
                             for item in self.plan.request.bindings.entries],
                'obligations': [{'id': item.obligation.id, 'family': item.obligation.assessment.scope.family.value,
                    'profile_ref': list(item.obligation.assessment.scope.profile_ref) if item.obligation.assessment.scope.profile_ref else None,
                    'source_paths': list(item.obligation.assessment.scope.source_paths),
                    'applicability': item.obligation.assessment.applicability.value,
                    'requirement': item.requirement.value, 'truth': item.truth.value,
                    'not_applicable': item.obligation.assessment.applicability == Truth.FALSE,
                    'requirement_complete': item.requirement_complete,
                    'binding_id': item.obligation.binding.id if item.obligation.binding else None,
                    'reason_codes': [reason.value for reason in item.reason_codes]} for item in self.outcomes],
                'open_guards': [domain.to_dict() for domain in self.plan.guards]}
