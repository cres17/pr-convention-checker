"""Independent IR validation against the caller's admitted immutable context.

This checks logical consistency, not parser soundness or source authenticity.
No file reads, manifests fetched from disk, clocks, or current-head assumptions.
"""
from collections import deque

from drift_gate.core.contracts.planner import Truth
from drift_gate.core.contracts.profiles import DEFAULT_REGISTRY
from drift_gate.core.models.proof import Operator, ProofContext, ProofEvaluation, ScopeCoverage


class ResultValidationError(ValueError):
    """An invalid IR must terminate evaluation, never become a pass/warn result."""


def require(condition, message):
    if not condition:
        raise ResultValidationError(message)


def validate_context(context, registry=DEFAULT_REGISTRY):
    require(isinstance(context, ProofContext), 'expected an admitted proof context')
    require(bool(context.domains) and bool(context.structure), 'empty declared scope or proposition structure')
    domains = {domain.id: domain for domain in context.domains}
    evidence = {claim.id: claim for claim in context.evidence}
    profiles = set(context.profile_refs)
    require(profiles <= {profile.ref for profile in registry.profiles}, 'unresolved profile reference')
    atoms = {atom.id: atom for atom in context.propositions}
    for claim in context.evidence:
        require(claim.proposition_ref in atoms, 'unresolved evidence proposition')
        require(set(claim.covered_domains) <= domains.keys(), 'unresolved evidence domain')
        require(claim.profile_ref is None or claim.profile_ref in profiles, 'unresolved evidence profile')
    for atom in context.propositions:
        require(set(atom.domain_refs) <= domains.keys(), 'unresolved proposition domain')
        require(atom.profile_ref is None or atom.profile_ref in profiles, 'unresolved proposition profile')
        require(set(atom.evidence_refs) <= evidence.keys(), 'unresolved evidence reference')
        claims = [evidence[ref] for ref in atom.evidence_refs]
        for claim in claims:
            require(claim.proposition_ref == atom.id and claim.truth == atom.truth and
                    claim.profile_ref == atom.profile_ref, 'contradictory proposition/evidence claim')
        if atom.truth != Truth.UNKNOWN:
            require(any(set(atom.domain_refs) <= set(claim.covered_domains) for claim in claims),
                    'known proposition lacks sufficiently scoped evidence')
    require({claim.id for atom in atoms.values() for claim in [evidence[ref] for ref in atom.evidence_refs]} == evidence.keys(),
            'unreferenced evidence claim')


def validate_proof_payload(payload, expected_context, **kwargs):
    """Validate decoded JSON against context supplied independently by the caller."""
    try:
        result = ProofEvaluation.from_dict(payload)
    except (ValueError, TypeError, KeyError) as exc:
        raise ResultValidationError('malformed proof payload') from exc
    return validate_proof_evaluation(result, expected_context, **kwargs)


def _truth(operator, values):
    # Independent table/branches rather than reusing the evaluator's reduction.
    if operator == Operator.NOT:
        return {'T': Truth.FALSE, 'F': Truth.TRUE, 'U': Truth.UNKNOWN}[values[0].value]
    if operator == Operator.CONDITIONAL:
        return {('T','T'): Truth.TRUE, ('T','F'): Truth.FALSE, ('T','U'): Truth.UNKNOWN,
                ('F','T'): Truth.TRUE, ('F','F'): Truth.TRUE, ('F','U'): Truth.TRUE,
                ('U','T'): Truth.TRUE, ('U','F'): Truth.UNKNOWN, ('U','U'): Truth.UNKNOWN}[
                    values[0].value, values[1].value]
    if operator == Operator.ALL:
        return Truth.FALSE if Truth.FALSE in values else Truth.TRUE if all(v == Truth.TRUE for v in values) else Truth.UNKNOWN
    return Truth.TRUE if Truth.TRUE in values else Truth.FALSE if all(v == Truth.FALSE for v in values) else Truth.UNKNOWN


