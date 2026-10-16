"""Focused-plan regressions: value semantics, finite schemas and honest metrics."""
from copy import deepcopy
from decimal import Decimal, localcontext
import json

import pytest

from drift_gate.adapters import holdout
from drift_gate.adapters.inspection import inspect
from drift_gate.core import evaluation_stats as stats
from drift_gate.core.contracts.planner import Truth
from drift_gate.core.evaluation import json_values
from drift_gate.core.evaluation.compatibility import Unsupported, admits, compare_documents, normalize, subset
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.policy.loader import load_policy_from_dict


def document(schema):
    return {'openapi': '3.1.0', 'paths': {'/x': {'get': {'responses': {'200': {
        'description': 'result', 'content': {'application/json': {'schema': schema}}}}}}}}


COMPATIBILITY = {'rules': [{'id': 'compat', 'when': {'any_changed': ['openapi.json']},
    'require': {'groups': [{'name': 'compatible', 'any_changed': ['openapi.json'],
                           'content': 'api-compatibility', 'direction': 'response'}]}, 'severity': 'blocker'}]}


@pytest.mark.parametrize('old,new,witness', [
    ({'oneOf': [{'enum': [1]}, {'enum': [1.0]}]}, {'enum': [1]}, 1),
    ({'type': 'string'}, {'type': 'integer', 'enum': [1.0]}, 1.0),
    ({'enum': [True]}, {'enum': [1]}, 1),
    ({'enum': [{'x': [1.1]}]}, {'enum': [{'x': [1]}]}, {'x': [1]}),
])
def test_numeric_counterexamples_are_confirmed_through_product_inspection(old, new, witness):
    validator = pytest.importorskip('jsonschema').Draft202012Validator
    assert validator(new).is_valid(witness) and not validator(old).is_valid(witness)
    assert compare_documents(document(old), document(new), 'response').truth == Truth.FALSE
    before, after = json.dumps(document(old)), json.dumps(document(new))
    result = inspect(changed_files=[ChangedFile('openapi.json', 'modified',
        patch=f'@@ -1 +1 @@\n-{before}\n+{after}\n', before_source=before, after_source=after)],
        policy=load_policy_from_dict(COMPATIBILITY))
    assert result.result == 'fail' and result.rule_decisions[0].decision == 'violated'


@pytest.mark.parametrize('old,new', [
    ({'enum': [1]}, {'enum': [1.0]}),
    ({'enum': [{'x': [1, -0.0]}]}, {'enum': [{'x': [1.0, 0]}]}),
    ({'enum': [{}]}, {'type': 'object', 'additionalProperties': False}),
    ({'enum': [{}, {'x': True}, {'x': False}]},
     {'type': 'object', 'properties': {'x': {'type': 'boolean'}}, 'additionalProperties': False}),
    ({'enum': [[]]}, {'type': 'array', 'items': False}),
    ({'enum': [{}]}, {'type': 'object', 'additionalProperties': {'type': 'integer', 'enum': ['impossible']}}),
])
def test_finite_equivalent_schemas_remain_decidable(old, new):
    assert compare_documents(document(old), document(new), 'response').truth == Truth.TRUE
    assert compare_documents(document(new), document(old), 'response').truth == Truth.TRUE


@pytest.mark.parametrize('value,kind', [(1.0, 'integer'), (-3.0, 'integer'), (-0.0, 'integer'),
    (1.5, 'number'), (True, 'boolean'), (False, 'boolean'), (2**70, 'integer')])
def test_json_types_and_independent_numeric_validator(value, kind):
    validator = pytest.importorskip('jsonschema').Draft202012Validator
    assert json_values.value_type(value) == kind
    for name in ('integer', 'number', 'boolean'):
        assert (admits(normalize({'type': name}, {}), value) == Truth.TRUE) == validator({'type': name}).is_valid(value)


