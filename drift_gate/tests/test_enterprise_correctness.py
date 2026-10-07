"""Counterexamples and positive controls from the enterprise logical design."""
import json
import subprocess
import sys
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from dataclasses import replace

import pytest

from drift_gate.adapters.ast.express_routes import extract_express_routes
from drift_gate.adapters.docs.content import attach_env_documents
from drift_gate.adapters.inspection import inspect
from drift_gate.core.engine import run
from drift_gate.core.models.evaluation_context import EvaluationContext
from drift_gate.core.models.result import DriftIgnoreDirective
from drift_gate.core.evaluation.openapi_document import load_openapi
from drift_gate.core.evaluation.static_routers import UnsupportedContract
from drift_gate.core.policy.loader import load_policy_from_dict
from drift_gate.tests.test_express_contracts import fixture
from drift_gate.tests.test_logical_contracts import changed, document, policy, source
from scripts.audit_auto_contracts import validate_suite


def plain_api():
    return ('from fastapi import FastAPI\napp = FastAPI()\n'
            '@app.get("/old")\ndef endpoint():\n    return {}\n')


@pytest.mark.parametrize('env', ['import os\nvalue = os.getenv("EXISTING")\n',
                               'from os import getenv as read\nvalue = read("EXISTING")\n',
                               'import os\nvalue = os.getenv(name)\n'])
@pytest.mark.parametrize('minimum', ['any', 'route-contract-change'])
@pytest.mark.parametrize('mode', ['plain-route', 'schema'])
def test_mixed_python_contracts_never_disappear(env, minimum, mode):
    before = env + (plain_api() if mode == 'plain-route' else source())
    after = before.replace('/old', '/new') if mode == 'plain-route' else before.replace('label: str', 'active: bool')
    p = policy(mode='auto-strict', action='warn')
    p.rules[0].when.min_change_intensity = minimum
    result = run([changed(before=before, after=after), document()], policy=p)
    assert result.result == 'warn'
    assert result.rule_decisions[0].decision == 'undetermined'
    assert result.verification == 'unverified'
    assert not result.violations
    reason = result.rule_decisions[0].unsatisfied_groups[0].evidence
    assert 'Mixed environment/API' in reason


def test_explicit_mixed_groups_keep_known_api_failure():
    env = 'import os\nvalue = os.getenv("EXISTING")\n'
    before = env + plain_api()
    p = load_policy_from_dict({'rules': [{'id': 'mixed', 'severity': 'blocker',
        'when': {'any_changed': ['src/**']}, 'require': {'groups': [
            {'name': 'API', 'all_changed': ['openapi.json'], 'content': 'api-routes'},
            {'name': 'env', 'all_changed': ['.env.example'], 'content': 'env-keys'}]}}]})
    stale = json.dumps({'openapi': '3.1.0', 'paths': {'/old': {'get': {'responses': {}}}}})
    result = run([changed(before=before, after=before.replace('/old', '/new')), document(stale)], policy=p)
    assert result.result == 'fail' and result.verification == 'verified'
    assert result.rule_decisions[0].decision == 'violated'


def test_unused_fastapi_import_does_not_invent_api_duty():
    before = 'from fastapi import FastAPI\nimport os\nvalue = os.getenv("EXISTING")\n'
    result = run([changed(before=before, after=before + '# note\n')],
                 policy=policy(mode='auto-strict', paths=['.env.example']))
    assert result.result == 'pass' and result.verification == 'not-applicable'


def test_unresolved_external_route_is_not_hidden_by_unchanged_env():
    before = 'import os\nfrom external import app\nvalue = os.getenv("EXISTING")\n@app.get("/old")\ndef f():\n    return {}\n'
    result = run([changed(before=before, after=before.replace('/old', '/new'))],
                 policy=policy(mode='auto-strict', action='warn'))
    assert result.result == 'warn' and result.verification == 'unverified'