def validate_proof_evaluation(result, expected_context, *, registry=DEFAULT_REGISTRY, max_nodes=4096, max_depth=128, max_edges=16384):
    validate_context(expected_context, registry)
    require(type(max_nodes) is int and max_nodes > 0 and type(max_depth) is int and max_depth > 0 and
            type(max_edges) is int and max_edges >= 0, 'invalid validator limits')
    require(isinstance(result, ProofEvaluation), 'expected typed proof evaluation')
    require(result.context_ref == expected_context.ref, 'result context differs from expected inputs')
    require(result.root_ref == expected_context.root_ref, 'root proposition substituted')
    require(0 < len(result.nodes) <= max_nodes, 'proof node limit or empty proof')
    require(sum(len(node.spec.children) for node in result.nodes) <= max_edges, 'proof edge limit')
    nodes = {node.id: node for node in result.nodes}
    require(len(nodes) == len(result.nodes), 'duplicate node ID')
    expected_specs = {spec.id: spec for spec in expected_context.structure}
    require({ref: node.spec for ref, node in nodes.items()} == expected_specs, 'declared proposition structure omitted or substituted')
    require(result.root_ref in nodes, 'unresolved root reference')
    atoms = {atom.id: atom for atom in expected_context.propositions}
    domains = {domain.id: domain for domain in expected_context.domains}
    dependents = {ref: set() for ref in nodes}; pending = {}
    atom_refs = []
    for ref, node in nodes.items():
        require(isinstance(node.truth, Truth) and type(node.decision_proven) is bool,
                'invalid node truth/proven fields')
        require(isinstance(node.coverage, ScopeCoverage), 'invalid node coverage')
        spec = node.spec
        require(set(spec.children) <= nodes.keys(), 'unresolved child reference')
        if spec.operator == Operator.ATOM:
            require(not spec.children and spec.proposition_ref in atoms, 'invalid atom reference')
            atom_refs.append(spec.proposition_ref)
        else:
            require(not spec.proposition_ref, 'compound node cannot substitute an atom')
            require(spec.operator != Operator.NOT or len(spec.children) == 1, 'invalid not arity')
            require(spec.operator != Operator.CONDITIONAL or len(spec.children) == 2, 'invalid conditional arity')
        pending[ref] = len(set(spec.children))
        for child in spec.children: dependents[child].add(ref)
    require(len(atom_refs) == len(set(atom_refs)) and set(atom_refs) == atoms.keys(),
            'propositions omitted, duplicated, or substituted')
    queue = deque(sorted(ref for ref in nodes if pending[ref] == 0))
    processed, heights = set(), {}
    while queue:
        ref = queue.popleft(); node = nodes[ref]; spec = node.spec
        children = [nodes[child] for child in spec.children]
        if spec.operator == Operator.ATOM:
            atom = atoms[spec.proposition_ref]; truth = atom.truth; domain_refs = set(atom.domain_refs)
        else:
            truth = _truth(spec.operator, [child.truth for child in children])
            domain_refs = {domain for child in children for domain in (*child.coverage.closed_domains, *child.coverage.open_domains)}
        require(node.truth == truth, 'stored truth contradicts recomputation')
        proven = truth != Truth.UNKNOWN
        require(node.decision_proven == proven and node.proof_ref == (ref if proven else None),
                'invalid decision proof for truth')
        refs = node.sufficient_witness_refs
        require(isinstance(refs, tuple) and all(isinstance(value, str) for value in refs) and
                len(set(refs)) == len(refs) and set(refs) <= set(spec.children), 'invalid witness reference')
        if not proven or spec.operator == Operator.ATOM:
            require(not refs, 'unknown/atom cannot have child witnesses')
        elif spec.operator == Operator.CONDITIONAL:
            require((set(refs) == set(spec.children) if truth == Truth.FALSE else
                     bool(refs) and all((child == spec.children[0] and nodes[child].truth == Truth.FALSE) or
                                        (child == spec.children[1] and nodes[child].truth == Truth.TRUE)
                                        for child in refs)), 'insufficient conditional witnesses')
        elif spec.operator == Operator.ALL and truth == Truth.FALSE or spec.operator == Operator.ANY and truth == Truth.TRUE:
            require(bool(refs) and all(nodes[child].truth == truth for child in refs), 'insufficient decisive witnesses')
        else:
            require(set(refs) == set(spec.children), 'all child witnesses required')
        require(all(nodes[child].decision_proven for child in refs), 'witness is not proven')
        expected_coverage = ScopeCoverage(expected_context.scope_ref,
            tuple(domain for domain in domain_refs if domains[domain].closed),
            tuple(domain for domain in domain_refs if not domains[domain].closed))
        require(node.coverage == expected_coverage, 'scope coverage omitted or changed')
        heights[ref] = 1 + max((heights[child] for child in spec.children), default=0)
        require(heights[ref] <= max_depth, 'proof depth limit')
        processed.add(ref)
        for parent in sorted(dependents[ref]):
            pending[parent] -= 1
            if pending[parent] == 0: queue.append(parent)
    require(processed == nodes.keys(), 'proof cycle')
    reachable, remaining = set(), [result.root_ref]
    while remaining:
        ref = remaining.pop()
        if ref not in reachable:
            reachable.add(ref); remaining.extend(nodes[ref].spec.children)
    require(reachable == nodes.keys(), 'unreachable proof nodes')
    root = nodes[result.root_ref]
    require(set((*root.coverage.closed_domains, *root.coverage.open_domains)) == domains.keys(),
            'declared scope omitted from root coverage')
    return result
