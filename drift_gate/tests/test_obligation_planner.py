"""Authored mixed-contract controls; no claims of real PR accuracy or proof completeness."""
from dataclasses import FrozenInstanceError, replace
import json

import pytest

from drift_gate.core.contracts.discovery import discover_contracts
from drift_gate.core.contracts.planner import (
    ContractAssessment, ContractObligation, DocumentBinding, DocumentBindings,
    ObligationOutcome, PlanReason, PlanRequest, Truth, conditional,
    contract_scopes, delta_applicability, plan_contracts,
)
from drift_gate.core.evaluation.analysis_session import AnalysisSession
from drift_gate.core.evaluation.contracts import content_requirement
from drift_gate.core.evaluation.obligations import inspect_contract_plan
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.facts import ContractFamily, ExactDelta, FactBasis, ReasonCode, UnknownDelta
from drift_gate.core.models.policy import Group
from drift_gate.core.evaluation.evaluator import _evaluate_cross_file_relations
from drift_gate.core.models.policy import CrossFileRelation


ENV = ('python-env-literals', '1')
ROUTE = ('python-fastapi-routes', '1')
RESPONSE = ('python-response-primitives', '2')


def code(path='/old', key='KNOWN', *, dynamic=False):
    return ('from fastapi import FastAPI\nimport os\napp = FastAPI()\n'
            f'value = os.getenv({"name" if dynamic else repr(key)})\n'
            f'@app.get({path!r})\ndef endpoint(): return {{}}\n')


def source(before=None, after=None, path='src/api.py'):
    return ChangedFile(path, 'modified', before_source=code() if before is None else before,
                       after_source=code('/new') if after is None else after)


def documents(path='/new', keys=('KNOWN',)):
    return [ChangedFile('docs/api.md', 'unchanged', after_source=f'GET {path}\n', document_input_state='available'),
            ChangedFile('.env.example', 'unchanged', documented_env_keys=list(keys), document_input_state='available')]


def bindings():
    return DocumentBindings('contract-document-bindings-v1', (
        DocumentBinding('api-doc', ROUTE, ('docs/api.md',)),
        DocumentBinding('env-doc', ENV, ('.env.example',)),
        DocumentBinding('response-doc', RESPONSE, ('openapi.json',)),
    ))


def request(files, selected=None, relation=''):
    return PlanRequest('contract-sync', 'contracts', tuple(file.path for file in files),
                       bindings() if selected is None else selected, relation)


def outcome(result, family):
    return next(row for row in result.outcomes if row.obligation.assessment.scope.family == family)


@pytest.mark.parametrize('case', [
    'unchanged-env-stale-api', 'new-env-missing-api', 'dynamic-env-stale-api',
    'dynamic-env-current-api', 'both-no-delta', 'unsupported-source-with-current-api',
])
def test_design_mixed_contract_matrix(case):
    files, docs, expected, complete = [source()], documents('/old'), Truth.FALSE, True
    if case == 'new-env-missing-api':
        files = [source(after=code('/new', 'NEW'))]
        docs = documents(keys=('NEW',)); docs[0] = ChangedFile('docs/api.md', 'unchanged', document_input_state='missing')
    elif case.startswith('dynamic-env'):
        files = [source(before=code(dynamic=True), after=code('/new', dynamic=True))]
        docs = documents('/old' if case.endswith('stale-api') else '/new')
        expected, complete = (Truth.FALSE if case.endswith('stale-api') else Truth.UNKNOWN), False
    elif case == 'both-no-delta':
        files, docs, expected = [source(after=code())], [], Truth.TRUE
    elif case == 'unsupported-source-with-current-api':
        files.append(ChangedFile('src/opaque.go', 'modified', before_source='package api', after_source='package api'))
        docs, expected, complete = documents(), Truth.UNKNOWN, False
    result = inspect_contract_plan(request(files), files, docs)
    assert result.truth == expected and result.complete_within_selection is complete
    api = outcome(result, ContractFamily.API_ROUTE)
    assert api.obligation.assessment.applicability == (Truth.FALSE if case == 'both-no-delta' else Truth.TRUE)
    if case == 'unchanged-env-stale-api':
        assert outcome(result, ContractFamily.ENV_KEY).obligation.assessment.applicability == Truth.FALSE
        assert api.truth == Truth.FALSE
    if case.startswith('dynamic-env'):
        assert outcome(result, ContractFamily.ENV_KEY).obligation.assessment.applicability == Truth.UNKNOWN
        assert result.plan.guards


