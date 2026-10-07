"""Independent framework oracle. Execute only the fixed fixtures authored here.

Production never imports or executes the repository being inspected.
"""
import json

import pytest

pytest.importorskip('fastapi', reason='install drift-gate[oracle] for framework validation')
from fastapi import FastAPI

from drift_gate.core.engine import run
from drift_gate.core.evaluation.api_schema import extract_responses
from drift_gate.tests.test_logical_contracts import changed, document, policy, source
from drift_gate.tests.test_contract_followup import router_source


def controlled_app(text):
    # No filename/input supplied by the application or user enters this helper.
    namespace={'__name__':'drift_gate_test_oracle'}
    exec(compile(text,'<fixed-test-fixture>','exec'),namespace)
    assert isinstance(namespace['app'],FastAPI)
    return namespace['app']


@pytest.mark.parametrize('fields', ['id: int','id: str','id: bool','id: float',
    'id: int = 1','id: str = "value"','id: bool = True','id: float = 1.5'])
@pytest.mark.parametrize('layout',['direct','router','nested','repeated'])
def test_real_fastapi_openapi_agrees_with_supported_static_contract(fields, layout):
    text=source(fields) if layout=='direct' else router_source(fields,nested=layout=='nested',repeat=layout=='repeated')
    actual=controlled_app(text).openapi()
    extracted=extract_responses(text)
    operations={(method.upper(),path) for path,item in actual['paths'].items() for method in item if method in {'get','post','put','patch','delete','head','options','trace'}}
    assert set(extracted)==operations
    file=changed(before='',after=text,status='added')
    result=run([file,document(json.dumps(actual))],policy=policy())
    assert result.result=='pass' and result.verification=='verified'
    # Independent negative control: changing generated field type must fail.
    schema=next(iter(actual['components']['schemas'].values()))
    schema['properties']['id']['type']='string' if schema['properties']['id']['type']!='string' else 'integer'
    schema['properties']['id'].pop('default',None)
    result=run([file,document(json.dumps(actual))],policy=policy())
    assert result.result=='fail' and result.rule_decisions[0].decision=='violated'


@pytest.mark.parametrize('method', ['get', 'post', 'put', 'delete'])
@pytest.mark.parametrize('change', ['fields', 'method', 'deleted', 'unchanged'])
@pytest.mark.parametrize('layout', ['direct', 'router'])
def test_real_framework_before_after_contracts(method, change, layout):
    from drift_gate.core.evaluation.api_schema import response_changes
    def app(fields, verb):
        text = source(fields, method=verb) if layout == 'direct' else router_source(fields).replace('@router.get(', f'@router.{verb}(')
        return text
    before = app('id: int\n    label: str\n    enabled: bool = True', method)
    after = app('id: int\n    enabled: bool = True', method)
    if change == 'method':
        after = app('id: int\n    label: str\n    enabled: bool = True', 'patch')
    elif change == 'deleted':
        after = ''
    elif change == 'unchanged':
        after = before.replace('def orders():', 'def renamed():')
    actual_before = controlled_app(before).openapi()
    actual_after = controlled_app(after).openapi() if after else {'openapi': '3.1.0', 'paths': {}}
    file = changed(before=before, after=after, status='deleted' if change == 'deleted' else 'modified')
    delta = response_changes([file])
    assert bool(delta) == (change != 'unchanged')
    positive = run([file, document(json.dumps(actual_after))], policy=policy(mode='auto-strict'))
    assert positive.result == 'pass'
    assert positive.verification == ('not-applicable' if change == 'unchanged' else 'verified')
    negative = run([file, document(json.dumps(actual_before))], policy=policy(mode='auto-strict'))
    assert negative.result == ('pass' if change == 'unchanged' else 'fail')
