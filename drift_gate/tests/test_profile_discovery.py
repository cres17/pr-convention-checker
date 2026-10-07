"""Discovery cannot erase open domains or treat hints as policy obligations."""
from dataclasses import FrozenInstanceError, replace
import json

import pytest

from drift_gate.adapters.ast.express_routes import attach_express_routes
from drift_gate.core.contracts.discovery import (
    DiscoveryDomain, DiscoveryResult, DiscoveryState, discover_contracts,
)
from drift_gate.core.contracts.profiles import DEFAULT_REGISTRY, ProfileRegistry
from drift_gate.core.engine import run
from drift_gate.core.evaluation.analysis_session import AnalysisSession
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.facts import ContractFamily, ExactFacts, FactBasis, ReasonCode
from drift_gate.tests.test_express_contracts import fixture
from drift_gate.tests.test_logical_contracts import changed, document, policy, source


def domain(result, family, path='src/api.py'):
    return next(item for item in result.domains if item.family == family and item.source_path == path)


def plain_api():
    return 'from fastapi import FastAPI\napp = FastAPI()\n@app.get("/old")\ndef endpoint(): return {}\n'


def profile():
    return DEFAULT_REGISTRY.find('python', ContractFamily.ENV_KEY)


def test_registry_copies_inputs_and_resolves_explicit_profiles():
    languages = ['python']
    requirements = ['complete-input']
    selected = replace(profile(), languages=languages, input_requirements=requirements)
    entries = [selected]
    registry = ProfileRegistry(entries)
    languages.append('go'); requirements.clear(); entries.clear()
    assert selected.languages == ('python',) and selected.input_requirements == ('complete-input',)
    assert registry.find('python', ContractFamily.ENV_KEY) is selected
    assert registry.find('go', ContractFamily.ENV_KEY) is None
    with pytest.raises(FrozenInstanceError):
        selected.version = '2'


@pytest.mark.parametrize('changes', [
    {'id': ''}, {'version': None}, {'family': 'env-key'}, {'content_mode': 'api-schema'},
    {'languages': []}, {'languages': 'python'}, {'languages': [False]},
    {'analyzer_key': ''}, {'analysis_boundary': ' '}, {'input_requirements': []},
])
def test_invalid_profile_declarations_are_rejected(changes):
    with pytest.raises(ValueError):
        replace(profile(), **changes)


@pytest.mark.parametrize('entries', [[], [None], [profile(), profile()],
                                   [profile(), replace(profile(), version='2')]])
def test_registry_rejects_empty_duplicate_and_ambiguous_selection(entries):
    with pytest.raises(ValueError):
        ProfileRegistry(entries)


@pytest.mark.parametrize('language,family', [('', ContractFamily.ENV_KEY),
                                          ('python', 'env-key'), (None, ContractFamily.ENV_KEY)])
def test_profile_lookup_rejects_untyped_input(language, family):
    with pytest.raises(ValueError):
        DEFAULT_REGISTRY.find(language, family)


def test_response_profile_does_not_admit_identity_sets_as_shape_facts():
    selected = FactBasis('scope', ContractFamily.API_RESPONSE, 'response', '1', ('input',))
    with pytest.raises(ValueError, match='dedicated fact model'):
        ExactFacts(selected, set())


def test_all_declared_families_are_retained_in_mixed_contract_scope():
    code = plain_api() + 'import os\nvalue = os.getenv("EXISTING")\n'
    result = discover_contracts([changed(before=code, after=code.replace('/old', '/new'))])
    assert len(result.domains) == 3 and result.complete_within_selection
    assert {item.family for item in result.candidates} == {ContractFamily.API_ROUTE, ContractFamily.ENV_KEY}
    assert set(result.legacy_modes) == {'api-routes', 'env-keys'}
    assert domain(result, ContractFamily.API_RESPONSE).state == DiscoveryState.CLOSED
    assert not domain(result, ContractFamily.API_RESPONSE).activated


def test_schema_and_route_candidates_do_not_subsume_each_other():
    result = discover_contracts([changed()])
    assert result.complete_within_selection
    assert {item.family for item in result.candidates} == {ContractFamily.API_ROUTE, ContractFamily.API_RESPONSE}
    assert set(result.legacy_modes) == {'api-routes', 'api-schema'}
    assert {item.profile_ref for item in result.candidates} == {('python-fastapi-routes', '1'), ('python-response-primitives', '2')}


@pytest.mark.parametrize('code', [
    'from fastapi import FastAPI\n',
    'message = "@app.get(\'/fake\', response_model=Model) os.getenv(\'FAKE\')"\n',
    '# @app.get("/fake", response_model=Model)\n# os.getenv("FAKE")\n',
    'value = 1\n',
])
def test_unused_import_strings_and_comments_do_not_invent_candidates(code):
    result = discover_contracts([changed(before=code, after=code)])
    assert result.complete_within_selection and not result.candidates and not result.legacy_modes