def test_decimal_tokens_keep_precision_and_ignore_decimal_context():
    a = json_values.decode('9007199254740993.0')
    b = json_values.decode('9007199254740992.0')
    assert json_values.canonical(a) != json_values.canonical(b)
    with localcontext() as context:
        context.prec = 2
        assert json_values.canonical(Decimal('123456789.00')) == '123456789'
    assert json_values.canonical(Decimal('1e100000')) == '1e100000'
    assert json_values.value_type(Decimal('1e-100000')) == 'number'
    old = json.dumps(document({'enum': [9007199254740992]}))
    new = json.dumps(document({'enum': [9007199254740993]})).replace('9007199254740993', '9007199254740993.0')
    result = inspect(changed_files=[ChangedFile('openapi.json', 'modified', patch='@@\n-x\n+y\n',
        before_source=old, after_source=new)], policy=load_policy_from_dict(COMPATIBILITY))
    assert result.result == 'fail'


@pytest.mark.parametrize('token', ['NaN', 'Infinity', '-Infinity'])
def test_nonfinite_schema_numbers_are_unverified_not_compatible(token):
    with pytest.raises(ValueError, match='non-finite'):
        json_values.decode(token)
    with pytest.raises(Unsupported, match='non-finite'):
        normalize({'enum': [float(token)]}, {})
    before = json.dumps(document({'enum': [1]}))
    after = before.replace('[1]', f'[{token}]')
    result = inspect(changed_files=[ChangedFile('openapi.json', 'modified', patch='@@\n-x\n+y\n',
        before_source=before, after_source=after)], policy=load_policy_from_dict(COMPATIBILITY))
    assert result.rule_decisions[0].decision == 'undetermined'


def test_finite_enumeration_cap_never_manufactures_a_counterexample():
    schema = {'type': 'object', 'additionalProperties': False,
              'properties': {f'p{i}': {'type': 'boolean'} for i in range(8)}}
    witnesses = []
    assert subset(normalize(schema, {}), normalize({'enum': [{}]}, {}), '$', witnesses) == Truth.UNKNOWN
    assert not witnesses
    assert subset(normalize({'type': 'array', 'items': {'type': 'boolean'}}, {}),
                  normalize({'enum': [[]]}, {}), '$', []) == Truth.UNKNOWN


def test_empty_required_property_language_never_causes_a_false_break():
    empty = {'type': 'object', 'properties': {'x': False}, 'required': ['x']}
    assert subset(normalize(empty, {}), normalize({'type': 'integer'}, {}), '$', []) == Truth.TRUE
    optional = {'type': 'object', 'properties': {'x': False}}
    without_x = {'type': 'object', 'additionalProperties': True, 'properties': {'x': False}}
    assert subset(normalize(optional, {}), normalize(without_x, {}), '$', []) == Truth.TRUE
    empty_extra = {'type': 'object', 'properties': {'x': {'type': 'string'}},
                   'additionalProperties': {'type': 'integer', 'enum': ['impossible']}}
    closed = {'type': 'object', 'properties': {'x': {'type': 'string'}}, 'additionalProperties': False}
    assert subset(normalize(empty_extra, {}), normalize(closed, {}), '$', []) == Truth.TRUE


