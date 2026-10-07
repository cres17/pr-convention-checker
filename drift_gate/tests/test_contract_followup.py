"""Static router graphs, route-local uncertainty, and request-scoped caching."""
from copy import deepcopy
import json
from unittest.mock import patch

import pytest

from drift_gate.core.engine import run
from drift_gate.core.evaluation import api_schema
from drift_gate.core.evaluation.analysis_session import AnalysisSession
from drift_gate.core.evaluation.api_schema import extract_responses, response_changes, UnknownResponse, UnsupportedContract
from drift_gate.tests.test_logical_contracts import changed, document, openapi, policy, raw_policy, source
from drift_gate.core.policy.loader import load_policy_from_dict


def router_source(fields='id: int', prefix='/v1', nested=False, repeat=False):
    text = f"from fastapi import FastAPI, APIRouter\nfrom pydantic import BaseModel\napp = FastAPI()\nrouter = APIRouter(prefix='{prefix}')\nclass Order(BaseModel):\n    {fields}\n@router.get(\n    '/orders',\n    response_model=Order,\n)\ndef orders():\n    return {{'id': 1}}\n"
    if nested:
        text += "parent = APIRouter(prefix='/parent')\nparent.include_router(router, prefix='/child')\napp.include_router(parent, prefix='/api')\n"
    else:
        text += "app.include_router(router, prefix='/api')\n"
    if repeat:
        text += "app.include_router(router, prefix='/second')\n"
    return text


@pytest.mark.parametrize('nested,repeat,expected', [
    (False,False,{'/api/v1/orders'}), (True,False,{'/api/parent/child/v1/orders'}),
    (False,True,{'/api/v1/orders','/second/v1/orders'}),
])
def test_static_router_prefix_composition(nested, repeat, expected):
    result=extract_responses(router_source(nested=nested,repeat=repeat))
    assert set(result)=={('GET',path) for path in expected}
    assert all(shape=={'id':{'type':'integer','required':True}} for shape in result.values())


def test_router_prefix_change_requires_new_and_removed_document_paths():
    file=changed(before=router_source(prefix='/v1'), after=router_source(prefix='/v2'))
    assert run([file,document(openapi(path='/api/v2/orders'))],policy=policy()).result=='pass'
    assert run([file,document(openapi(path='/api/v1/orders'))],policy=policy()).result=='fail'


@pytest.mark.parametrize('mutation', ['dynamic-prefix','trailing-prefix','external-router','late-route','late-child','cycle','duplicate','second-app','conditional'])
def test_ambiguous_router_graph_is_unknown(mutation):
    text=router_source(nested=mutation=='late-child')
    if mutation=='dynamic-prefix': text=text.replace("prefix='/v1'",'prefix=PREFIX')
    elif mutation=='trailing-prefix': text=text.replace("prefix='/v1'","prefix='/v1/'")
    elif mutation=='external-router': text=text.replace('include_router(router','include_router(external')
    elif mutation=='late-route': text += "@router.get('/late', response_model=Order)\ndef late(): return {}\n"
    elif mutation=='late-child': text=text.replace("parent.include_router(router, prefix='/child')\napp.include_router(parent, prefix='/api')", "app.include_router(parent, prefix='/api')\nparent.include_router(router, prefix='/child')")
    elif mutation=='cycle': text += 'router.include_router(router)\n'
    elif mutation=='duplicate': text += "app.include_router(router, prefix='/api')\n"
    elif mutation=='second-app': text += 'other = FastAPI()\n'
    elif mutation=='conditional': text=text.replace("app.include_router(router, prefix='/api')", "if True:\n    app.include_router(router, prefix='/api')")
    with pytest.raises(UnsupportedContract): extract_responses(text)


def test_unmounted_router_does_not_invent_an_app_route():
    text=router_source().replace("app.include_router(router, prefix='/api')",'')
    assert extract_responses(text)=={}


def test_router_expansion_has_a_hard_budget():
    text=router_source()+''.join(f"app.include_router(router, prefix='/copy{i}')\n" for i in range(257))
    with pytest.raises(UnsupportedContract,match='limit'): extract_responses(text)


