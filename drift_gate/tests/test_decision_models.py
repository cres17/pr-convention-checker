"""Migration-gated proof decisions (11), typed triggers (20) and API compatibility (21)."""
from copy import deepcopy
from hashlib import sha256
import json
import random
import subprocess

import pytest

from drift_gate.core.contracts.planner import Truth
from drift_gate.core.engine import run
from drift_gate.core.evaluation.compatibility import (
    Unsupported, admits, compare_documents, normalize, subset,
)
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.policy.loader import PolicyLoadError, load_policy_from_dict
from drift_gate.desktop.package_git_check import source


def api_file(before, after, path='src/api.py'):
    return ChangedFile(path, 'modified', patch='@@\n-x\n+y\n', before_source=source(before), after_source=source(after))


def doc_file(text, path='docs/api.md'):
    return ChangedFile(path, 'modified', patch='@@\n+x\n', after_source=text, document_input_state='available')


def proof_policy(proof_gate='v1', content='contract-proof'):
    return load_policy_from_dict({'rules': [{'id': 'api', 'when': {'any_changed': ['src/**']},
        'require': {'groups': [{'name': 'docs', 'any_changed': ['docs/api.md'], 'content': content}]},
        'severity': 'blocker'}], 'gate': {'proof_gate': proof_gate}})


# -- 11. proof gate ----------------------------------------------------------------
def test_contract_proof_group_requires_the_versioned_gate():
    with pytest.raises(PolicyLoadError, match='proof_gate: v1'):
        proof_policy(proof_gate='off')
    with pytest.raises(PolicyLoadError, match='off or v1'):
        load_policy_from_dict({'rules': [{'id': 'a', 'when': {'any_changed': ['x']},
            'require': {'groups': [{'name': 'g', 'any_changed': ['d.md']}]}}], 'gate': {'proof_gate': 'v2'}})


def test_proof_gate_decides_through_the_validated_dag():
    policy = proof_policy()
    stale = run([api_file('/old', '/new'), doc_file('GET /old\n')], policy=policy)
    assert stale.result == 'fail'
    group = stale.violations[0].unsatisfied_groups[0]
    assert (group.content_mode, group.decision) == ('contract-proof', 'violated')
    current = run([api_file('/old', '/new'), doc_file('GET /new\n')], policy=policy)
    decision = current.rule_decisions[0]
    assert decision.status == 'pass' and decision.satisfied_groups[0].content_mode == 'contract-proof'
    # Unparseable source: the proof root is U, never a pass; on_unverified=fail applies.
    broken = ChangedFile('src/api.py', 'modified', patch='@@\n+x\n', before_source=source('/old'),
                         after_source='def (:\n')
    assert run([broken, doc_file('GET /new\n')], policy=policy).result == 'fail'


def test_identical_policy_without_proof_gate_keeps_its_identity():
    from drift_gate.core.models.policy import policy_identity_dict
    legacy = load_policy_from_dict({'rules': [{'id': 'a', 'when': {'any_changed': ['x']},
                                               'require': {'groups': [{'name': 'g', 'any_changed': ['d.md']}]}}]})
    data = policy_identity_dict(legacy)
    assert 'proof_gate' not in data['gate'] and 'services' not in data and 'budget' not in data
    assert 'trigger' not in data['rules'][0]['when'] and 'direction' not in data['rules'][0]['require']['groups'][0]


def git(root, *args):
    return subprocess.check_output(['git', '-c', 'core.autocrlf=false', *args], cwd=root, stderr=subprocess.PIPE)


def commit(root, files, message):
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, encoding='utf-8')
    git(root, 'add', '-A')
    git(root, '-c', 'user.name=F', '-c', 'user.email=f@example.invalid', 'commit', '-q', '-m', message)
    return git(root, 'rev-parse', 'HEAD').decode().strip()


MIGRATION_POLICY = '''rules:
  - id: api
    when: {any_changed: ["src/**"], min_change_intensity: route-contract-change}
    require: {groups: [{name: docs, any_changed: ["docs/api.md"], content: auto-strict}]}
    severity: blocker
'''