def test_numeric_and_finite_boundary_grid_against_independent_jsonschema():
    validator = pytest.importorskip('jsonschema').Draft202012Validator
    scalars = [None, True, False, -1, -1.0, -0.0, 0, 1, 1.0, 1.5, 2, 'x', 'outside']
    values = scalars + [[value] for value in scalars] + [[], {}, {'x': 1}, {'x': 1.0}, {'x': True}, {'x': False}, {'extra': 42}]
    schemas = [{'type': name} for name in ('integer', 'number', 'boolean', 'null', 'string', 'object', 'array')]
    schemas += [{'enum': [value]} for value in values]
    schemas += [{'oneOf': [{'enum': [1]}, {'enum': [1.0]}]},
                {'anyOf': [{'enum': [1]}, {'enum': [1.0]}]},
                {'type': 'object', 'additionalProperties': False},
                {'type': 'object', 'properties': {'x': {'type': 'boolean'}}, 'additionalProperties': False},
                {'type': 'object', 'properties': {'x': False}, 'required': ['x']},
                {'type': 'array', 'items': False},
                {'allOf': [{'type': 'number'}, {'type': 'integer'}]}]
    # Fixed boundary families, not a claim about unobserved production schemas.
    checks = [validator(schema) for schema in schemas]
    membership = [[check.is_valid(value) for value in values] for check in checks]
    nodes = [normalize(schema, {}) for schema in schemas]
    for i, left in enumerate(nodes):
        for j, right in enumerate(nodes):
            result = subset(left, right, '$', [])
            counterexamples = [value for k, value in enumerate(values) if membership[i][k] and not membership[j][k]]
            if result == Truth.TRUE:
                assert not counterexamples, (schemas[i], schemas[j], counterexamples)
            elif result == Truth.FALSE:
                assert counterexamples, (schemas[i], schemas[j])


def partial_case():
    return {'case_id': 'one', 'repository': 'fixture/repo', 'source_family': 'one',
        'policy': {'rules': [
            {'id': 'visible', 'when': {'any_changed': ['src/**']}, 'require': {'groups': [
                {'name': 'ok', 'any_changed': ['docs/ok.md']}]}, 'severity': 'blocker'},
            {'id': 'omitted', 'when': {'any_changed': ['src/**']}, 'require': {'groups': [
                {'name': 'missing', 'any_changed': ['docs/missing.md']}]}, 'severity': 'blocker'}]},
        'changed_files': [{'path': 'src/a.py', 'status': 'modified', 'patch': '@@\n-x=1\n+x=2\n',
                          'before_source': 'x=1\n', 'after_source': 'x=2\n'},
                         {'path': 'docs/ok.md', 'status': 'modified', 'patch': '@@\n+updated\n', 'after_source': 'updated\n'}],
        'expected': {'gate': 'fail', 'rules': {'visible': {'decision': 'satisfied', 'support': 'supported'}}}}


def test_expectations_do_not_select_holdout_denominator_or_review_items():
    frozen = holdout.freeze({'schema': holdout.CASES, 'split': 'holdout', 'cases': [partial_case()]}, protocol='focused')
    result = holdout.run_frozen(frozen, holdout.artifact_sha256(frozen))
    units = {unit['rule_id']: unit for unit in result['units']}
    assert set(units) == {'visible', 'omitted'} and units['omitted']['decision'] == 'violated'
    assert units['omitted']['expected_decision'] is None and units['omitted']['expected_support'] is None
    packet = holdout.review_packet(frozen, instructions='test fixture, not independent human evaluation')
    assert {item['item_id'] for item in packet['items']} == {'one::visible', 'one::omitted', 'one::pr-action'}
    labels = holdout.adjudicate(packet, [{'item_id': 'one::visible', 'reviewer_id': 'synthetic',
                                       'reviewer_kind': 'llm-proxy', 'label': 'satisfied'}])
    metrics = holdout.score_all(result, labels)
    scored = metrics['by_label_source']['llm-proxy']['obligations']
    assert scored['units_total'] == 2 and scored['units_unlabelled'] == ['one::omitted']
    assert scored['engine_outcomes_total'] == {'satisfied': 1, 'violated': 1}
    assert metrics['units_without_frozen_expectation'] == 1
    assert metrics['frozen_expectation_agreement']['denominator'] == 1


def test_holdout_rejects_expectations_for_nonexistent_rules():
    case = deepcopy(partial_case())
    case['expected']['rules']['typo'] = {'decision': 'satisfied', 'support': 'supported'}
    with pytest.raises(holdout.HoldoutError, match='not in policy'):
        holdout.freeze({'schema': holdout.CASES, 'split': 'holdout', 'cases': [case]}, protocol='test')