def test_unmapped_contract_is_unknown_without_extension_guessing():
    files = [source(after=code('/new', 'NEW'))]
    selected = DocumentBindings('contract-document-bindings-v1', (DocumentBinding('api', ROUTE, ('docs/api.md',)),))
    result = inspect_contract_plan(request(files, selected), files, documents(keys=('NEW',)))
    env = outcome(result, ContractFamily.ENV_KEY)
    assert env.requirement == Truth.UNKNOWN and PlanReason.UNMAPPED_DOCUMENT in env.reason_codes
    assert result.truth == Truth.UNKNOWN


def test_missing_mapping_does_not_create_a_document_duty_for_no_delta():
    files = [source(after=code())]
    result = inspect_contract_plan(request(files, DocumentBindings('contract-document-bindings-v1')), files)
    assert result.truth == Truth.TRUE and result.complete_within_selection
    assert all(row.obligation.assessment.applicability == Truth.FALSE for row in result.outcomes)


def test_literal_document_not_collected_is_unknown_not_authenticated_missing():
    files = [source()]
    result = inspect_contract_plan(request(files), files, documents()[1:])
    assert outcome(result, ContractFamily.API_ROUTE).requirement == Truth.UNKNOWN
    assert result.truth == Truth.UNKNOWN and not result.complete_within_selection


@pytest.mark.parametrize('require_all,truth', [(False, Truth.TRUE), (True, Truth.UNKNOWN)])
def test_document_alternatives_keep_unknown_coverage_even_with_positive_witness(require_all, truth):
    files = [source()]
    selected = DocumentBindings('contract-document-bindings-v1', (
        DocumentBinding('api', ROUTE, ('docs/api.md', 'docs/other.md'), require_all),))
    result = inspect_contract_plan(request(files, selected), files, documents())
    assert result.truth == truth and not result.complete_within_selection
    assert outcome(result, ContractFamily.API_ROUTE).requirement == truth


def test_all_documents_keep_known_false_with_unknown_sibling():
    files = [source()]
    selected = DocumentBindings('contract-document-bindings-v1', (
        DocumentBinding('api', ROUTE, ('docs/api.md', 'docs/other.md'), True),))
    result = inspect_contract_plan(request(files, selected), files, documents('/old'))
    assert result.truth == Truth.FALSE and not result.complete_within_selection


@pytest.mark.parametrize('path,expected', [('/new', Truth.TRUE), ('/old', Truth.UNKNOWN)])
def test_glob_document_observations_do_not_certify_complete_enumeration(path, expected):
    files = [source()]
    selected = DocumentBindings('contract-document-bindings-v1', (
        DocumentBinding('api', ROUTE, ('docs/*.md',)),))
    result = inspect_contract_plan(request(files, selected), files, documents(path))
    assert result.truth == expected and not result.complete_within_selection
    assert PlanReason.DOCUMENT_OPEN in outcome(result, ContractFamily.API_ROUTE).reason_codes


def test_env_key_move_includes_inactive_modules_and_is_not_new():
    files = [source(before='import os\nx = os.getenv("MOVE")\n', after='x = 1\n', path='src/first.py'),
             source(before='x = 1\n', after='import os\nx = os.getenv("MOVE")\n', path='src/second.py')]
    result = inspect_contract_plan(request(files), files)
    env = outcome(result, ContractFamily.ENV_KEY)
    assert env.obligation.assessment.applicability == Truth.FALSE
    assert result.truth == Truth.TRUE and result.complete_within_selection
    assert env.obligation.assessment.scope.source_paths == ('src/first.py', 'src/second.py')


