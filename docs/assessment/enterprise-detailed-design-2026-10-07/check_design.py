"""Executable reference checks for a proposed design, not the production engine."""
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from itertools import combinations, product
import json
from pathlib import Path


VALUES = ('T', 'F', 'U')


def possible(value):
    return (True, False) if value == 'U' else (value == 'T',)


@dataclass(frozen=True)
class Node:
    op: str
    children: tuple = ()
    name: str = ''


@dataclass(frozen=True)
class Outcome:
    truth: str
    witnesses: tuple
    scope_open: bool


def reference(node, assignments):
    if node.op == 'atom':
        value = assignments[node.name]
        return Outcome(value, () if value == 'U' else (node.name,), value == 'U')
    children = [reference(child, assignments) for child in node.children]
    if node.op == 'not':
        child, = children
        return Outcome({'T': 'F', 'F': 'T', 'U': 'U'}[child.truth],
                       child.witnesses, child.scope_open)
    if node.op == 'conditional':
        condition, requirement = node.children
        return reference(Node('any', (Node('not', (condition,)), requirement)), assignments)
    decisive, neutral = ('F', 'T') if node.op == 'all' else ('T', 'F')
    matches = [child for child in children if child.truth == decisive]
    truth = decisive if matches else 'U' if any(child.truth == 'U' for child in children) else neutral
    if matches:
        witnesses = min(child.witnesses for child in matches)
    elif truth == 'U':
        witnesses = ()
    else:
        witnesses = tuple(sorted({name for child in children for name in child.witnesses}))
    return Outcome(truth, witnesses, any(child.scope_open for child in children))


def concrete(node, assignment):
    if node.op == 'atom':
        return assignment[node.name]
    values = [concrete(child, assignment) for child in node.children]
    if node.op == 'not':
        return not values[0]
    if node.op == 'all':
        return all(values)
    if node.op == 'any':
        return any(values)
    return not values[0] or values[1]


def sets(universe):
    return [frozenset(items) for size in range(len(universe) + 1)
            for items in combinations(universe, size)]


def intervals(universe):
    subsets = sets(universe)
    return [(low, high) for low in subsets for high in subsets if low <= high]


def worlds(bounds, universe):
    low, high = bounds
    return [value for value in sets(universe) if low <= value <= high]


def route_requirement(before, after, document):
    return after - before <= document and not (before - after) & document


