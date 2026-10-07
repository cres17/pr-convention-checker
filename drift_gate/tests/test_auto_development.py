"""Regression controls for the auto-panel plan; no application code executed."""
from dataclasses import replace
from itertools import permutations

import pytest

from drift_gate.core.engine import run
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.policy.loader import load_policy_from_dict
from drift_gate.tests.test_logical_contracts import changed, document, openapi, policy, source
from drift_gate.tests.test_contract_followup import router_source
from drift_gate.adapters.docs.content import attach_env_documents
from drift_gate.core.evaluation.environment import environment_facts
from drift_gate.core.evaluation.routes import complete_route_delta


def relation_policy(*, minimum='any', ignore=None, parent='src/config.py'):
    return load_policy_from_dict({'ignore_paths': ignore or [], 'rules': [{
        'id': 'conditional', 'severity': 'blocker',
        'when': {'any_changed': [parent], 'min_change_intensity': minimum},
        'require': {'groups': [{'name': 'API', 'required': False,
                               'all_changed': ['openapi.json'], 'content': 'api-schema'}],
                    'cross_file': [{'name': 'API changed', 'when_any_changed': ['src/api.py'],
                                    'require_groups': ['API']}]}}]})


def config():
    return ChangedFile('src/config.py', 'modified', patch='-x = 1\n+x = 2\n',
                       before_source='x = 1\n', after_source='x = 2\n')


@pytest.mark.parametrize('doc,expected,verification', [
    (document(openapi({'id': {'type': 'integer'}, 'label': {'type': 'string'}})), 'fail', 'verified'),
    (document(openapi()), 'pass', 'verified'),
    (None, 'fail', 'verified'),
    (document('not json'), 'fail', 'unverified'),
])
def test_relation_uses_its_own_contract_source(doc, expected, verification):
    files = [config(), changed(), *([doc] if doc else [])]
    for ordered in permutations(files):
        result = run(list(ordered), policy=relation_policy())
        assert (result.result, result.verification) == (expected, verification)
        decision = result.rule_decisions[0]
        assert decision.trigger_files == ['src/config.py']
        group = (decision.unsatisfied_groups or decision.satisfied_groups)[0]
        assert group.source_files == ['src/api.py'] and group.relation == 'API changed'
        assert group.to_dict()['source_files'] == ['src/api.py']


@pytest.mark.parametrize('files', [[config()], [changed()], [config(), replace(changed(), status='unchanged')]])
def test_relation_needs_both_parent_and_relation(files):
    result = run(files, policy=relation_policy())
    assert result.result == 'pass'
    assert not result.violations


def test_relation_rename_ignore_and_missing_input():
    stale = document(openapi({'id': {'type': 'integer'}, 'label': {'type': 'string'}}))
    renamed = replace(changed(), path='src/moved.py', previous_path='src/api.py', status='renamed')
    assert run([config(), renamed, stale], policy=relation_policy()).rule_decisions[0].decision == 'violated'
    assert run([config(), renamed, stale], policy=relation_policy(ignore=['src/moved.py', 'src/api.py'])).result == 'pass'
    result = run([config(), replace(changed(), before_source=None), stale], policy=relation_policy())
    assert result.rule_decisions[0].decision == 'undetermined'
    assert not result.violations


def test_parent_threshold_still_controls_relation_duty():
    files = [config(), changed(), document('invalid')]
    assert run(files, policy=relation_policy(minimum='route-contract-change')).result == 'pass'
    files[0] = replace(config(), patch='', analysis_method='unavailable')
    result = run(files, policy=relation_policy(minimum='route-contract-change'))
    assert result.rule_decisions[0].decision == 'undetermined'
    assert not result.violations


def test_same_parent_and_relation_scope_matches_direct_control():
    files = [changed(), document(openapi())]
    result = run(files, policy=relation_policy(parent='src/api.py'))
    assert result.result == 'pass' and result.verification == 'verified'


@pytest.mark.parametrize('spelling', [
    "import os\nv = os.getenv('RETRY_DELAY')\n",
    "from os import getenv as read_env\nv = read_env('RETRY_DELAY')\n",
    "import os as runtime\nv = runtime.environ.get('RETRY_DELAY')\n",
    "from os import environ as env\nv = env['RETRY_DELAY']\n",
])
def test_environment_aliases_have_static_binding_evidence(spelling):
    facts = environment_facts(spelling)
    assert facts.keys == {'RETRY_DELAY'} and not facts.uncertain
    result = run([changed(before='', after=spelling, status='added')],
                 policy=policy(mode='env-keys', paths=['.env.example']))
    assert result.rule_decisions[0].decision == 'violated'
    assert result.verification == 'verified'


