"""Immutable, profile-scoped facts; absence of facts never implies completeness."""
from dataclasses import dataclass
from enum import Enum
import re
from typing import Union


class ContractFamily(str, Enum):
    API_ROUTE = 'api-route'
    API_RESPONSE = 'api-response'
    ENV_KEY = 'env-key'


class ReasonCode(str, Enum):
    MISSING_SOURCE = 'missing_source'
    UNSUPPORTED_BINDING = 'unsupported_binding'
    UNSUPPORTED_PROFILE = 'profile_not_supported'
    OPEN_DEPENDENCY_SCOPE = 'open_dependency_scope'
    RESOURCE_LIMIT = 'resource_limit'
    PATCH_ONLY = 'patch_only_input'


Identity = Union[str, tuple[str, str]]


def _nonempty_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be nonempty text')


@dataclass(frozen=True)
class FactBasis:
    """An analysis boundary, not a claim of service-wide discovery/closure.

    Evidence references are immutable opaque IDs supplied by the analyzer.
    These constructors validate structure, not the truth of an analyzer claim.
    """
    scope_id: str
    family: ContractFamily
    profile_id: str
    profile_version: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self):
        for label in ('scope_id', 'profile_id', 'profile_version'):
            _nonempty_text(getattr(self, label), label)
        if not isinstance(self.family, ContractFamily):
            raise ValueError('family must be a ContractFamily')
        if not isinstance(self.evidence_refs, (list, tuple)) or not self.evidence_refs:
            raise ValueError('at least one evidence reference is required')
        for reference in self.evidence_refs:
            _nonempty_text(reference, 'evidence reference')
        object.__setattr__(self, 'evidence_refs', tuple(sorted(set(self.evidence_refs))))

    @property
    def domain(self):
        return self.scope_id, self.family, self.profile_id, self.profile_version


def _facts(values, basis):
    if not isinstance(basis, FactBasis):
        raise ValueError('basis must be a FactBasis')
    if basis.family == ContractFamily.API_RESPONSE:
        raise ValueError('response shapes require a dedicated fact model, not identity sets')
    if not isinstance(values, (set, frozenset, list, tuple)):
        raise ValueError('facts must be an identity collection')
    for value in values:
        if basis.family == ContractFamily.ENV_KEY:
            if not isinstance(value, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]*', value):
                raise ValueError('environment identity must be a key name')
        elif (not isinstance(value, tuple) or len(value) != 2
              or not all(isinstance(part, str) for part in value)
              or value[0] not in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'TRACE'}
              or not value[1].startswith('/')):
            raise ValueError('route identity must be an uppercase method and absolute path')
    return frozenset(values)


def _reasons(values):
    if not isinstance(values, (tuple, list)) or not values or any(not isinstance(value, ReasonCode) for value in values):
        raise ValueError('open facts require stable reason codes')
    return tuple(sorted(set(values), key=lambda value: value.value))


@dataclass(frozen=True)
class ExactFacts:
    basis: FactBasis
    facts: frozenset[Identity]

    def __post_init__(self):
        object.__setattr__(self, 'facts', _facts(self.facts, self.basis))

    @property
    def must(self):
        return self.facts

    @property
    def may(self):
        return self.facts


@dataclass(frozen=True)
class BoundedFacts:
    basis: FactBasis
    must: frozenset[Identity]
    may: frozenset[Identity]
    reasons: tuple[ReasonCode, ...]

    def __post_init__(self):
        object.__setattr__(self, 'must', _facts(self.must, self.basis))
        object.__setattr__(self, 'may', _facts(self.may, self.basis))
        object.__setattr__(self, 'reasons', _reasons(self.reasons))
        if not self.must <= self.may:
            raise ValueError('must facts must be a subset of may facts')


@dataclass(frozen=True)
class UnknownFacts:
    basis: FactBasis
    must: frozenset[Identity]
    reasons: tuple[ReasonCode, ...]

    def __post_init__(self):
        object.__setattr__(self, 'must', _facts(self.must, self.basis))
        object.__setattr__(self, 'reasons', _reasons(self.reasons))

    @property
    def may(self):
        return None  # Top, never the empty set.


FactOutcome = Union[ExactFacts, BoundedFacts, UnknownFacts]


@dataclass(frozen=True)
class ExactDelta:
    basis: FactBasis
    added: frozenset[Identity]
    removed: frozenset[Identity]

    def __post_init__(self):
        object.__setattr__(self, 'added', _facts(self.added, self.basis))
        object.__setattr__(self, 'removed', _facts(self.removed, self.basis))
        if self.added & self.removed:
            raise ValueError('an exact identity cannot be both added and removed')

    @property
    def is_empty(self):
        # This only proves no identity delta within basis, not discovery closure.
        return not (self.added or self.removed)


@dataclass(frozen=True)
class BoundedDelta:
    basis: FactBasis
    added_must: frozenset[Identity]
    added_may: frozenset[Identity]
    removed_must: frozenset[Identity]
    removed_may: frozenset[Identity]
    reasons: tuple[ReasonCode, ...]

    def __post_init__(self):
        _delta_bounds(self, allow_top=False)


@dataclass(frozen=True)
class UnknownDelta:
    basis: FactBasis
    added_must: frozenset[Identity]
    added_may: Union[frozenset[Identity], None]
    removed_must: frozenset[Identity]
    removed_may: Union[frozenset[Identity], None]
    reasons: tuple[ReasonCode, ...]

    def __post_init__(self):
        _delta_bounds(self, allow_top=True)
        if self.added_may is not None and self.removed_may is not None:
            raise ValueError('unknown delta requires an open upper bound')


def _delta_bounds(delta, *, allow_top):
    for name in ('added_must', 'added_may', 'removed_must', 'removed_may'):
        value = getattr(delta, name)
        if value is None and allow_top and name.endswith('_may'):
            continue
        object.__setattr__(delta, name, _facts(value, delta.basis))
    object.__setattr__(delta, 'reasons', _reasons(delta.reasons))
    for prefix in ('added', 'removed'):
        lower, upper = getattr(delta, prefix + '_must'), getattr(delta, prefix + '_may')
        if upper is not None and not lower <= upper:
            raise ValueError('must delta must be a subset of may delta')
    if delta.added_must & delta.removed_must:
        raise ValueError('an identity cannot be certainly both added and removed')


DeltaOutcome = Union[ExactDelta, BoundedDelta, UnknownDelta]
