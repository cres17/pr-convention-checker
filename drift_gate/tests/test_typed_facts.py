"""Production interval soundness and legacy compatibility, not parser completeness."""
from dataclasses import FrozenInstanceError, replace
from itertools import combinations, product

import pytest

from drift_gate.core.contracts.delta import compare_facts
from drift_gate.core.evaluation.environment import environment_delta, environment_fact_outcome
from drift_gate.core.evaluation.routes import analyze_route_facts, complete_route_delta
from drift_gate.core.evaluation.static_routers import UnsupportedContract
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.facts import (
    BoundedDelta, BoundedFacts, ContractFamily, ExactDelta, ExactFacts,
    FactBasis, ReasonCode, UnknownDelta, UnknownFacts,
)


def basis(**updates):
    return replace(FactBasis('selected-service', ContractFamily.ENV_KEY, 'env', '1', ('input:base',)), **updates)


def test_exact_empty_is_distinct_from_unknown_empty():
    exact = ExactFacts(basis(), set())
    opaque = UnknownFacts(basis(), set(), (ReasonCode.OPEN_DEPENDENCY_SCOPE,))
    assert exact.must == opaque.must == frozenset()
    assert exact.may == frozenset() and opaque.may is None
    assert isinstance(compare_facts(exact, exact), ExactDelta)
    assert compare_facts(exact, exact).is_empty
    open_delta = compare_facts(opaque, opaque)
    assert isinstance(open_delta, UnknownDelta)
    assert open_delta.added_may is None and open_delta.removed_may is None


def test_constructor_copies_mutable_inputs_and_evidence():
    keys, refs, reasons = {'A'}, ['input:base'], [ReasonCode.UNSUPPORTED_BINDING]
    domain = FactBasis('scope', ContractFamily.ENV_KEY, 'env', '1', refs)
    exact, unknown = ExactFacts(domain, keys), UnknownFacts(domain, keys, reasons)
    keys.add('B'); refs.append('input:modified'); reasons.clear()
    assert exact.facts == unknown.must == frozenset({'A'})
    assert domain.evidence_refs == ('input:base',)
    assert unknown.reasons == (ReasonCode.UNSUPPORTED_BINDING,)
    with pytest.raises(FrozenInstanceError):
        exact.facts = frozenset()


@pytest.mark.parametrize('changes', [{'scope_id': ''}, {'scope_id': 1}, {'family': 'env-key'},
                                    {'profile_id': ' '}, {'profile_version': None},
                                    {'evidence_refs': []}, {'evidence_refs': 'input'},
                                    {'evidence_refs': ['']}, {'evidence_refs': [False]}])
def test_invalid_basis_is_rejected(changes):
    with pytest.raises(ValueError):
        basis(**changes)


@pytest.mark.parametrize('identity', ['lower', '', None, 1, True, ('GET', '/api'), ['A']])
def test_invalid_environment_identity_is_rejected(identity):
    with pytest.raises(ValueError):
        ExactFacts(basis(), [identity])


@pytest.mark.parametrize('identity', ['GET /api', ('get', '/api'), ('GET', 'relative'),
                                     ('CONNECT', '/api'), ('GET', '/api', 'extra'), (True, '/api')])
def test_invalid_route_identity_is_rejected(identity):
    with pytest.raises(ValueError):
        ExactFacts(basis(family=ContractFamily.API_ROUTE), [identity])


@pytest.mark.parametrize('reasons', [(), [], 'missing_source', ['missing_source'], [None]])
def test_unknown_requires_typed_reason_codes(reasons):
    with pytest.raises(ValueError):
        UnknownFacts(basis(), set(), reasons)