def test_unknown_old_env_in_other_module_cannot_prove_new_key():
    files = [source(before='import os\nx = os.getenv(name)\n', after='x = 1\n', path='src/first.py'),
             source(before='x = 1\n', after='import os\nx = os.getenv("MAYBE_OLD")\n', path='src/second.py')]
    result = inspect_contract_plan(request(files), files, [ChangedFile('.env.example', 'unchanged', document_input_state='missing')])
    env = outcome(result, ContractFamily.ENV_KEY)
    assert env.obligation.assessment.applicability == Truth.UNKNOWN
    assert not env.obligation.assessment.delta.added_must
    assert result.truth == Truth.UNKNOWN


def response_code(fields='id: int'):
    return ('from fastapi import FastAPI\nfrom pydantic import BaseModel\napp = FastAPI()\n'
            f'class Item(BaseModel):\n    {fields}\n'
            '@app.get("/items", response_model=Item)\ndef endpoint(): return {}\n')


def test_response_duty_never_subsumes_route_duty():
    files = [source(before=response_code(), after=response_code().replace('/items', '/new'))]
    result = inspect_contract_plan(request(files), files, documents('/old'))
    assert {row.obligation.assessment.scope.family for row in result.outcomes} == {ContractFamily.API_ROUTE, ContractFamily.API_RESPONSE}
    assert outcome(result, ContractFamily.API_ROUTE).truth == Truth.FALSE
    assert outcome(result, ContractFamily.API_RESPONSE).truth == Truth.UNKNOWN
    assert result.truth == Truth.FALSE and not result.complete_within_selection


def test_response_only_module_change_is_not_erased_by_plain_route_module():
    files = [source(before=response_code('id: int\n    label: str'), after=response_code(), path='src/models.py'),
             source(before=code(), after=code(), path='src/plain.py')]
    result = inspect_contract_plan(request(files), files)
    assert outcome(result, ContractFamily.API_RESPONSE).obligation.assessment.applicability == Truth.TRUE
    assert not result.plan.guards


def test_plain_route_identity_collision_cannot_prove_a_response_duty():
    from drift_gate.tests.test_logical_contracts import openapi
    files = [source(before=response_code('id: int\n    label: str'), after=response_code(), path='src/model.py'),
             source(before=code('/items'), after=code('/items'), path='src/plain.py')]
    docs = [ChangedFile('openapi.json', 'unchanged', after_source=openapi(path='/items', fields={
        'id': {'type': 'integer'}, 'label': {'type': 'string'}}), document_input_state='available')]
    result = inspect_contract_plan(request(files), files, docs)
    assert outcome(result, ContractFamily.API_RESPONSE).obligation.assessment.applicability == Truth.UNKNOWN
    assert result.truth == Truth.UNKNOWN and not result.complete_within_selection


def test_supported_response_mismatch_remains_false_with_opaque_shape_sibling():
    from drift_gate.tests.test_logical_contracts import openapi
    old = response_code('id: int\n    label: str')
    files = [source(before=old, after=response_code(), path='src/known.py'),
             source(before=response_code('id: list[int]').replace('/items', '/opaque'),
                    after=response_code('id: list[int]').replace('/items', '/opaque'), path='src/opaque.py')]
    doc = ChangedFile('openapi.json', 'unchanged', after_source=openapi(path='/items', fields={
        'id': {'type': 'integer'}, 'label': {'type': 'string'}}), document_input_state='available')
    result = inspect_contract_plan(request(files), files, [doc])
    assert outcome(result, ContractFamily.API_RESPONSE).truth == Truth.FALSE
    assert result.truth == Truth.FALSE and not result.complete_within_selection


def test_open_domains_without_candidates_have_mandatory_guards():
    files = [ChangedFile('src/file.go', 'modified', before_source='', after_source='package main')]
    req = request(files, DocumentBindings('contract-document-bindings-v1'))
    result = inspect_contract_plan(req, files)
    assert not result.plan.obligations and len(result.plan.guards) == 3
    assert result.truth == Truth.UNKNOWN and not result.complete_within_selection
    with pytest.raises(ValueError, match='guards'):
        replace(result.plan, guards=())


def test_closed_inactive_scope_is_empty_plan_with_explicit_discovery():
    files = [source(before='value = 1\n', after='value = 2\n')]
    result = inspect_contract_plan(request(files), files)
    assert not result.plan.obligations and not result.plan.guards
    assert result.truth == Truth.TRUE and result.complete_within_selection
    assert result.to_dict()['service_scope_certified'] is False