@pytest.mark.parametrize('mutation', ['empty', 'missing-axis', 'duplicate-id', 'invalid-kind',
                                    'invalid-outcome', 'absolute-path', 'parent-path', 'git-config', 'nontext',
                                    'invalid-protocol', 'missing-protocol-axis', 'invalid-kind-type', 'invalid-outcome-type'])
def test_evaluation_suite_cannot_report_vacuous_or_partial_success(mutation):
    case = {'id': 'one', 'before': {}, 'after': {'src/config.py': 'x = 1'}, 'facts_kind': 'env',
            'policy': {}, 'expected': {'facts': [], 'decision': 'satisfied', 'verification': 'not-applicable', 'gate': 'pass'}}
    suite = {'protocol': {'version': 1, 'input': 'authored test',
                         'axes': ['facts', 'decision', 'verification', 'gate']}, 'cases': [case]}
    assert validate_suite(deepcopy(suite)) == suite
    if mutation == 'empty': suite['cases'] = []
    elif mutation == 'missing-axis': del case['expected']['facts']
    elif mutation == 'duplicate-id': suite['cases'].append(deepcopy(case))
    elif mutation == 'invalid-kind': case['facts_kind'] = 'guess'
    elif mutation == 'invalid-outcome': case['expected']['verification'] = 'probably'
    elif mutation == 'absolute-path': case['after'] = {'/tmp/out.py': 'x = 1'}
    elif mutation == 'parent-path': case['after'] = {'../out.py': 'x = 1'}
    elif mutation == 'git-config': case['after'] = {'.git/config': '[alias]'}
    elif mutation == 'nontext': case['after'] = {'src/config.py': {'x': 1}}
    elif mutation == 'invalid-protocol': suite['protocol']['version'] = True
    elif mutation == 'missing-protocol-axis': suite['protocol']['axes'].pop()
    elif mutation == 'invalid-kind-type': case['facts_kind'] = []
    elif mutation == 'invalid-outcome-type': case['expected']['decision'] = {}
    with pytest.raises(ValueError):
        validate_suite(suite)


@pytest.mark.parametrize('name', ['auto-contracts-v2.json', 'express-contracts-v1.json'])
def test_real_frozen_suite_format_remains_supported(name):
    suite = json.loads((Path(__file__).parent / 'contracts' / name).read_text())
    assert validate_suite(suite) == suite


@pytest.mark.parametrize('payload', [
    {'protocol': {'version': 1, 'input': 'test', 'axes': ['facts', 'decision', 'verification', 'gate']}, 'cases': []},
    {'protocol': 'invalid', 'cases': []},
    {'protocol': {'version': True, 'input': 'test', 'axes': ['facts', 'decision', 'verification', 'gate']}, 'cases': []},
])
def test_invalid_evaluation_cli_is_input_error_and_writes_no_success(tmp_path, payload):
    suite = tmp_path / 'invalid.json'
    output = tmp_path / 'report.json'
    suite.write_text(json.dumps(payload))
    script = Path(__file__).resolve().parents[2] / 'scripts/audit_auto_contracts.py'
    process = subprocess.run([sys.executable, str(script), '--suite', str(suite), '--out', str(output)],
                             capture_output=True, text=True, timeout=10)
    assert process.returncode == 2
    assert 'error:' in process.stderr and 'Traceback' not in process.stderr
    assert not output.exists()


@pytest.mark.parametrize('header', [
    "import type express from 'express';", "import /* note */ type express from 'express';",
    "import\ttype\texpress from 'express';", "import\ntype\nexpress from 'express';",
    "import // note\n type express from 'express';",
])
@pytest.mark.parametrize('language', ['typescript', 'tsx'])
def test_type_only_express_import_semantics_survive_trivia(header, language):
    code = fixture().replace("import express from 'express';", header)
    with pytest.raises(UnsupportedContract, match='type-only'):
        extract_express_routes(code, language)
    file = replace(changed(before='', after=code, status='added'), path='src/api.ts' if language == 'typescript' else 'src/api.tsx')
    result = inspect(changed_files=[file, document()], policy=policy(mode='api-routes', action='warn'))
    assert result.result == 'warn' and result.verification == 'unverified'
    assert not result.violations


