"""Finite checks of the proposed algebra, not a proof of parser soundness."""
import argparse
from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from drift_gate.core.evaluation.content_result import ContentCheck, combine

VALUES = ('T', 'F', 'U')
DECISIONS = {'T': 'satisfied', 'F': 'violated', 'U': 'undetermined'}


def land(a, b):
    return 'F' if 'F' in (a, b) else 'U' if 'U' in (a, b) else 'T'


def lor(a, b):
    return 'T' if 'T' in (a, b) else 'U' if 'U' in (a, b) else 'F'


def lnot(a):
    return {'T': 'F', 'F': 'T', 'U': 'U'}[a]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('refusing to replace existing evidence')
    counts = {'production_binary_truth_table': 0, 'logical_laws': 0,
              'conditional_table': 0, 'abstract_delta_concrete_pairs': 0,
              'no_delta_sufficiency_pairs': 0}
    failures = []

    def check(ok, label, detail):
        if not ok:
            failures.append({'property': label, 'detail': detail})

    for a, b in itertools.product(VALUES, repeat=2):
        inputs = [ContentCheck(DECISIONS[x], 'unverified' if x == 'U' else 'verified', x, 'model') for x in (a, b)]
        for operator, required in [(land, True), (lor, False)]:
            actual = combine(inputs, require_all=required, mode='model').decision
            check(actual == DECISIONS[operator(a, b)], 'production_truth', [a, b, required, actual])
            counts['production_binary_truth_table'] += 1

    for a, b, c in itertools.product(VALUES, repeat=3):
        laws = [land(a, b) == land(b, a), lor(a, b) == lor(b, a),
                land(land(a, b), c) == land(a, land(b, c)),
                lor(lor(a, b), c) == lor(a, lor(b, c)),
                lnot(land(a, b)) == lor(lnot(a), lnot(b)),
                lnot(lor(a, b)) == land(lnot(a), lnot(b)),
                land(a, lor(b, c)) == lor(land(a, b), land(a, c)),
                lor(a, land(b, c)) == land(lor(a, b), lor(a, c))]
        for index, holds in enumerate(laws):
            check(holds, f'logical_law_{index}', [a, b, c])
            counts['logical_laws'] += 1

    expected = {('F', 'T'): 'T', ('F', 'F'): 'T', ('F', 'U'): 'T',
                ('T', 'T'): 'T', ('T', 'F'): 'F', ('T', 'U'): 'U',
                ('U', 'T'): 'T', ('U', 'F'): 'U', ('U', 'U'): 'U'}
    for (applicable, requirement), truth in expected.items():
        check(lor(lnot(applicable), requirement) == truth, 'conditional_table', [applicable, requirement])
        counts['conditional_table'] += 1

    universe = frozenset(('a', 'b', 'c'))
    subsets = [frozenset(items) for size in range(4) for items in itertools.combinations(sorted(universe), size)]
    # Every possible L subset concrete F subset U over a three-fact universe.
    states = [(low, concrete, high) for low in subsets for concrete in subsets for high in subsets
              if low <= concrete <= high]
    for (lb, before, ub), (la, after, ua) in itertools.product(states, repeat=2):
        lower_added, upper_added = la - ub, ua - lb
        lower_removed, upper_removed = lb - ua, ub - la
        added, removed = after - before, before - after
        check(lower_added <= added <= upper_added and lower_removed <= removed <= upper_removed,
              'sound_delta_bounds', {'before': sorted(before), 'after': sorted(after)})
        counts['abstract_delta_concrete_pairs'] += 1
        if not upper_added and not upper_removed:
            check(before == after, 'no_delta_sufficient', {'before': sorted(before), 'after': sorted(after)})
            counts['no_delta_sufficiency_pairs'] += 1

    result = {'schema': 'enterprise-finite-model-v1', 'created_at': datetime.now(timezone.utc).isoformat(),
              'counts': counts, 'failures': failures, 'passed': not failures,
              'limits': ['Finite model universe has three facts; delta bounds are proposed, not implemented in current analyzers.',
                         'Current combine decision checked for two operands only; evidence coverage is not proved by this script.',
                         'No parser soundness, scope completeness, source collection, temporal/liveness or TLA+ claim.'],
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'production_combine_sha256': hashlib.sha256((ROOT / 'drift_gate/core/evaluation/content_result.py').read_bytes()).hexdigest()}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
