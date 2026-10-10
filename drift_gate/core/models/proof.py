"""Immutable proof IR. Admitted premises are observations, not signed authority."""
from dataclasses import asdict, dataclass
from enum import Enum
from hashlib import sha256
import json

from drift_gate.core.contracts.planner import Truth


def texts(values):
    if (not isinstance(values, (tuple, list)) or
        any(not isinstance(value, str) or not value.strip() for value in values) or
        len(set(values)) != len(values)):
        raise ValueError('expected unique text references')
    return tuple(sorted(values))


def label(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('expected nonempty proof label')


def typed_rows(values, kind):
    if not isinstance(values, (tuple, list)) or any(not isinstance(row, kind) for row in values):
        raise ValueError('expected typed proof rows')
    if len({row.id for row in values}) != len(values):
        raise ValueError('duplicate proof row ID')
    return tuple(sorted(values, key=lambda row: row.id))


class Operator(str, Enum):
    ATOM = 'atom'
    NOT = 'not'
    ALL = 'all'
    ANY = 'any'
    CONDITIONAL = 'conditional'


@dataclass(frozen=True)
class CoverageDomain:
    id: str
    closed: bool
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self):
        label(self.id)
        if type(self.closed) is not bool:
            raise ValueError('closed must be boolean')
        object.__setattr__(self, 'reason_codes', texts(self.reason_codes))
        if not self.closed and not self.reason_codes:
            raise ValueError('open coverage requires a reason')


@dataclass(frozen=True)
class EvidenceClaim:
    id: str
    proposition_ref: str
    truth: Truth
    covered_domains: tuple[str, ...]
    profile_ref: tuple[str, str] | None = None

    def __post_init__(self):
        label(self.id); label(self.proposition_ref)
        if not isinstance(self.truth, Truth):
            raise ValueError('evidence requires typed truth')
        object.__setattr__(self, 'covered_domains', texts(self.covered_domains))
        if self.profile_ref is not None:
            if (not isinstance(self.profile_ref, (tuple, list)) or len(self.profile_ref) != 2):
                raise ValueError('invalid evidence profile')
            for value in self.profile_ref: label(value)
            object.__setattr__(self, 'profile_ref', tuple(self.profile_ref))


@dataclass(frozen=True)
class Proposition:
    id: str
    truth: Truth
    domain_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...] = ()
    profile_ref: tuple[str, str] | None = None
    assumptions: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self):
        label(self.id)
        if not isinstance(self.truth, Truth):
            raise ValueError('proposition requires typed truth')
        for name in ('domain_refs', 'evidence_refs', 'assumptions', 'reason_codes'):
            object.__setattr__(self, name, texts(getattr(self, name)))
        if self.profile_ref is not None:
            if not isinstance(self.profile_ref, (tuple, list)) or len(self.profile_ref) != 2:
                raise ValueError('invalid proposition profile')
            for value in self.profile_ref: label(value)
            object.__setattr__(self, 'profile_ref', tuple(self.profile_ref))


@dataclass(frozen=True)
class ProofContext:
    scope_ref: str
    input_ref: str
    domains: tuple[CoverageDomain, ...]
    propositions: tuple[Proposition, ...]
    evidence: tuple[EvidenceClaim, ...]
    profile_refs: tuple[tuple[str, str], ...] = ()
    structure: tuple['NodeSpec', ...] = ()
    root_ref: str = ''

    def __post_init__(self):
        label(self.scope_ref); label(self.input_ref)
        for name, kind in (('domains', CoverageDomain), ('propositions', Proposition), ('evidence', EvidenceClaim)):
            object.__setattr__(self, name, typed_rows(getattr(self, name), kind))
        if (not isinstance(self.profile_refs, (tuple, list)) or
            any(not isinstance(ref, (tuple, list)) or len(ref) != 2 for ref in self.profile_refs)):
            raise ValueError('invalid context profiles')
        for ref in self.profile_refs:
            for value in ref: label(value)
        object.__setattr__(self, 'profile_refs', tuple(sorted(set(tuple(ref) for ref in self.profile_refs))))
        object.__setattr__(self, 'structure', typed_rows(self.structure, NodeSpec))
        label(self.root_ref)

    @property
    def ref(self):
        return sha256(json.dumps(asdict(self), sort_keys=True, ensure_ascii=True,
                                 separators=(',', ':')).encode()).hexdigest()