def test_inconsistent_bounds_and_certain_delta_overlap_are_rejected():
    with pytest.raises(ValueError):
        BoundedFacts(basis(), {'A'}, set(), (ReasonCode.UNSUPPORTED_BINDING,))
    with pytest.raises(ValueError):
        ExactDelta(basis(), {'A'}, {'A'})
    with pytest.raises(ValueError):
        BoundedDelta(basis(), {'A'}, set(), set(), set(), (ReasonCode.UNSUPPORTED_BINDING,))
    with pytest.raises(ValueError):
        UnknownDelta(basis(), {'A'}, None, {'A'}, None, (ReasonCode.UNSUPPORTED_BINDING,))
    with pytest.raises(ValueError):
        UnknownDelta(basis(), set(), set(), set(), set(), (ReasonCode.UNSUPPORTED_BINDING,))


@pytest.mark.parametrize('changes', [{'scope_id': 'other'}, {'profile_id': 'other'}, {'profile_version': '2'}])
def test_cross_domain_comparison_is_rejected(changes):
    with pytest.raises(ValueError):
        compare_facts(ExactFacts(basis(), set()), ExactFacts(basis(**changes), set()))


def test_cross_family_comparison_is_rejected():
    with pytest.raises(ValueError):
        compare_facts(ExactFacts(basis(), set()), ExactFacts(basis(family=ContractFamily.API_ROUTE), set()))


def test_invalid_untyped_comparison_is_rejected():
    with pytest.raises(ValueError):
        compare_facts(set(), ExactFacts(basis(), set()))


def test_evidence_and_reasons_are_preserved_deterministically():
    before = UnknownFacts(basis(evidence_refs=('z', 'a')), {'A'}, (ReasonCode.UNSUPPORTED_BINDING,))
    after = BoundedFacts(basis(evidence_refs=('b', 'a')), {'B'}, {'B', 'C'}, (ReasonCode.RESOURCE_LIMIT,))
    delta = compare_facts(before, after)
    assert delta.basis.evidence_refs == ('a', 'b', 'z')
    assert delta.reasons == (ReasonCode.RESOURCE_LIMIT, ReasonCode.UNSUPPORTED_BINDING)
    assert delta.added_must == set() and delta.added_may == {'B', 'C'}
    assert delta.removed_must == {'A'} and delta.removed_may is None


def subsets():
    return [frozenset(items) for size in range(4) for items in combinations(('A', 'B', 'C'), size)]


def test_finite_production_delta_bounds_are_sound_for_every_concrete_pair():
    values = subsets()
    observations = [ExactFacts(basis(), value) for value in values]
    observations += [BoundedFacts(basis(), low, high, (ReasonCode.OPEN_DEPENDENCY_SCOPE,))
                     for low in values for high in values if low < high]
    observations += [UnknownFacts(basis(), value, (ReasonCode.UNSUPPORTED_BINDING,)) for value in values]
    for before, after in product(observations, repeat=2):
        delta = compare_facts(before, after)
        old_worlds = [v for v in values if before.must <= v and (before.may is None or v <= before.may)]
        new_worlds = [v for v in values if after.must <= v and (after.may is None or v <= after.may)]
        for old, new in product(old_worlds, new_worlds):
            added, removed = new - old, old - new
            if isinstance(delta, ExactDelta):
                assert added == delta.added and removed == delta.removed
            else:
                assert delta.added_must <= added and delta.removed_must <= removed
                assert delta.added_may is None or added <= delta.added_may
                assert delta.removed_may is None or removed <= delta.removed_may


def test_equal_lower_sets_cannot_prove_no_delta():
    observation = BoundedFacts(basis(), set(), {'A'}, (ReasonCode.OPEN_DEPENDENCY_SCOPE,))
    delta = compare_facts(observation, observation)
    assert isinstance(delta, BoundedDelta)
    assert delta.added_must == delta.removed_must == set()
    assert delta.added_may == delta.removed_may == {'A'}