def test_proof_gate_and_typed_trigger_migration_reports(tmp_path, monkeypatch, capsys):
    from drift_gate.adapters.cli.runner import run_cli
    git(tmp_path, 'init', '-q')
    base = commit(tmp_path, {'.drift-gate.yml': MIGRATION_POLICY, 'src/api.py': source('/old'),
                             'docs/api.md': 'GET /old\n'}, 'base')
    head = commit(tmp_path, {'src/api.py': source('/new')}, 'route change, stale doc')
    monkeypatch.chdir(tmp_path)
    pin = sha256(MIGRATION_POLICY.encode()).hexdigest()
    args = ['--base', base, '--head', head, '--trusted-policy-ref', base, '--trusted-policy-sha256', pin]
    with pytest.raises(SystemExit) as exit:
        run_cli(['migrate', 'proof-gate', *args])
    report = json.loads(capsys.readouterr().out)
    row = report['groups'][0]
    assert (row['legacy']['decision'], row['proof']['decision'], row['classification']) == (
        'violated', 'violated', 'equal')
    assert report['safe_to_switch'] and exit.value.code == 0
    with pytest.raises(SystemExit) as exit:
        run_cli(['migrate', 'typed-trigger', *args])
    trigger = json.loads(capsys.readouterr().out)['rules'][0]
    assert trigger['mapped_trigger'] == {'family': 'api-route', 'predicate': 'route-changed'}
    assert trigger['classification'] == 'equal' and exit.value.code == 0


# -- 20. typed triggers --------------------------------------------------------------
def trigger_policy(**trigger):
    return load_policy_from_dict({'rules': [{'id': 'api', 'when': {'any_changed': ['src/**'], 'trigger': trigger},
        'require': {'groups': [{'name': 'docs', 'any_changed': ['docs/api.md'], 'content': 'api-routes'}]},
        'severity': 'major'}], 'gate': {'fail_on_major_count': 1}})


def test_typed_trigger_separates_kind_magnitude_and_unknown():
    added = trigger_policy(family='api-route', predicate='route-added')
    assert run([api_file('/old', '/new'), doc_file('GET /old\n')], policy=added).result == 'fail'
    removed_only = trigger_policy(family='api-route', predicate='route-removed', min_magnitude=2)
    decision = run([api_file('/old', '/new'), doc_file('GET /old\n')], policy=removed_only).rule_decisions[0]
    assert decision.status == 'unmatched' and 'predicate is false' in decision.reason
    review = trigger_policy(family='api-route', predicate='route-changed', on_unknown='review')
    unknown_source = ChangedFile('src/api.py', 'modified', patch='@@\n+x\n', before_source=None, after_source=None)
    outcome = run([unknown_source, doc_file('GET /old\n')], policy=review)
    assert outcome.rule_decisions[0].status == 'undetermined' and not outcome.violations
    ignored = trigger_policy(family='api-route', predicate='route-changed', on_unknown='ignore-with-audit')
    audit = run([unknown_source, doc_file('GET /old\n')], policy=ignored).rule_decisions[0]
    assert audit.status == 'unmatched' and 'audited' in audit.reason
    with pytest.raises(PolicyLoadError, match='not defined'):
        trigger_policy(family='env-key', predicate='route-added')


def test_typed_trigger_change_needs_migration_against_the_trusted_policy():
    from drift_gate.core.policy.guard import weakening_reasons
    trusted = trigger_policy(family='api-route', predicate='route-changed', on_unknown='review')
    candidate = trigger_policy(family='api-route', predicate='route-changed', on_unknown='ignore-with-audit')
    assert any('typed trigger changed' in reason for reason in weakening_reasons(trusted, candidate))


# -- 21. compatibility ----------------------------------------------------------------
def document(schema=None, *, request=None, status='200', params=None, media='application/json', components=None):
    operation = {'responses': {status: {'content': {media: {'schema': schema or {}}}}}}
    if request is not None:
        operation['requestBody'] = request
    if params is not None:
        operation['parameters'] = params
    return {'paths': {'/a': {'post': operation}}, 'components': {'schemas': components or {}}}


@pytest.mark.parametrize('old, new, response, request_truth', [
    ({'type': 'string'}, {'type': 'string', 'nullable': True}, 'F', 'T'),
    ({'type': 'string', 'enum': ['a', 'b']}, {'type': 'string', 'enum': ['a', 'b', 'c']}, 'F', 'T'),
    ({'type': 'string', 'enum': ['a', 'b']}, {'type': 'string', 'enum': ['a']}, 'T', 'F'),
    ({'type': 'object', 'properties': {'x': {'type': 'integer'}}, 'required': ['x']},
     {'type': 'object', 'properties': {'x': {'type': 'integer'}}}, 'F', 'T'),
    ({'type': 'integer'}, {'type': 'number'}, 'F', 'T'),
    ({'type': 'object', 'additionalProperties': False, 'properties': {'x': {'type': 'string'}}},
     {'type': 'object', 'additionalProperties': False, 'properties': {'x': {'type': 'string'}, 'y': {'type': 'string'}}},
     'F', 'T'),
])
def test_direction_specific_schema_rules(old, new, response, request_truth):
    assert compare_documents(document(old), document(new), 'response').truth.value == response
    body = lambda schema: {'content': {'application/json': {'schema': schema}}}
    assert compare_documents(document(request=body(old)), document(request=body(new)), 'request').truth.value == request_truth