@dataclass(frozen=True)
class ScopeCoverage:
    declared_scope_ref: str
    closed_domains: tuple[str, ...]
    open_domains: tuple[str, ...]

    def __post_init__(self):
        label(self.declared_scope_ref)
        for name in ('closed_domains', 'open_domains'):
            object.__setattr__(self, name, texts(getattr(self, name)))
        if set(self.closed_domains) & set(self.open_domains):
            raise ValueError('coverage domains overlap')

    @property
    def complete(self):
        return bool(self.closed_domains) and not self.open_domains


@dataclass(frozen=True)
class NodeSpec:
    id: str
    operator: Operator
    children: tuple[str, ...] = ()
    proposition_ref: str = ''

    def __post_init__(self):
        label(self.id)
        if not isinstance(self.operator, Operator):
            raise ValueError('expected typed operator')
        if (not isinstance(self.children, (tuple, list)) or
            any(not isinstance(ref, str) or not ref for ref in self.children)):
            raise ValueError('invalid child references')
        object.__setattr__(self, 'children', tuple(self.children))  # Conditional order matters.
        if not isinstance(self.proposition_ref, str):
            raise ValueError('invalid proposition reference')


@dataclass(frozen=True)
class ProofNode:
    spec: NodeSpec
    truth: Truth
    decision_proven: bool
    proof_ref: str | None
    sufficient_witness_refs: tuple[str, ...]
    coverage: ScopeCoverage

    @property
    def id(self):
        return self.spec.id


@dataclass(frozen=True)
class ProofEvaluation:
    context_ref: str
    root_ref: str
    nodes: tuple[ProofNode, ...]

    def __post_init__(self):
        label(self.context_ref); label(self.root_ref)
        object.__setattr__(self, 'nodes', typed_rows(self.nodes, ProofNode))

    def to_dict(self):
        """Serialize IR only; consumers must validate against their expected context."""
        return {'schema': 'contract-proof-evaluation-v1', 'context_ref': self.context_ref,
                'root_ref': self.root_ref, 'nodes': [asdict(node) for node in self.nodes],
                'assurance': 'logical-consistency-relative-to-admitted-premises',
                'source_authenticity_verified': False, 'current_head_certified': False,
                'service_scope_certified': False}

    @classmethod
    def from_dict(cls, payload):
        """Parse a bounded persisted IR; semantic validation still needs context."""
        keys = {'schema', 'context_ref', 'root_ref', 'nodes', 'assurance',
                'source_authenticity_verified', 'current_head_certified', 'service_scope_certified'}
        if (not isinstance(payload, dict) or set(payload) != keys or
            payload['schema'] != 'contract-proof-evaluation-v1' or
            payload['assurance'] != 'logical-consistency-relative-to-admitted-premises' or
            any(payload[key] is not False for key in ('source_authenticity_verified', 'current_head_certified', 'service_scope_certified'))):
            raise ValueError('invalid proof schema or unsupported assurance claim')
        if not isinstance(payload['nodes'], list) or not 0 < len(payload['nodes']) <= 4096:
            raise ValueError('invalid proof node count')
        nodes = []
        edges = 0
        for row in payload['nodes']:
            if not isinstance(row, dict) or set(row) != {'spec','truth','decision_proven','proof_ref','sufficient_witness_refs','coverage'}:
                raise ValueError('invalid proof node shape')
            spec = row['spec']; coverage = row['coverage']
            if not isinstance(spec, dict) or set(spec) != {'id','operator','children','proposition_ref'}:
                raise ValueError('invalid proof spec shape')
            if not isinstance(coverage, dict) or set(coverage) != {'declared_scope_ref','closed_domains','open_domains'}:
                raise ValueError('invalid coverage shape')
            if not isinstance(spec['children'], list):
                raise ValueError('invalid children')
            edges += len(spec['children'])
            if edges > 16384:
                raise ValueError('proof edge limit')
            if not isinstance(row['sufficient_witness_refs'], list):
                raise ValueError('invalid witnesses')
            nodes.append(ProofNode(NodeSpec(spec['id'], Operator(spec['operator']), spec['children'], spec['proposition_ref']),
                Truth(row['truth']), row['decision_proven'], row['proof_ref'],
                texts(row['sufficient_witness_refs']), ScopeCoverage(**coverage)))
        return cls(payload['context_ref'], payload['root_ref'], tuple(nodes))