@pytest.mark.parametrize('spelling', [
    "import os\nv = os.getenv(setting_name)\n",
    "from os import getenv as read_env\nread_env = custom\nv = read_env('RETRY_DELAY')\n",
    "from os import getenv as read_env\ndef f(read_env):\n    return read_env('RETRY_DELAY')\n",
    "import os\nread_env = os.getenv\nv = read_env('RETRY_DELAY')\n",
    "from os import *\nv = getenv('RETRY_DELAY')\n",
    "import os\nos.getenv = custom\nv = os.getenv('RETRY_DELAY')\n",
    "from os import getenv as read_env\ntry:\n    work()\nexcept Exception as read_env:\n    v = read_env('RETRY_DELAY')\n",
    "from os import getenv as read_env\nmatch payload:\n    case {'getter': read_env}:\n        v = read_env('RETRY_DELAY')\n",
])
def test_dynamic_shadowed_and_escaped_getters_stay_unknown(spelling):
    result = run([changed(before='', after=spelling, status='added')],
                 policy=policy(mode='env-keys', action='warn', paths=['.env.example']))
    assert result.result == 'warn' and not result.violations
    assert result.rule_decisions[0].decision == 'undetermined'


@pytest.mark.parametrize('minimum', ['any', 'config-key-added'])
def test_environment_no_delta_and_known_failure_with_unknown(minimum):
    before = 'import os\nv = os.getenv("OLD_KEY")\n'
    after = before + 'new = os.getenv("NEW_KEY")\nother = os.getenv(name)\n'
    doc = ChangedFile('.env.example', 'unchanged', documented_env_keys=[])
    p = policy(mode='env-keys', paths=['.env.example'], action='warn')
    p.rules[0].when.min_change_intensity = minimum
    result = run([changed(before=before, after=after), doc], policy=p)
    assert result.rule_decisions[0].decision == 'violated'
    assert result.verification == 'partial'
    result = run([changed(before=before, after=before)], policy=policy(mode='auto-strict', paths=['.env.example']))
    assert result.result == 'pass' and result.verification == 'not-applicable'


def test_opaque_old_environment_access_cannot_prove_new_key_absent():
    before = 'import os\nv = os.getenv(name)\n'
    after = 'import os\nv = os.getenv("KNOWN_KEY")\n'
    result = run([changed(before=before, after=after)], policy=policy(mode='env-keys', action='warn', paths=['.env.example']))
    assert result.result == 'warn' and not result.violations


@pytest.mark.parametrize('case', ['multiline', 'prefix', 'response', 'unchanged', 'unmounted'])
@pytest.mark.parametrize('doc_current', [True, False])
def test_strict_auto_uses_complete_python_contracts(case, doc_current):
    if case in {'response', 'unchanged'}:
        before = source()
        after = source('id: int') if case == 'response' else before.replace('Order', 'Renamed')
        correct = openapi() if case == 'response' else openapi({'id': {'type': 'integer'}, 'label': {'type': 'string'}})
    else:
        before = router_source('id: int', prefix='/v1').replace('    response_model=Order,\n', '')
        after = before.replace('/v1', '/v2')
        if case == 'multiline':
            after = before.replace("'/orders'", "'/new-orders'")
        if case == 'unmounted':
            before = before.replace("app.include_router(router, prefix='/api')", '')
            after = before.replace('/v1', '/v2')
        from drift_gate.core.evaluation.api_schema import _extract_contracts
        import json
        paths = {}
        for method, path in _extract_contracts(after, routes_only=True):
            paths.setdefault(path, {})[method.lower()] = {'responses': {}}
        correct = json.dumps({'openapi': '3.0.3', 'paths': paths})
    stale = openapi({'id': {'type': 'integer'}, 'label': {'type': 'string'}}) if case == 'response' else openapi()
    result = run([changed(before=before, after=after), document(correct if doc_current else stale)],
                 policy=policy(mode='auto-strict'))
    if case in {'unchanged', 'unmounted'}:
        assert result.result == 'pass' and result.verification == 'not-applicable'
    else:
        assert result.result == ('pass' if doc_current else 'fail')
        assert result.verification == 'verified'


def test_complete_route_delta_tracks_multiline_and_registered_prefix():
    before = "from fastapi import FastAPI\napp = FastAPI()\n@app.get(\n    '/catalog'\n)\ndef read():\n    return {}\n"
    after = before.replace('/catalog', '/products')
    assert complete_route_delta([changed(before=before, after=after)]) == ({('GET', '/products')}, {('GET', '/catalog')})


@pytest.mark.parametrize('text', [
    "openapi: 3.0.3\npaths: {}\npaths: {}\n",
    "openapi: 3.0.3\npaths: &x {}\nother: *x\n",
    "openapi: 3.0.3\npaths: !!python/object/apply:os.system ['echo unsafe']\n",
    "openapi: 3.0.3\npaths:\n  /orders:\n    $ref: https://example.invalid/path\n",
    "openapi: 3.0.3\npaths:\n  /orders:\n    get: null\n",
])
def test_invalid_yaml_never_becomes_verified(text):
    files = attach_env_documents([changed()], policy(mode='auto-strict', action='warn', paths=['openapi.yaml']), lambda path: text)
    result = run(files, policy=policy(mode='auto-strict', action='warn', paths=['openapi.yaml']))
    assert result.result == 'warn' and result.verification == 'unverified'
    assert not result.violations


