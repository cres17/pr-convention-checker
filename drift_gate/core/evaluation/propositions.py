"""Strong Kleene evaluation and deterministic sufficient witnesses."""
from drift_gate.core.contracts.planner import Truth
from drift_gate.core.models.proof import Operator, ProofEvaluation, ProofNode, ScopeCoverage


def negate(value):
    return {Truth.TRUE: Truth.FALSE, Truth.FALSE: Truth.TRUE, Truth.UNKNOWN: Truth.UNKNOWN}[value]


def combine(operator, values):
    if operator == Operator.NOT:
        return negate(values[0])
    if operator == Operator.CONDITIONAL:
        return combine(Operator.ANY, (negate(values[0]), values[1]))
    decisive = Truth.FALSE if operator == Operator.ALL else Truth.TRUE
    if decisive in values:
        return decisive
    if Truth.UNKNOWN in values:
        return Truth.UNKNOWN
    return Truth.TRUE if operator == Operator.ALL else Truth.FALSE


def witnesses(operator, children, truth):
    if truth == Truth.UNKNOWN:
        return ()
    if operator == Operator.CONDITIONAL:
        if truth == Truth.FALSE:
            return tuple(sorted({child.id for child in children}))
        candidates = [child.id for index, child in enumerate(children)
                      if child.truth == (Truth.FALSE if index == 0 else Truth.TRUE)]
        return (min(candidates),)
    decisive = (operator == Operator.ALL and truth == Truth.FALSE or
                operator == Operator.ANY and truth == Truth.TRUE)
    return (min(child.id for child in children if child.truth == truth),) if decisive else tuple(sorted({child.id for child in children}))


def build_proof(context, specs, root_ref, *, max_nodes=4096, max_depth=128, max_edges=16384):
    """Bounded construction. The independent guard validates the finished IR."""
    from drift_gate.core.evaluation.result_guard import ResultValidationError, validate_context
    validate_context(context)
    specs = tuple(specs)
    if (type(max_nodes) is not int or max_nodes < 1 or type(max_depth) is not int or not 1 <= max_depth <= 128 or
        type(max_edges) is not int or max_edges < 0):
        raise ResultValidationError('invalid proof limits')
    if not specs or len(specs) > max_nodes:
        raise ResultValidationError('proof node limit or empty proof')
    if sum(len(spec.children) for spec in specs) > max_edges:
        raise ResultValidationError('proof edge limit')
    by_id = {spec.id: spec for spec in specs}
    if len(by_id) != len(specs):
        raise ResultValidationError('duplicate node ID')
    atoms = {atom.id: atom for atom in context.propositions}
    domains = {domain.id: domain for domain in context.domains}
    built, visiting, heights = {}, set(), {}

    def visit(ref, depth):
        if depth > max_depth or ref in visiting:
            raise ResultValidationError('proof depth limit or cycle')
        if ref in built:
            if depth + heights[ref] - 1 > max_depth:
                raise ResultValidationError('proof depth limit')
            return built[ref]
        if ref not in by_id:
            raise ResultValidationError('unresolved child reference')
        spec = by_id[ref]; visiting.add(ref)
        if spec.operator == Operator.ATOM:
            if spec.children or spec.proposition_ref not in atoms:
                raise ResultValidationError('invalid atom reference')
            atom = atoms[spec.proposition_ref]
            truth, refs, witness = atom.truth, set(atom.domain_refs), ()
        else:
            if (spec.proposition_ref or spec.operator == Operator.NOT and len(spec.children) != 1 or
                spec.operator == Operator.CONDITIONAL and len(spec.children) != 2):
                raise ResultValidationError('invalid operator arity')
            children = [visit(child, depth + 1) for child in spec.children]
            truth = combine(spec.operator, [child.truth for child in children])
            witness = witnesses(spec.operator, children, truth)
            refs = {domain for child in children for domain in (*child.coverage.closed_domains, *child.coverage.open_domains)}
        coverage = ScopeCoverage(context.scope_ref, tuple(ref for ref in refs if domains[ref].closed),
                                 tuple(ref for ref in refs if not domains[ref].closed))
        node = ProofNode(spec, truth, truth != Truth.UNKNOWN, ref if truth != Truth.UNKNOWN else None, witness, coverage)
        built[ref] = node; visiting.remove(ref)
        heights[ref] = 1 + max((heights[child] for child in spec.children), default=0)
        return node

    visit(root_ref, 1)
    if set(built) != set(by_id):
        raise ResultValidationError('unreachable proof nodes')
    return ProofEvaluation(context.ref, root_ref, tuple(built.values()))