@pytest.mark.parametrize('code', [
    'import os\nvalue = os.getenv(name)\n',
    'import os\nos.getenv = custom\nvalue = os.getenv("KNOWN")\n',
    'from os import getenv as read\nvalue = read(name)\n',
])
def test_unresolved_env_has_its_own_open_domain(code):
    result = discover_contracts([changed(before=code, after=code)])
    selected = domain(result, ContractFamily.ENV_KEY)
    assert selected.state == DiscoveryState.OPEN and selected.activated
    assert selected.reasons == (ReasonCode.UNSUPPORTED_BINDING,)
    assert domain(result, ContractFamily.API_ROUTE).state == DiscoveryState.CLOSED
    assert not result.complete_within_selection


@pytest.mark.parametrize('code', [
    'from external import app\n@app.get("/external")\ndef endpoint(): return {}\n',
    'from fastapi import FastAPI as Api\napp = Api()\n@app.get("/alias")\ndef endpoint(): return {}\n',
    'from fastapi import FastAPI\napp = FastAPI()\nregister(app)\n',
])
def test_opaque_registration_is_open_even_without_response_model(code):
    result = discover_contracts([changed(before=code, after=code)])
    assert domain(result, ContractFamily.API_ROUTE).state == DiscoveryState.OPEN
    assert domain(result, ContractFamily.API_ROUTE).activated
    assert domain(result, ContractFamily.API_RESPONSE).state == DiscoveryState.OPEN
    assert not result.complete_within_selection


def test_local_unknown_response_keeps_route_domain_closed():
    code = source('id: list[int]')
    result = discover_contracts([changed(before=code, after=code)])
    assert domain(result, ContractFamily.API_ROUTE).state == DiscoveryState.CLOSED
    assert domain(result, ContractFamily.API_RESPONSE).state == DiscoveryState.OPEN
    assert ContractFamily.API_RESPONSE in {item.family for item in result.candidates}


@pytest.mark.parametrize('status,before,after', [
    ('added', None, plain_api()), ('deleted', plain_api(), None),
])
def test_declared_add_delete_absence_does_not_require_missing_side(status, before, after):
    file = ChangedFile('src/api.py', status, before_source=before, after_source=after)
    result = discover_contracts([file])
    assert result.complete_within_selection
    assert domain(result, ContractFamily.API_ROUTE).activated
    assert not result.legacy_python_error


@pytest.mark.parametrize('before,after,error', [
    (None, plain_api(), 'complete before/after'),
    (plain_api(), None, 'complete before/after'),
    (plain_api(), 'broken !', 'could not be parsed'),
])
def test_partial_or_invalid_source_opens_every_requested_domain(before, after, error):
    file = ChangedFile('src/api.py', 'modified', before_source=before, after_source=after)
    result = discover_contracts([file])
    assert len(result.open_domains) == 3 and not result.complete_within_selection
    assert error in result.legacy_python_error
    assert domain(result, ContractFamily.API_ROUTE).activated  # The valid side is retained.


@pytest.mark.parametrize('extension', ['go', 'java', 'rb', 'kt', 'txt'])
def test_unsupported_language_is_not_vacuous_closed_discovery(extension):
    file = ChangedFile('src/api.' + extension, 'modified', before_source='', after_source='code')
    result = discover_contracts([file])
    assert len(result.open_domains) == 3 and not result.complete_within_selection
    assert not result.candidates
    assert all(item.reasons == (ReasonCode.UNSUPPORTED_PROFILE,) for item in result.domains)


@pytest.mark.parametrize('extension', ['js', 'jsx', 'ts', 'tsx'])
def test_express_complete_route_does_not_claim_env_or_schema_support(extension):
    file = ChangedFile('src/api.' + extension, 'modified', before_source=fixture(), after_source=fixture())
    result = discover_contracts(attach_express_routes([file]))
    assert domain(result, ContractFamily.API_ROUTE, file.path).state == DiscoveryState.CLOSED
    assert domain(result, ContractFamily.API_ROUTE, file.path).activated
    assert {item.family for item in result.open_domains} == {ContractFamily.ENV_KEY, ContractFamily.API_RESPONSE}
    assert not result.complete_within_selection
    payload = result.to_dict()
    assert payload['service_scope_certified'] is False
    assert fixture() not in json.dumps(payload)


def test_explicit_route_only_selection_is_complete_in_its_declared_subset():
    file = ChangedFile('src/api.ts', 'modified', before_routes=[('GET', '/old')], after_routes=[('GET', '/new')])
    result = discover_contracts([file], families=(ContractFamily.API_ROUTE,))
    assert result.complete_within_selection and len(result.domains) == 1


@pytest.mark.parametrize('rows,error', [
    (None, ''), ([('get', '/old')], ''), ([('GET', '/old'), ('GET', '/old')], ''),
    ([('GET', '/old')], 'type-only import'),
])
def test_missing_invalid_or_opaque_express_facts_are_open(rows, error):
    file = ChangedFile('src/api.ts', 'modified', before_routes=rows, after_routes=rows, route_analysis_error=error)
    result = discover_contracts([file])
    assert domain(result, ContractFamily.API_ROUTE, file.path).state == DiscoveryState.OPEN