def test_status_media_body_parameters_and_removed_operations():
    assert compare_documents(document({}), document({}, status='201'), 'response').breaking[0].check == 'status-added'
    assert compare_documents(document({}), document({}, media='text/plain'), 'response').truth == Truth.FALSE
    optional = {'content': {'application/json': {'schema': {}}}}
    required = {**optional, 'required': True}
    assert compare_documents(document(request=optional), document(request=required), 'request').breaking[0].check == \
        'body-became-required'
    param = {'in': 'query', 'name': 'q', 'schema': {'type': 'string'}}
    assert compare_documents(document(params=[]), document(params=[{**param, 'required': True}]), 'request').truth == \
        Truth.FALSE
    assert compare_documents(document(params=[param]), document(params=[]), 'request').truth == Truth.UNKNOWN
    gone = {'paths': {}, 'components': {}}
    assert compare_documents(document({}), gone, 'response').breaking[0].check == 'removed-operation'


def test_refs_allof_oneof_and_recursion_profiles():
    components = {'Item': {'type': 'object', 'properties': {'id': {'type': 'integer'}}, 'required': ['id']},
                  'Node': {'type': 'object', 'properties': {'next': {'$ref': '#/components/schemas/Node'}}}}
    ref = {'$ref': '#/components/schemas/Item'}
    assert compare_documents(document(ref, components=components), document(ref, components=components),
                             'response').truth == Truth.TRUE
    merged = {'allOf': [ref, {'type': 'object', 'properties': {'name': {'type': 'string'}}}]}
    assert compare_documents(document(ref, components=components), document(merged, components=components),
                             'response').truth == Truth.TRUE
    union_old = {'oneOf': [{'type': 'string'}, {'type': 'integer'}]}
    assert compare_documents(document(union_old), document({'type': 'string'}), 'response').truth == Truth.TRUE
    assert compare_documents(document({'type': 'string'}), document(union_old), 'response').truth == Truth.FALSE
    recursive = {'$ref': '#/components/schemas/Node'}
    changed = deepcopy(components)
    changed['Node']['properties']['extra'] = {'type': 'string'}
    assert compare_documents(document(recursive, components=components), document(recursive, components=changed),
                             'response').truth == Truth.UNKNOWN
    with pytest.raises(Unsupported):
        normalize({'$ref': 'http://example.invalid/s.json'}, {})
    assert compare_documents(document({'pattern': '^a'}), document({'pattern': '^b'}), 'response').truth == Truth.UNKNOWN


# Independent oracle: a direct JSON Schema interpreter over a finite value universe.
def _universe():
    level0 = [None, True, False, 0, 1, 2, 1.5, 'a', 'b', 'c']
    level1 = level0 + [[], {}] + [[v] for v in level0] + [{k: v} for k in 'xyz' for v in level0]
    containers = [v for v in level1 if isinstance(v, (list, dict))]
    level2 = (level1 + [[v] for v in containers] + [{k: v} for k in 'xy' for v in containers]
              + [{'x': v1, 'y': v2} for v1 in level0 + [{}] for v2 in level0 + [{}]])
    unique = {}
    for value in level2:
        unique.setdefault(json.dumps(value, sort_keys=True), value)
    return list(unique.values())


UNIVERSE = _universe()


def oracle_valid(schema, value):
    types = schema.get('type')
    if types is not None:
        names = [types] if isinstance(types, str) else list(types)
        if schema.get('nullable'):
            names.append('null')
        kind = ('null' if value is None else 'boolean' if isinstance(value, bool) else 'integer' if isinstance(value, int)
                else 'number' if isinstance(value, float) else 'string' if isinstance(value, str)
                else 'array' if isinstance(value, list) else 'object')
        if not (kind in names or kind == 'integer' and 'number' in names):
            return False
    if 'enum' in schema and not any(json.dumps(value, sort_keys=True) == json.dumps(e, sort_keys=True)
                                    for e in schema['enum']):
        return False
    if isinstance(value, dict):
        if not set(schema.get('required', [])) <= set(value):
            return False
        for key, item in value.items():
            if key in schema.get('properties', {}):
                if not oracle_valid(schema['properties'][key], item):
                    return False
            elif schema.get('additionalProperties', True) is False:
                return False
    if isinstance(value, list) and 'items' in schema:
        return all(oracle_valid(schema['items'], item) for item in value)
    return True


SAMPLES = {'string': ['a', 'b', 'c', 'zz'], 'integer': [0, 1, 2, 7], 'number': [1.5, 0, 2],
           'boolean': [True, False], 'null': [None]}
FREE = [None, True, 0, 1.5, 'a', [], {}]