def test_missing_assessment_is_retained_and_annotated():
    files = [source()]; req = request(files); discovery = discover_contracts(files)
    plan = plan_contracts(req, discovery)
    assert plan.obligations and all(row.assessment.applicability == Truth.UNKNOWN for row in plan.obligations)
    assert all(PlanReason.MISSING_ASSESSMENT in row.assessment.reason_codes for row in plan.obligations)


@pytest.mark.parametrize('mutation', ['omit-obligation', 'omit-binding', 'omit-outcome', 'duplicate-outcome', 'other-scope'])
def test_plan_and_result_reject_dropped_or_substituted_coverage(mutation):
    files = [source(after=code('/new', 'NEW'))]
    result = inspect_contract_plan(request(files), files, documents(keys=('NEW',)))
    with pytest.raises(ValueError):
        if mutation == 'omit-obligation': replace(result.plan, obligations=result.plan.obligations[:-1])
        elif mutation == 'omit-binding':
            rows = [replace(row, binding=None) for row in result.plan.obligations]
            replace(result.plan, obligations=rows)
        elif mutation == 'omit-outcome': replace(result, outcomes=result.outcomes[:-1])
        elif mutation == 'duplicate-outcome': replace(result, outcomes=result.outcomes + result.outcomes[:1])
        else:
            other = replace(result.plan.obligations[0].assessment.scope, request_ref='other')
            plan_contracts(result.plan.request, result.plan.discovery, [ContractAssessment(other, Truth.UNKNOWN)])


@pytest.mark.parametrize('changes', [{'id': ''}, {'profile_ref': None}, {'profile_ref': ('x',)},
                                    {'selectors': []}, {'selectors': ['x', 'x']}, {'require_all': 1}])
def test_invalid_document_binding_rejected(changes):
    with pytest.raises(ValueError): replace(DocumentBinding('env', ENV, ('.env.example',)), **changes)


@pytest.mark.parametrize('schema,entries', [('future', ()), ('contract-document-bindings-v1', (None,)),
    ('contract-document-bindings-v1', (DocumentBinding('a', ENV, ('a',)), DocumentBinding('b', ENV, ('b',))))])
def test_invalid_version_or_ambiguous_bindings_rejected(schema, entries):
    with pytest.raises(ValueError): DocumentBindings(schema, entries)


def test_binding_collections_and_plan_are_immutable():
    selectors = ['.env.example']; entry = DocumentBinding('env', list(ENV), selectors)
    entries = [entry]; selected = DocumentBindings('contract-document-bindings-v1', entries)
    paths = ['src/api.py']; req = PlanRequest('rule', 'group', paths, selected)
    selectors.clear(); entries.clear(); paths.clear()
    assert req.source_paths == ('src/api.py',) and entry.selectors == ('.env.example',)
    with pytest.raises(FrozenInstanceError): req.rule_id = 'new'


@pytest.mark.parametrize('mutation', ['empty', 'duplicate', 'outside-discovery', 'outside-source', 'duplicate-source', 'outside-binding'])
def test_request_scope_is_exact_and_nonempty(mutation):
    files = [source()]; req = request(files)
    with pytest.raises(ValueError):
        if mutation == 'empty': replace(req, source_paths=())
        elif mutation == 'duplicate': replace(req, source_paths=('src/api.py', 'src/api.py'))
        elif mutation == 'outside-discovery': plan_contracts(replace(req, source_paths=('src/other.py',)), discover_contracts(files))
        elif mutation == 'outside-source': inspect_contract_plan(req, [replace(files[0], path='src/other.py')])
        elif mutation == 'duplicate-source': inspect_contract_plan(req, files + files)
        else:
            selected = DocumentBindings('contract-document-bindings-v1', (DocumentBinding('future', ('future', '1'), ('x',)),))
            inspect_contract_plan(replace(req, bindings=selected), files)


@pytest.mark.parametrize('a,r,expected', [
    ('T','T','T'), ('T','F','F'), ('T','U','U'), ('F','T','T'), ('F','F','T'),
    ('F','U','T'), ('U','T','T'), ('U','F','U'), ('U','U','U'),
])
def test_conditional_truth_table(a, r, expected):
    assert conditional(Truth(a), Truth(r)) == Truth(expected)