@pytest.mark.parametrize('source,fragment,expected,keys', [
    ('import os\nvalue = os.getenv("KNOWN")\n', False, ExactFacts, {'KNOWN'}),
    ('import os\nvalue = os.getenv("KNOWN")\nother = os.getenv(key)\n', False, UnknownFacts, {'KNOWN'}),
    ('import os\nos.getenv = custom\nvalue = os.getenv("KNOWN")\n', False, UnknownFacts, set()),
    ('import os\nvalue = os.getenv("KNOWN")\n', True, UnknownFacts, set()),
    (None, False, UnknownFacts, set()),
    ('invalid Python !', False, UnknownFacts, set()),
])
def test_environment_wrapper_retains_only_sound_complete_source_facts(source, fragment, expected, keys):
    result = environment_fact_outcome(source, scope_id='module', evidence_ref='snapshot:module', fragment=fragment)
    assert isinstance(result, expected) and result.must == keys
    if fragment:
        assert result.reasons == (ReasonCode.PATCH_ONLY,)


def python_route(path):
    return f'from fastapi import FastAPI\napp = FastAPI()\n@app.get("{path}")\ndef endpoint(): return {{}}\n'


@pytest.mark.parametrize('status,before,after,expected', [
    ('modified', python_route('/old'), python_route('/new'), ({('GET', '/new')}, {('GET', '/old')})),
    ('added', None, python_route('/new'), ({('GET', '/new')}, set())),
    ('deleted', python_route('/old'), None, (set(), {('GET', '/old')})),
    ('modified', python_route('/old'), python_route('/old'), (set(), set())),
])
def test_actual_route_compatibility_api_uses_typed_facts(status, before, after, expected):
    file = ChangedFile('api.py', status, before_source=before, after_source=after)
    pair = analyze_route_facts([file])
    assert isinstance(pair.before, ExactFacts) and isinstance(pair.after, ExactFacts)
    assert complete_route_delta([file]) == expected
    assert pair.before.basis.profile_id == 'legacy-complete-routes'
    assert pair.before.basis.scope_id.startswith('selected-modules:')


@pytest.mark.parametrize('file,reason', [
    (ChangedFile('api.py', 'modified'), ReasonCode.MISSING_SOURCE),
    (ChangedFile('api.py', 'modified', before_source=python_route('/old'), after_source='broken !'), ReasonCode.UNSUPPORTED_BINDING),
    (ChangedFile('api.ts', 'modified', route_analysis_error='type-only binding'), ReasonCode.UNSUPPORTED_BINDING),
])
def test_unavailable_route_inputs_stay_unknown_and_legacy_api_raises(file, reason):
    pair = analyze_route_facts([file])
    assert isinstance(pair.before, UnknownFacts) and isinstance(pair.after, UnknownFacts)
    assert pair.before.reasons == pair.after.reasons == (reason,)
    with pytest.raises(UnsupportedContract, match=pair.diagnostic):
        complete_route_delta([file])


def test_duplicate_route_scope_remains_unknown():
    file = ChangedFile('api.py', 'modified', before_source=python_route('/old'), after_source=python_route('/new'))
    pair = analyze_route_facts([file, replace(file, path='other.py')])
    assert isinstance(pair.before, UnknownFacts)
    assert pair.diagnostic == 'duplicate route identity across modules'


def test_express_adapter_evidence_is_not_misrepresented_as_source_hash():
    file = ChangedFile('api.ts', 'modified', before_routes=[('GET', '/old')], after_routes=[('GET', '/new')])
    pair = analyze_route_facts([file])
    assert all('adapter-route-facts' in ref for ref in pair.before.basis.evidence_refs)
    assert complete_route_delta([file]) == ({('GET', '/new')}, {('GET', '/old')})


def test_environment_legacy_global_key_movement_does_not_create_new_duty():
    code = 'import os\nvalue = os.getenv("KNOWN")\n'
    files = [ChangedFile('one.py', 'modified', before_source=code, after_source=''),
             ChangedFile('two.py', 'modified', before_source='', after_source=code)]
    legacy = environment_delta(files)
    assert not legacy.keys and not legacy.uncertain