@pytest.mark.parametrize('keyword', ['const ', 'const\t', 'const\n', 'const /* note */ '])
def test_express_const_tokens_have_same_registration_meaning(keyword):
    code = fixture().replace('const ', keyword)
    assert extract_express_routes(code) == {('GET', '/v1/catalog')}


@pytest.mark.parametrize('token', ['1e999', '-1e999', 'NaN', 'Infinity', '-Infinity'])
@pytest.mark.parametrize('container', ['root', 'nested-list'])
def test_openapi_nonfinite_numeric_domain(token, container):
    value = token if container == 'root' else '[{"value":' + token + '}]'
    text = '{"openapi":"3.1.0","paths":{},"x-number":' + value + '}'
    with pytest.raises(UnsupportedContract, match='unsupported_numeric_range'):
        load_openapi(text)
    result = run([changed(), document(text)], policy=policy(mode='api-schema', action='warn'))
    assert result.result == 'warn' and result.verification == 'unverified'
    assert not result.violations


@pytest.mark.parametrize('token', ['0', '-1', '1e308', '1e-300'])
def test_openapi_finite_numeric_controls(token):
    text = '{"openapi":"3.1.0","paths":{},"x-number":' + token + '}'
    assert 'x-number' in load_openapi(text)


@pytest.mark.parametrize('mode', ['api-routes', 'api-schema', 'auto-strict'])
def test_overflow_document_remains_unknown_through_adapter(mode):
    text = '{"openapi":"3.1.0","paths":{},"x-number":1e999}'
    p = policy(mode=mode, action='warn')
    inputs = attach_env_documents([changed(after=source(path='/new-orders'))], p, lambda path: text)
    result = inspect(changed_files=inputs, policy=p)
    assert result.result == 'warn' and result.verification == 'unverified'


@pytest.mark.parametrize('day,accepted', [(6, True), (7, True), (8, False)])
def test_expiry_is_replayable_and_inclusive_on_expiry_date(day, accepted):
    directive = DriftIgnoreDirective(rule_id='response-contract', reason='reviewed exception', expires='2026-10-07')
    result = run([changed()], policy=policy(), drift_ignores=[directive],
                 context=EvaluationContext(date(2026, 10, day)))
    assert bool(result.skipped_rules) == accepted
    assert bool(result.rejected_ignores) != accepted
    replay = run([changed()], policy=policy(), drift_ignores=[directive],
                 context=EvaluationContext(date(2026, 10, day)))
    assert replay.to_dict() == result.to_dict()


def test_expiring_ignore_without_context_is_not_silently_authorized():
    directive = DriftIgnoreDirective(rule_id='response-contract', reason='exception', expires='2999-01-01')
    result = run([changed()], policy=policy(), drift_ignores=[directive])
    assert not result.skipped_rules
    assert 'explicit evaluation date' in result.rejected_ignores[0].reason


@pytest.mark.parametrize('value', [None, '2026-10-07', True, datetime(2026, 10, 7)])
def test_context_does_not_coerce_date_inputs(value):
    with pytest.raises(ValueError, match='must be a date'):
        EvaluationContext(value)


def test_evaluation_date_is_bound_to_receipt_digest():
    first = inspect(changed_files=[changed(), document()], policy=policy(),
                    context=EvaluationContext(date(2026, 10, 7)))
    second = inspect(changed_files=[changed(), document()], policy=policy(),
                     context=EvaluationContext(date(2026, 10, 8)))
    replay = inspect(changed_files=[changed(), document()], policy=policy(),
                     context=EvaluationContext(date(2026, 10, 7)))
    assert first.execution['input_sha256'] != second.execution['input_sha256']
    assert first.execution['input_sha256'] == replay.execution['input_sha256']
    assert first.execution['evaluation_context'] == {'evaluated_on': '2026-10-07', 'date_basis': 'UTC'}