def partial_files(collision=False):
    known=changed()
    other=changed(before=source('id: list[int]',path='/orders' if collision else '/opaque'),after=source('id: list[str]',path='/orders' if collision else '/opaque'))
    other.path='src/other.py'
    return [known,other]


@pytest.mark.parametrize('minimum',['any','route-contract-change'])
@pytest.mark.parametrize('reverse',[False,True])
def test_known_failure_survives_route_local_unknown_source(minimum,reverse):
    files=partial_files()
    if reverse: files.reverse()
    raw=raw_policy(action='warn');raw['rules'][0]['when']['min_change_intensity']=minimum
    # Stale schema for the known route; the other source's identity is known.
    result=run([*files,document(openapi({'id':{'type':'integer'},'label':{'type':'string'}}))],policy=load_policy_from_dict(raw))
    assert result.result=='fail'
    assert result.rule_decisions[0].decision=='violated'
    assert result.verification=='partial'
    assert '/opaque' in result.rule_decisions[0].unsatisfied_groups[0].evidence


def test_duplicate_identity_cannot_be_hidden_by_unknown_shape():
    result=run([*partial_files(collision=True),document()],policy=policy(action='warn'))
    assert result.result=='warn' and not result.violations


def test_unknown_routing_cannot_be_isolated_as_only_a_shape():
    files=partial_files(); files[1].after_source=files[1].after_source.replace("'/opaque'",'DYNAMIC_PATH')
    result=run([*files,document(openapi(path='/wrong'))],policy=policy(action='warn'))
    assert result.result=='warn' and not result.violations


def test_missing_document_with_only_unknown_delta_does_not_invent_violation():
    file=partial_files()[1]
    result=run([file],policy=policy(action='warn'))
    assert result.result=='warn' and not result.violations


def test_known_identity_removal_is_verifiable_even_when_old_shape_is_unknown():
    file=partial_files()[1]; file.status='deleted'; file.after_source=''
    result=run([file,document(json.dumps({'openapi':'3.1.0','paths':{}}))],policy=policy())
    assert result.result=='pass' and result.verification=='verified'


def test_cache_is_per_evaluation_and_bound_to_content():
    raw=raw_policy(); raw['rules'][0]['when']['min_change_intensity']='route-contract-change'
    for i in range(5):
        rule=deepcopy(raw['rules'][0]);rule['id']=f'extra{i}';raw['rules'].append(rule)
    p=load_policy_from_dict(raw); files=[changed(),document()]
    with patch.object(api_schema,'_extract_contracts',wraps=api_schema._extract_contracts) as spy:
        assert run(files,policy=p).result=='pass'
        assert spy.call_count==2  # before/after, shared across thresholds and all rules
        files[0].after_source=source('id: str')
        assert run(files,policy=p).result=='fail'
        assert spy.call_count==4  # a new evaluation never inherits old results


def test_cache_bounds_and_failures_do_not_become_empty_contracts():
    session=AnalysisSession(limit=2)
    for i in range(8):
        file=changed(after=source(path=f'/item{i}'))
        response_changes([file],session)
        assert len(session._entries)<=2
    bad=changed(after='not valid Python!!!')
    for _ in range(2):
        with pytest.raises(UnsupportedContract): response_changes([bad],session)
    good=changed(after=source('id: list[int]'))
    delta=response_changes([good],session)
    assert isinstance(delta[('GET','/orders')],UnknownResponse)


@pytest.mark.parametrize('mutation', ["app.router.routes.clear()\n", "configure(app)\n", "Order.model_rebuild()\n"])
def test_opaque_calls_cannot_mutate_a_verified_routing_scope(mutation):
    with pytest.raises(UnsupportedContract): extract_responses(router_source()+mutation)


def test_path_converter_does_not_impersonate_the_openapi_path():
    with pytest.raises(UnsupportedContract,match='converter'):
        extract_responses(router_source().replace("'/orders'", "'/orders/{id:int}'"))