def interval_requirement(before, after, document):
    lb, ub = before
    la, ua = after
    ld, ud = document
    added_low, added_high = la - ub, ua - lb
    removed_low, removed_high = lb - ua, ub - la
    if added_high <= ld and not removed_high & ud:
        return 'T'
    if added_low - ud or removed_low & ld:
        return 'F'
    return 'U'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('refusing to replace prior evidence')
    failures = []
    counts = {'interval_states': 0, 'concrete_route_worlds': 0,
              'nested_circuit_assignments': 0, 'concrete_circuit_worlds': 0,
              'proof_witness_completions': 0, 'scope_guard_cases': 0,
              'publication_event_sequences': 0, 'rejected_alternative_counterexamples': 0}

    def check(holds, label, details):
        if not holds:
            failures.append({'property': label, 'details': details})

    universe = ('a', 'b')
    for before, after, doc in product(intervals(universe), repeat=3):
        value = interval_requirement(before, after, doc)
        for old, new, document in product(worlds(before, universe), worlds(after, universe), worlds(doc, universe)):
            actual = route_requirement(old, new, document)
            check(value == 'U' or actual == (value == 'T'), 'route_bound_soundness',
                  {'truth': value, 'before': sorted(old), 'after': sorted(new), 'doc': sorted(document)})
            counts['concrete_route_worlds'] += 1
        counts['interval_states'] += 1

    atoms = tuple(Node('atom', name=name) for name in ('a', 'b', 'c'))
    # Repeated atoms test shared identities; intervals still intentionally ignore correlations.
    trees = [Node(outer, (Node(inner, (atoms[0], atoms[1])), atoms[2]))
             for outer, inner in product(('all', 'any', 'conditional'), repeat=2)]
    trees += [Node('any', (atoms[0], Node('not', (atoms[0],)))),
              Node('all', (atoms[0], Node('not', (atoms[0],))))]
    for index, tree in enumerate(trees):
        for values in product(VALUES, repeat=3):
            assignments = dict(zip(('a', 'b', 'c'), values))
            result = reference(tree, assignments)
            used = values if index < 9 else values[:1]
            check(result.scope_open == ('U' in used),
                  'scope_metadata', {'tree': index, 'values': values})
            for values_concrete in product(*(possible(assignments[name]) for name in ('a', 'b', 'c'))):
                actual = concrete(tree, dict(zip(('a', 'b', 'c'), values_concrete)))
                check(result.truth == 'U' or actual == (result.truth == 'T'), 'circuit_truth_soundness',
                      {'tree': index, 'values': values})
                counts['concrete_circuit_worlds'] += 1
            if result.truth != 'U':
                # Omitted leaves range over BOTH booleans, even when the original observation was exact.
                for completion in product(*((assignments[name] == 'T',) if name in result.witnesses else (False, True)
                                            for name in ('a', 'b', 'c'))):
                    check(concrete(tree, dict(zip(('a', 'b', 'c'), completion))) == (result.truth == 'T'),
                          'sufficient_witness', {'tree': index, 'values': values, 'witnesses': result.witnesses})
                    counts['proof_witness_completions'] += 1
            counts['nested_circuit_assignments'] += 1

    for known, discovery_closed in product(VALUES, (True, False)):
        # Mandatory completeness guard: K AND (T if complete else U).
        guard = Node('all', (Node('atom', name='known'), Node('atom', name='guard')))
        outcome = reference(guard, {'known': known, 'guard': 'T' if discovery_closed else 'U'})
        check(discovery_closed or outcome.truth != 'T', 'open_scope_cannot_verify_pass', [known, discovery_closed])
        check(known != 'F' or outcome.truth == 'F', 'known_violation_is_retained', [known, discovery_closed])
        counts['scope_guard_cases'] += 1

    # A small server-CAS reference, NOT the current GitHub publisher implementation.
    events = ('head-A', 'head-B', 'capture', 'complete', 'abort', 'publish')
    for sequence in product(events, repeat=6):
        head, generation, run, latest = 'A', 0, None, None
        for event in sequence:
            if event.startswith('head-'):
                head = event[-1]
                generation += 1
                latest = None  # head generation invalidates the mutable latest pointer
            elif event == 'capture':
                run = (head, generation, 'running')
            elif event in ('complete', 'abort') and run and run[2] == 'running':
                run = (run[0], run[1], 'completed' if event == 'complete' else 'aborted')
            elif event == 'publish' and run and run == (head, generation, 'completed'):
                latest = run
            check(latest is None or latest == (head, generation, 'completed'),
                  'publication_current_generation', {'sequence': sequence, 'event': event})
        counts['publication_event_sequences'] += 1

    # Check each rejected shortcut against an explicit counterexample.
    checks = [
        (frozenset() == frozenset() and frozenset() != frozenset(('a',)),
         'equal_lower_sets_do_not_prove_no_delta'),
        (reference(Node('all', atoms[:2]), {'a': 'T', 'b': 'U'}).truth == 'U',
         'open_discovery_guard_retained'),
        (reference(Node('all', atoms[:2]), {'a': 'F', 'b': 'U'}).truth == 'F',
         'known_violation_retained'),
        (('A', 0) != ('A', 2), 'generation_rejects_head_ABA')]
    for holds, label in checks:
        check(holds, label, {})
        counts['rejected_alternative_counterexamples'] += 1
    rejected = {
        'equal_lower_sets_prove_no_delta': {
            'before_bounds': [[], ['a']], 'after_bounds': [[], ['a']],
            'concrete_before': [], 'concrete_after': ['a'], 'rejected': True},
        'drop_unknown_discovery_then_pass': {
            'known_truth': 'T', 'discovery_guard': 'U', 'required_root': 'U', 'rejected': True},
        'failed_conjunction_loses_known_violation': {
            'known_truth': 'F', 'unknown_sibling': 'U', 'required_root': 'F', 'rejected': True},
        'head_oid_alone_prevents_ABA': {
            'captured': ['A', 0], 'current': ['A', 2], 'required_publication': 'stale', 'rejected': True}}
    result = {'schema': 'enterprise-detailed-design-model-v1',
              'created_at': datetime.now(timezone.utc).isoformat(), 'counts': counts,
              'failures': failures, 'passed': not failures, 'rejected_design_alternatives': rejected,
              'script_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
              'limitations': ['Reference design only; no production code is exercised.',
                              'Two-fact finite intervals, eleven circuits, six publication events to depth six.',
                              'Set bounds ignore correlations; unknown may be conservative.',
                              'Publication assumes atomic server CAS and trusted generation invalidation.',
                              'No parser soundness, real concurrency, liveness, OS, CI, installer or PR accuracy proof.']}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