@pytest.mark.parametrize('family,added,removed,truth', [
    (ContractFamily.ENV_KEY, [], ['OLD'], Truth.FALSE),
    (ContractFamily.ENV_KEY, ['NEW'], [], Truth.TRUE),
    (ContractFamily.API_ROUTE, [], [('GET','/old')], Truth.TRUE),
    (ContractFamily.API_ROUTE, [], [], Truth.FALSE),
])
def test_family_specific_applicability(family, added, removed, truth):
    delta = ExactDelta(FactBasis('scope', family, 'profile', '1', ('input',)), added, removed)
    assert delta_applicability(delta, family) == truth


def test_open_upper_bound_is_not_no_delta_and_assessment_cannot_lie():
    files = [source()]; req = request(files); discovery = discover_contracts(files)
    scope = next(row for row in contract_scopes(req, discovery) if row.family == ContractFamily.ENV_KEY)
    basis = FactBasis(scope.id, scope.family, *scope.profile_ref, ('input',))
    delta = UnknownDelta(basis, [], None, [], None, (ReasonCode.UNSUPPORTED_BINDING,))
    assert delta_applicability(delta, scope.family) == Truth.UNKNOWN
    with pytest.raises(ValueError, match='contradicts'): ContractAssessment(scope, Truth.FALSE, delta)
    with pytest.raises(ValueError, match='mismatch'): ContractAssessment(replace(scope, request_ref='other'), Truth.UNKNOWN, delta)


@pytest.mark.parametrize('family', ['env-key', None, ContractFamily.API_RESPONSE])
def test_delta_applicability_requires_a_supported_typed_family(family):
    delta = ExactDelta(FactBasis('scope', ContractFamily.ENV_KEY, 'profile', '1', ('input',)), [], [])
    with pytest.raises(ValueError): delta_applicability(delta, family)


def test_express_route_obligation_retains_unsupported_family_guards():
    files = [ChangedFile('src/api.ts', 'modified', before_routes=[('GET', '/old')], after_routes=[('GET', '/new')])]
    selected = DocumentBindings('contract-document-bindings-v1', (
        DocumentBinding('express', ('express-registered-routes', '1'), ('docs/api.md',)),))
    result = inspect_contract_plan(request(files, selected), files, documents('/old'))
    assert len(result.outcomes) == 1 and result.outcomes[0].truth == Truth.FALSE
    assert result.truth == Truth.FALSE and not result.complete_within_selection
    assert {domain.family for domain in result.plan.guards} == {ContractFamily.ENV_KEY, ContractFamily.API_RESPONSE}


def test_added_and_deleted_source_absence_remains_a_legacy_declaration():
    files = [ChangedFile('src/api.py', 'added', after_source=code('/new'))]
    added = inspect_contract_plan(request(files), files, documents('/new'))
    assert outcome(added, ContractFamily.API_ROUTE).obligation.assessment.applicability == Truth.TRUE
    files = [ChangedFile('src/api.py', 'deleted', before_source=code('/old'))]
    deleted = inspect_contract_plan(request(files), files, documents('/new'))
    assert outcome(deleted, ContractFamily.API_ROUTE).truth == Truth.TRUE
    assert outcome(deleted, ContractFamily.ENV_KEY).obligation.assessment.applicability == Truth.FALSE


@pytest.mark.parametrize('state', ['unavailable', 'deleted-without-absence-proof'])
def test_unreadable_or_deleted_document_is_not_known_missing(state):
    files = [source()]
    docs = documents()
    docs[0] = replace(docs[0], status='deleted' if state.startswith('deleted') else 'unchanged',
                      document_input_state='unavailable', after_source=None)
    result = inspect_contract_plan(request(files), files, docs)
    assert outcome(result, ContractFamily.API_ROUTE).requirement == Truth.UNKNOWN
    assert result.truth == Truth.UNKNOWN


def test_duplicate_documents_are_rejected_before_membership_evaluation():
    files = [source()]
    with pytest.raises(ValueError, match='duplicate document'):
        inspect_contract_plan(request(files), files, documents() + documents())


