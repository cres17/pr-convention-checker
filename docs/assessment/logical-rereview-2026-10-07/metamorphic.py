"""Exhaustive finite-state logic and frozen counterexample replay; never overwrite."""
import argparse
from copy import deepcopy
from itertools import permutations, product
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from drift_gate.core.evaluation.content_result import ContentCheck, combine
from reproduce import reproduce


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Output already exists')
    base = Path(__file__).parent
    cases = json.loads((base / 'final-cases.json').read_text())
    values = [ContentCheck('satisfied', 'verified', 'true', 'test'),
              ContentCheck('violated', 'verified', 'false', 'test'),
              ContentCheck('undetermined', 'unverified', 'unknown', 'test'),
              ContentCheck('violated', 'partial', 'partial-false', 'test')]
    finite_states, permutations_checked = 0, 0
    for require_all in [False, True]:
        for inputs in product(values, repeat=4):
            # Oracle is a truth table, independently expressed as truth values.
            truths = [True if c.decision == 'satisfied' else False if c.decision == 'violated' else None for c in inputs]
            if require_all:
                expected = 'violated' if False in truths else 'undetermined' if None in truths else 'satisfied'
            else:
                expected = 'satisfied' if True in truths else 'undetermined' if None in truths else 'violated'
            if expected == 'undetermined':
                coverage = 'unverified'
            elif not require_all and expected == 'satisfied':
                coverage = 'verified'  # complete witness in this finite domain
            else:
                coverage = 'partial' if any(c.verification in {'partial', 'unverified'} for c in inputs) else 'verified'
            baseline = combine(inputs, require_all=require_all, mode='test')
            assert (baseline.decision, baseline.verification) == (expected, coverage)
            finite_states += 1
            for order in permutations(inputs):
                assert combine(order, require_all=require_all, mode='test') == baseline
                permutations_checked += 1
    seeds = []
    for seed in range(1, 9):
        output = args.out.with_name(f'after-seed{seed}.json')
        subprocess.run([sys.executable, str(base / 'reproduce.py'), '--cases', str(base / 'final-cases.json'), '--out', str(output)],
                       check=True, env={**os.environ, 'PYTHONHASHSEED': str(seed)})
        data = json.loads(output.read_text())
        assert data['matched'] == data['total'] == len(cases)
        seeds.append({'seed': seed, 'matched': data['matched'], 'total': data['total']})
    policy_pairs, file_orderings = 0, 0
    for case in cases:
        weak = deepcopy(case); weak['policy']['gate']['on_unverified'] = 'warn'
        strong = deepcopy(case); strong['policy']['gate']['on_unverified'] = 'fail'
        a, b = reproduce([weak])[0]['actual'], reproduce([strong])[0]['actual']
        rank = {'pass': 0, 'warn': 1, 'fail': 2}
        assert rank[b['gate']] >= rank[a['gate']]
        assert {k:v for k,v in a.items() if k != 'gate'} == {k:v for k,v in b.items() if k != 'gate'}
        policy_pairs += 1
        for order in permutations(case['files']):
            variant = deepcopy(case); variant['files'] = list(order)
            assert reproduce([variant])[0]['actual'] == reproduce([case])[0]['actual']
            file_orderings += 1
    with args.out.open('x', encoding='utf-8') as handle:
        json.dump({'finite_states': finite_states, 'permutation_checks': permutations_checked,
                   'hash_seeds': seeds, 'policy_strengthening_pairs': policy_pairs,
                   'file_orderings': file_orderings, 'all_matched': True}, handle, indent=2)
        handle.write('\n')


if __name__ == '__main__':
    main()