@pytest.mark.parametrize('changes', [{'id': 'custom'}, {'version': 'future'}, {'analyzer_key': 'unknown-analyzer'}])
def test_registry_metadata_cannot_install_or_certify_unknown_analyzer(changes):
    registry = ProfileRegistry((replace(profile(), **changes),))
    result = discover_contracts([changed()], registry=registry)
    assert len(result.open_domains) == 3
    assert all(item.reasons == (ReasonCode.UNSUPPORTED_PROFILE,) for item in result.domains)


def test_missing_profile_is_open_and_never_dropped():
    registry = ProfileRegistry((profile(),))
    result = discover_contracts([changed()], registry=registry)
    assert {item.family for item in result.open_domains} == {ContractFamily.API_ROUTE, ContractFamily.API_RESPONSE}


def test_empty_input_has_no_completeness_certificate():
    result = discover_contracts([])
    assert not result.domains and not result.complete_within_selection


@pytest.mark.parametrize('families', [[], None, ['env-key'], 'env-key'])
def test_invalid_family_selection_is_rejected(families):
    with pytest.raises(ValueError):
        discover_contracts([changed()], families=families)


def test_duplicate_input_scope_is_rejected():
    with pytest.raises(ValueError, match='duplicate source paths'):
        discover_contracts([changed(), changed()])


def test_result_rejects_omitted_file_or_family_domain():
    result = discover_contracts([changed()])
    with pytest.raises(ValueError, match='omitted'):
        replace(result, domains=result.domains[:-1])
    with pytest.raises(ValueError, match='omitted'):
        replace(result, source_paths=('src/api.py', 'src/missing.py'))


def test_reordering_scopes_does_not_change_discovery():
    files = [changed(), replace(changed(), path='src/other.py')]
    assert discover_contracts(files).to_dict() == discover_contracts(files[::-1]).to_dict()


def test_cache_reuses_parsers_without_reusing_other_file_scope(monkeypatch):
    import drift_gate.core.contracts.discovery as module
    calls = {'route': 0, 'response': 0}
    original_route, original_response = module.extract_routes, module._extract_contracts

    def route(text):
        calls['route'] += 1
        return original_route(text)

    def response(text):
        calls['response'] += 1
        return original_response(text)

    monkeypatch.setattr(module, 'extract_routes', route)
    monkeypatch.setattr(module, '_extract_contracts', response)
    text = source()
    files = [changed(before=text, after=text), replace(changed(before=text, after=text), path='src/other.py')]
    result = discover_contracts(files, session=AnalysisSession())
    assert calls == {'route': 1, 'response': 1}
    assert {item.scope_id for item in result.domains} == {'selected-module:src/api.py', 'selected-module:src/other.py'}


def test_strict_auto_consumes_discovery_compatibility_hints(monkeypatch):
    import drift_gate.core.contracts.discovery as module
    original = module.discover_contracts
    seen = []

    def capture(files, **kwargs):
        result = original(files, **kwargs)
        seen.append(result)
        return result

    monkeypatch.setattr(module, 'discover_contracts', capture)
    result = run([changed(), document()], policy=policy(mode='auto-strict'))
    assert seen and any(ContractFamily.API_RESPONSE == item.family for item in seen[0].candidates)
    assert result.result == 'pass' and result.verification == 'verified'


def test_mixed_legacy_gate_remains_unknown_while_discovery_retains_both_candidates():
    text = plain_api() + 'import os\nvalue = os.getenv("KNOWN")\n'
    file = changed(before=text, after=text.replace('/old', '/new'))
    discovery = discover_contracts([file])
    assert set(discovery.legacy_modes) == {'env-keys', 'api-routes'}
    result = run([file, document()], policy=policy(mode='auto-strict', action='warn'))
    assert result.result == 'warn' and result.verification == 'unverified'


@pytest.mark.parametrize('changes', [
    {'state': 'closed'}, {'family': 'env-key'}, {'activated': 1}, {'profile_ref': None},
    {'profile_ref': ('', '1')}, {'evidence_refs': []}, {'evidence_refs': ['']},
    {'state': DiscoveryState.OPEN}, {'reasons': [ReasonCode.UNSUPPORTED_BINDING]},
])
def test_invalid_discovery_domains_are_rejected(changes):
    selected = DiscoveryDomain('src/file.py', ContractFamily.ENV_KEY, profile().ref,
                               DiscoveryState.CLOSED, False, ('input',))
    with pytest.raises(ValueError):
        replace(selected, **changes)


def test_discovery_result_and_domains_copy_mutable_inputs():
    refs = ['input']
    selected = DiscoveryDomain('src/file.py', ContractFamily.ENV_KEY, profile().ref,
                               DiscoveryState.CLOSED, False, refs)
    domains, paths, families = [selected], ['src/file.py'], [ContractFamily.ENV_KEY]
    result = DiscoveryResult(domains, paths, families)
    refs.clear(); domains.clear(); paths.clear(); families.clear()
    assert selected.evidence_refs == ('input',)
    assert len(result.domains) == len(result.source_paths) == len(result.requested_families) == 1
