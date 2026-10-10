"""Adversarial logical boundaries; expectations are independent of gate defaults."""
from itertools import permutations, product
import json
from pathlib import Path

import pytest

from drift_gate.core.engine import run
from drift_gate.core.evaluation.api_schema import _document_check, extract_responses, UnsupportedContract
from drift_gate.core.evaluation.content_result import combine, checked, unknown, ContentCheck
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.policy.loader import load_policy_from_dict

CASES = json.loads((Path(__file__).with_name('contracts') / 'logical-rereview.json').read_text())


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['id'])
def test_reproduced_adversarial_contract(case):
    files = []
    for data in case['files']:
        file = ChangedFile.from_dict(data)
        file.before_source, file.after_source = data['before_source'], data['after_source']
        files.append(file)
    result = run(files, policy=load_policy_from_dict(case['policy'])).to_dict()
    assert {'gate': result['result'], 'decision': result['rule_decisions'][0]['decision'],
            'verification': result['verification'], 'violations': len(result['violations'])} == case['expected']


def test_document_contract_order_preserves_known_failure_and_unknown():
    expected = {'id': {'type': 'integer', 'required': True}}
    doc = {'openapi': '3.1.0', 'paths': {'/unknown': {'$ref': './external.json'}}}
    delta = {('GET', '/missing'): expected, ('GET', '/unknown'): expected}
    outcomes = [_document_check(json.dumps(doc), dict(order)) for order in permutations(delta.items())]
    assert outcomes[0] == outcomes[1]
    assert outcomes[0].decision == 'violated'
    assert outcomes[0].verification == 'partial'
    assert '/missing' in outcomes[0].reason and '/unknown' in outcomes[0].reason


@pytest.mark.parametrize('all_required', [False, True])
def test_three_valued_truth_table_and_permutation_invariance(all_required):
    values = [checked(True, 'yes', 'test'), checked(False, 'no', 'test'), unknown('unknown', 'test')]
    for checks in product(values, repeat=3):
        decisions = [c.decision for c in checks]
        decisive = 'violated' if all_required else 'satisfied'
        expected = decisive if decisive in decisions else ('undetermined' if 'undetermined' in decisions else 'satisfied' if all_required else 'violated')
        actual = combine(checks, require_all=all_required, mode='test')
        assert actual.decision == expected
        for ordering in permutations(checks):
            assert combine(ordering, require_all=all_required, mode='test') == actual


@pytest.mark.parametrize('all_required', [False, True])
def test_singleton_aggregation_preserves_partial_evidence(all_required):
    partial = ContentCheck('violated', 'partial', 'known mismatch; other contract unavailable', 'test')
    assert combine([partial], require_all=all_required, mode='test') == partial


def test_complete_alternative_proves_disjunction_despite_partial_other():
    partial = ContentCheck('violated', 'partial', 'incomplete', 'test')
    complete = checked(True, 'complete witness', 'test')
    assert combine([partial, complete], require_all=False, mode='test') == complete


def test_primitive_field_name_cannot_shadow_annotation_resolution():
    source = "from fastapi import FastAPI\nfrom pydantic import BaseModel\napp = FastAPI()\nclass Item(BaseModel):\n    int: str = 'wrong'\n    value: int\n@app.get('/items', response_model=Item)\ndef items(): pass\n"
    with pytest.raises(UnsupportedContract, match='shadowing'):
        extract_responses(source)