def test_input_order_does_not_change_request_plan_or_result():
    files = [source(), source(before='value = 1\n', after='value = 2\n', path='src/plain.py')]
    a = inspect_contract_plan(request(files), files, documents())
    b = inspect_contract_plan(request(files[::-1]), files[::-1], documents()[::-1])
    assert a.to_dict() == b.to_dict()


def test_relation_request_never_inherits_parent_source_files():
    parent_files = [source(path='src/parent.py'), source(path='src/relation.py')]
    child_files = parent_files[1:]
    req = request(child_files, relation='child-contract')
    result = inspect_contract_plan(req, child_files, documents('/old'))
    assert result.plan.request.source_paths == ('src/relation.py',)
    assert all('src/parent.py' not in row.obligation.assessment.scope.source_paths for row in result.outcomes)
    with pytest.raises(ValueError): inspect_contract_plan(req, parent_files, documents())


def test_actual_legacy_selector_runs_shadow_without_reinterpreting_yaml():
    session = AnalysisSession(); files = [source(after=code('/new', 'NEW'))]
    group = Group('contracts', any_changed=['docs/api.md'], content='auto-strict')
    check = content_requirement(group, files, documents(), session)
    assert check.decision == 'undetermined'  # Old mixed selector remains conservative.
    assert len(session.shadow_contract_plans) == 1
    shadow = session.shadow_contract_plans[0]
    assert shadow.truth == Truth.UNKNOWN
    assert all(row.obligation.binding is None for row in shadow.outcomes)
    assert {row.obligation.assessment.scope.family for row in shadow.outcomes} == {ContractFamily.ENV_KEY, ContractFamily.API_ROUTE}


def test_actual_relation_evaluator_preserves_source_scope_in_shadow():
    session = AnalysisSession()
    files = [source(path='src/parent.py'), source(path='src/relation.py'), *documents()]
    group = Group('contracts', any_changed=['docs/api.md'], content='auto-strict')
    relation = CrossFileRelation('child', ['src/relation.py'], ['contracts'])
    _evaluate_cross_file_relations([relation], [group], files, session)
    assert len(session.shadow_contract_plans) == 1
    assert session.shadow_contract_plans[0].plan.request.source_paths == ('src/relation.py',)


def test_shadow_trace_is_bounded_and_immutable():
    session = AnalysisSession(limit=1); group = Group('contracts', content='auto-strict')
    for path in ('src/first.py', 'src/second.py'):
        content_requirement(group, [source(path=path)], [], session)
    assert isinstance(session.shadow_contract_plans, tuple) and len(session.shadow_contract_plans) == 1
    assert session.shadow_contract_plans[0].plan.request.source_paths == ('src/second.py',)
    with pytest.raises(ValueError): session.record_contract_plan({})


def test_legacy_empty_scope_behavior_is_preserved():
    result = content_requirement(Group('contracts', content='auto-strict'), [], [])
    assert result.verification == 'not-applicable'


def test_serialization_contains_coverage_and_bindings_but_no_raw_source():
    files = [source(before=code(dynamic=True), after=code('/new', dynamic=True))]
    result = inspect_contract_plan(request(files), files, documents('/old'))
    payload = result.to_dict()
    assert payload['truth'] == 'F' and not payload['complete_within_selection']
    assert payload['service_scope_certified'] is False and payload['proof_dag_attached'] is False
    assert payload['open_guards'] and all(row['binding_id'] for row in payload['obligations'])
    assert files[0].after_source not in json.dumps(payload)


@pytest.mark.parametrize('mutation', ['unknown-complete', 'untyped-truth', 'unmapped-success', 'untyped-reason'])
def test_invalid_outcomes_rejected(mutation):
    files = [source()]; result = inspect_contract_plan(request(files), files, documents())
    row = outcome(result, ContractFamily.API_ROUTE)
    with pytest.raises(ValueError):
        if mutation == 'unknown-complete': replace(row, requirement=Truth.UNKNOWN, requirement_complete=True)
        elif mutation == 'untyped-truth': replace(row, requirement='T')
        elif mutation == 'untyped-reason': replace(row, reason_codes=['unmapped_contract_document'])
        else: ObligationOutcome(ContractObligation(row.obligation.assessment, None), Truth.TRUE, True)