@pytest.mark.parametrize('decision', stats.DECISIONS)
@pytest.mark.parametrize('label', stats.LABELS)
def test_every_decision_label_pair_has_an_explicit_false_verified_contract(decision, label):
    # Synthetic labels test arithmetic, not the product's independent accuracy.
    unit = {'unit_id': 'one::rule', 'case_id': 'one', 'decision': decision,
            'verification': 'verified', 'expected_support': 'supported'}
    row = {'unit_id': 'one::rule', 'source': 'llm-proxy', 'label': label}
    result = stats.score([unit], [row], label_source='llm-proxy')
    assessable = decision in stats.DEFINITE and label in stats.DEFINITE
    assert result['false_verified']['denominator'] == int(assessable)
    assert result['false_verified']['numerator'] == int(assessable and decision != label)
    assert result['decision_label_matrix'][decision][label] == 1
    assert result['verified_without_decidable_label'] == int(decision in stats.DEFINITE and label == 'undecidable')


def test_duplicate_units_and_labels_cannot_silently_overwrite_denominators():
    unit = {'unit_id': 'one::rule', 'case_id': 'one', 'decision': 'violated', 'verification': 'verified'}
    label = {'unit_id': 'one::rule', 'source': 'llm-proxy', 'label': 'violated'}
    with pytest.raises(ValueError, match='duplicate evaluation unit'):
        stats.score([unit, unit], [label], label_source='llm-proxy')
    with pytest.raises(ValueError, match='duplicate labels'):
        stats.score([unit], [label, label], label_source='llm-proxy')


def test_frozen_duplicate_cases_are_rejected_before_execution():
    case = partial_case()
    with pytest.raises(holdout.HoldoutError, match='duplicate case ids'):
        holdout.freeze({'schema': holdout.CASES, 'split': 'holdout', 'cases': [case, deepcopy(case)]}, protocol='test')


def test_score_rejects_duplicate_and_misidentified_labels():
    frozen = holdout.freeze({'schema': holdout.CASES, 'split': 'holdout', 'cases': [partial_case()]}, protocol='test')
    result = holdout.run_frozen(frozen, holdout.artifact_sha256(frozen))
    packet = holdout.review_packet(frozen, instructions='synthetic')
    labels = holdout.adjudicate(packet, [{'item_id': 'one::visible', 'reviewer_kind': 'llm-proxy',
        'reviewer_id': 'synthetic', 'label': 'satisfied'}])
    malformed = deepcopy(labels)
    malformed['labels'].append(deepcopy(malformed['labels'][0]))
    with pytest.raises(holdout.HoldoutError, match='duplicate labels'):
        holdout.score_all(result, malformed)
    malformed = deepcopy(labels)
    malformed['labels'][0]['unit_id'] = 'one::pr-action'
    with pytest.raises(holdout.HoldoutError, match='same evaluation item'):
        holdout.score_all(result, malformed)
    malformed = deepcopy(labels)
    malformed['labels'][0]['case_id'] = 'other-case'
    with pytest.raises(holdout.HoldoutError, match='same evaluation item'):
        holdout.score_all(result, malformed)
    duplicated = deepcopy(result)
    duplicated['units'].append(deepcopy(duplicated['units'][0]))
    with pytest.raises(holdout.HoldoutError, match='duplicate evaluation unit'):
        holdout.score_all(duplicated, labels)


def test_pr_metrics_keep_unlabelled_cases_and_reject_duplicate_action_labels():
    cases = [{'case_id': 'one', 'gate': 'fail'}, {'case_id': 'two', 'gate': 'error'}]
    label = {'case_id': 'one', 'source': 'llm-proxy', 'kind': 'pr-action', 'label': 'pass'}
    result = stats.pr_action_metrics(cases, [label], label_source='llm-proxy')
    assert result['prs_total'] == 2 and result['prs_unlabelled'] == ['two']
    assert result['false_block']['numerator'] == result['false_block']['denominator'] == 1
    with pytest.raises(ValueError, match='duplicate PR action labels'):
        stats.pr_action_metrics(cases, [label, label], label_source='llm-proxy')