def instances(schema, depth=0):
    """Schema-driven candidate members, filtered by the interpreter (independent of the code under test)."""
    declared = schema.get('type')
    names = ([declared] if isinstance(declared, str) else list(declared) if declared else
             ['string', 'integer', 'number', 'boolean', 'null', 'array', 'object'])
    if schema.get('nullable'):
        names.append('null')
    values = list(schema.get('enum', []))
    for name in names:
        if name in SAMPLES:
            values += SAMPLES[name]
        elif name == 'array':
            items = instances(schema['items'], depth + 1) if 'items' in schema and depth < 3 else FREE
            values += [[]] + [[item] for item in items[:5]] + [[items[0], items[-1]]] if items else [[]]
        elif name == 'object' and depth < 3:
            props = schema.get('properties', {})
            choices = {key: instances(sub, depth + 1)[:4] or [None] for key, sub in props.items()}
            base = {key: options[0] for key, options in choices.items()}
            values += [base, {k: v for k, v in base.items() if k in schema.get('required', [])}]
            for key, options in choices.items():
                for option in options:
                    values.append({**base, key: option})
            if schema.get('additionalProperties', True) is not False:
                values += [{**base, 'zz': extra} for extra in FREE]
            values += [{}]
    return [value for value in values if oracle_valid(schema, value)]


def random_schema(rng, depth=0):
    choice = rng.randrange(5 if depth < 2 else 3)
    if choice == 0:
        schema = {'type': rng.choice(['string', 'integer', 'number', 'boolean'])}
        if rng.random() < 0.3:
            schema['nullable'] = True
        if schema['type'] == 'string' and rng.random() < 0.5:
            schema['enum'] = rng.sample(['a', 'b', 'c'], rng.randint(1, 3))
        if schema['type'] == 'integer' and rng.random() < 0.4:
            schema['enum'] = rng.sample([0, 1, 2], rng.randint(1, 3))
        return schema
    if choice == 1:
        return {}
    if choice == 2:
        return {'type': rng.choice([['string', 'integer'], ['boolean', 'null'], ['string']])}
    if choice == 3:
        props = {name: random_schema(rng, depth + 1) for name in rng.sample(['x', 'y'], rng.randint(0, 2))}
        schema = {'type': 'object', 'properties': props}
        if props and rng.random() < 0.5:
            schema['required'] = rng.sample(sorted(props), rng.randint(1, len(props)))
        if rng.random() < 0.4:
            schema['additionalProperties'] = False
        return schema
    return {'type': 'array', 'items': random_schema(rng, depth + 1)}


def test_subset_agrees_with_an_independent_interpreter_on_a_finite_universe():
    rng = random.Random(20261008)
    proven_true = proven_false = 0
    for _ in range(1500):
        a, b = random_schema(rng), random_schema(rng)
        verdict = subset(normalize(a, {}), normalize(b, {}), '$', [])
        counterexamples = [v for v in UNIVERSE + instances(a) if oracle_valid(a, v) and not oracle_valid(b, v)]
        if verdict == Truth.TRUE:
            proven_true += 1
            assert not counterexamples, (a, b, counterexamples)
        elif verdict == Truth.FALSE:
            proven_false += 1
            # F claims a counterexample exists: search the fixed universe and a's own generated members.
            assert counterexamples, (a, b)
    assert proven_true > 200 and proven_false > 200


def test_admits_matches_the_oracle_value_by_value():
    rng = random.Random(7)
    for _ in range(300):
        schema = random_schema(rng)
        node = normalize(schema, {})
        for value in UNIVERSE:
            assert (admits(node, value) == Truth.TRUE) == oracle_valid(schema, value), (schema, value)


def test_policy_group_uses_before_and_after_documents():
    policy = load_policy_from_dict({'rules': [{'id': 'compat', 'when': {'any_changed': ['openapi.json']},
        'require': {'groups': [{'name': 'compatible', 'any_changed': ['openapi.json'], 'content': 'api-compatibility',
                                'direction': 'response'}]}, 'severity': 'blocker'}]})
    old = json.dumps(document({'type': 'string'}))
    new = json.dumps(document({'type': 'string', 'nullable': True}))
    file = ChangedFile('openapi.json', 'modified', patch='@@\n+x\n', before_source=old, after_source=new)
    result = run([file], policy=policy)
    assert result.result == 'fail' and result.violations[0].unsatisfied_groups[0].content_mode == 'api-compatibility'
    same = ChangedFile('openapi.json', 'modified', patch='@@\n+x\n', before_source=old, after_source=old)
    assert run([same], policy=policy).result == 'pass'
    with pytest.raises(PolicyLoadError, match='direction'):
        load_policy_from_dict({'rules': [{'id': 'c', 'when': {'any_changed': ['o.json']},
            'require': {'groups': [{'name': 'g', 'any_changed': ['o.json'], 'content': 'api-compatibility'}]}}]})