@pytest.mark.parametrize('mode', ['api-schema', 'auto-strict'])
def test_yaml_openapi_matches_json_semantics(mode):
    import json
    import yaml
    correct = yaml.safe_dump(json.loads(openapi()))
    p = policy(mode=mode, paths=['openapi.yaml'])
    result = run(attach_env_documents([changed()], p, lambda path: correct), policy=p)
    assert result.result == 'pass' and result.verification == 'verified'
    stale = yaml.safe_dump(json.loads(openapi({'id': {'type': 'integer'}, 'label': {'type': 'string'}})))
    result = run(attach_env_documents([changed()], p, lambda path: stale), policy=p)
    assert result.result == 'fail' and result.verification == 'verified'


def test_relation_environment_scope_and_multiple_relations():
    raw = {'rules': [{'id': 'multi', 'severity': 'blocker', 'when': {'any_changed': ['src/config.py']},
        'require': {'groups': [{'name': 'env', 'required': False, 'content': 'env-keys', 'all_changed': ['.env.example']}],
                    'cross_file': [{'name': name, 'when_any_changed': [path], 'require_groups': ['env']}
                                   for name, path in [('first', 'src/first.py'), ('second', 'src/second.py')]]}}]}
    first = ChangedFile('src/first.py', 'modified', patch="+value = os.getenv('FIRST_KEY')\n")
    second = ChangedFile('src/second.py', 'modified', patch="+value = os.getenv('SECOND_KEY')\n")
    env_doc = ChangedFile('.env.example', 'unchanged', documented_env_keys=['FIRST_KEY'])
    for files in permutations([config(), first, second, env_doc]):
        result = run(list(files), policy=load_policy_from_dict(raw))
        assert result.rule_decisions[0].decision == 'violated'
        yes = result.rule_decisions[0].satisfied_groups[0]
        no = result.rule_decisions[0].unsatisfied_groups[0]
        assert yes.source_files == ['src/first.py']
        assert no.source_files == ['src/second.py']


@pytest.mark.parametrize('patch', [
    "-router = APIRouter(prefix='/v1')\n+router = APIRouter(prefix='/v2')\n",
    "+router.route('/catalog').get(handler)\n",
])
def test_possible_route_changes_are_not_lost_at_threshold(patch):
    p = policy(mode='api-routes', action='warn', paths=['docs/api.md'])
    p.rules[0].when.min_change_intensity = 'route-contract-change'
    result = run([ChangedFile('src/api.py', 'modified', patch=patch)], policy=p)
    assert result.result == 'warn'
    assert result.rule_decisions[0].decision == 'undetermined' and not result.violations


@pytest.mark.parametrize('patch', ["+# router.route('/catalog').get(handler)\n", "+message = \"router.route('/catalog').get(handler)\"\n"])
def test_possible_route_witness_excludes_comments_and_strings(patch):
    p = policy(mode='api-routes', paths=['docs/api.md'])
    p.rules[0].when.min_change_intensity = 'route-contract-change'
    result = run([ChangedFile('src/api.py', 'modified', patch=patch)], policy=p)
    assert result.rule_decisions[0].status == 'unmatched'


def test_git_evaluation_harness_preserves_utf8_under_non_utf8_text_defaults(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    from scripts import audit_auto_contracts as harness
    suite = json.loads((harness.ROOT / 'drift_gate/tests/contracts/auto-contracts-v2.json').read_text(encoding='utf-8'))
    suite['cases'] = suite['cases'][:1]
    suite['protocol']['authorship'] = '한국어 검증 사례'
    suite_path, output = tmp_path / 'suite.json', tmp_path / 'result.json'
    suite_path.write_bytes(json.dumps(suite, ensure_ascii=False).encode('utf-8'))
    real = Path.open
    def non_utf8_default(path, mode='r', buffering=-1, encoding=None, errors=None, newline=None):
        if 'b' not in mode and encoding is None:
            encoding = 'cp1252'
        return real(path, mode, buffering, encoding, errors, newline)
    monkeypatch.setattr(Path, 'open', non_utf8_default)
    monkeypatch.setattr(harness.sys, 'argv', ['audit', '--suite', str(suite_path), '--out', str(output)])
    assert harness.main() == 0
    result = json.loads(output.read_text(encoding='utf-8'))
    assert result['protocol']['authorship'] == '한국어 검증 사례'
    assert b'\r\n' not in output.read_bytes()
    assert all(row['correct'] == row['total'] == 1 for row in result['counts'].values())
