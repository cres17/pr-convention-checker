"""Logical consistency controls, independent truth oracle and adversarial IR."""
from dataclasses import asdict, replace
from itertools import product
import json

import pytest

from drift_gate.core.contracts.discovery import discover_contracts
from drift_gate.core.contracts.planner import DocumentBindings, PlanRequest, Truth, plan_contracts
from drift_gate.core.evaluation.contract_proof import inspect_contract_proof
from drift_gate.core.evaluation.obligations import evaluate_contract_plan, inspect_contract_plan
from drift_gate.core.evaluation.propositions import build_proof
from drift_gate.core.evaluation.result_guard import ResultValidationError, validate_proof_evaluation, validate_proof_payload
from drift_gate.core.models.proof import (
    CoverageDomain, EvidenceClaim, NodeSpec, Operator, ProofContext, Proposition, ScopeCoverage,
)
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.facts import ContractFamily
from drift_gate.tests.test_obligation_planner import code, documents, request, source


def context(values, operator=Operator.ALL, *, specs=None, root='root'):
    atoms = tuple(Proposition(name, value, (name,), ('e:' + name,) if value != Truth.UNKNOWN else (),
                              assumptions=('test-observation',)) for name, value in values.items())
    claims = tuple(EvidenceClaim('e:' + name, name, value, (name,))
                   for name, value in values.items() if value != Truth.UNKNOWN)
    domains = tuple(CoverageDomain(name, value != Truth.UNKNOWN,
                    ('analysis_open',) if value == Truth.UNKNOWN else ()) for name, value in values.items())
    specs = specs or tuple(NodeSpec(name, Operator.ATOM, proposition_ref=name) for name in values) + (
        NodeSpec(root, operator, tuple(values)),)
    return ProofContext('test-scope', 'test-input', domains, atoms, claims, (), specs, root)


def evaluate(ctx, **kwargs):
    result = build_proof(ctx, ctx.structure, ctx.root_ref, **kwargs)
    validate_proof_evaluation(result, ctx, **kwargs)
    return result


def root(result):
    return next(node for node in result.nodes if node.id == result.root_ref)


def oracle(operator, a, b=None):
    if operator == Operator.NOT:
        return {'T':'F', 'F':'T', 'U':'U'}[a]
    if operator == Operator.CONDITIONAL:
        return {('T','T'):'T', ('T','F'):'F', ('T','U'):'U', ('F','T'):'T',
                ('F','F'):'T', ('F','U'):'T', ('U','T'):'T', ('U','F'):'U', ('U','U'):'U'}[a,b]
    if operator == Operator.ALL:
        return 'F' if 'F' in (a,b) else 'T' if (a,b) == ('T','T') else 'U'
    return 'T' if 'T' in (a,b) else 'F' if (a,b) == ('F','F') else 'U'


@pytest.mark.parametrize('operator,a,b', list(product((Operator.ALL, Operator.ANY, Operator.CONDITIONAL), Truth, Truth)))
def test_exhaustive_binary_truth_tables(operator, a, b):
    ctx = context({'a':a, 'b':b}, operator); node = root(evaluate(ctx))
    assert node.truth.value == oracle(operator, a.value, b.value)
    assert node.decision_proven == (node.truth != Truth.UNKNOWN)
    assert node.coverage.open_domains == tuple(name for name, value in {'a':a,'b':b}.items() if value == Truth.UNKNOWN)


@pytest.mark.parametrize('value', list(Truth))
def test_not_table(value):
    assert root(evaluate(context({'a':value}, Operator.NOT))).truth.value == oracle(Operator.NOT,value.value)


def test_shared_atom_does_not_use_classical_excluded_middle():
    specs = (NodeSpec('a',Operator.ATOM,proposition_ref='a'), NodeSpec('neg',Operator.NOT,('a',)),
             NodeSpec('root',Operator.ANY,('a','neg')))
    result = evaluate(context({'a':Truth.UNKNOWN}, specs=specs))
    assert root(result).truth == Truth.UNKNOWN and root(result).proof_ref is None
    assert root(result).coverage.open_domains == ('a',)


@pytest.mark.parametrize('value', list(Truth))
def test_shared_conditional_atom_keeps_kleene_semantics(value):
    specs = (NodeSpec('a',Operator.ATOM,proposition_ref='a'), NodeSpec('root',Operator.CONDITIONAL,('a','a')))
    assert root(evaluate(context({'a':value}, specs=specs))).truth.value == oracle(Operator.CONDITIONAL,value.value,value.value)


@pytest.mark.parametrize('operator,value', list(product((Operator.ALL,Operator.ANY),Truth)))
def test_repeated_shared_child_has_one_witness_reference(operator,value):
    specs=(NodeSpec('a',Operator.ATOM,proposition_ref='a'),NodeSpec('root',operator,('a','a')))
    node=root(evaluate(context({'a':value},specs=specs)))
    assert node.truth == value
    assert node.sufficient_witness_refs == (() if value == Truth.UNKNOWN else ('a',))


@pytest.mark.parametrize('operator,values,truth', [
    (Operator.ALL,{'a':Truth.FALSE,'b':Truth.UNKNOWN},Truth.FALSE),
    (Operator.ANY,{'a':Truth.TRUE,'b':Truth.UNKNOWN},Truth.TRUE),
])
def test_decisive_witness_preserves_unused_unknown_coverage(operator, values, truth):
    result = evaluate(context(values,operator)); node = root(result)
    assert node.truth == truth and node.decision_proven
    assert node.sufficient_witness_refs == ('a',) and node.coverage.open_domains == ('b',)
    assert not node.coverage.complete


def witness_atoms(result, ref):
    nodes = {node.id:node for node in result.nodes}; node = nodes[ref]
    if node.spec.operator == Operator.ATOM: return {node.spec.proposition_ref}
    return {atom for child in node.sufficient_witness_refs for atom in witness_atoms(result,child)}


def bool_eval(specs, ref, assignments):
    spec = {row.id:row for row in specs}[ref]
    if spec.operator == Operator.ATOM: return assignments[spec.proposition_ref]
    values = [bool_eval(specs,child,assignments) for child in spec.children]
    if spec.operator == Operator.NOT: return not values[0]
    if spec.operator == Operator.CONDITIONAL: return not values[0] or values[1]
    return all(values) if spec.operator == Operator.ALL else any(values)


@pytest.mark.parametrize('values', list(product(Truth, repeat=3)))
def test_nested_witnesses_suffice_under_all_unused_leaf_completions(values):
    specs = tuple(NodeSpec(name,Operator.ATOM,proposition_ref=name) for name in 'abc') + (
        NodeSpec('neg',Operator.NOT,('a',)), NodeSpec('left',Operator.ANY,('neg','b')),
        NodeSpec('right',Operator.CONDITIONAL,('b','c')), NodeSpec('root',Operator.ALL,('left','right')))
    assigned = dict(zip('abc',values)); ctx = context(assigned,specs=specs); result = evaluate(ctx)
    node = root(result)
    if node.truth == Truth.UNKNOWN:
        assert node.sufficient_witness_refs == (); return
    witnesses = witness_atoms(result,result.root_ref)
    possibilities = [(assigned[name] == Truth.TRUE,) if name in witnesses else (False,True) for name in 'abc']
    for completion in product(*possibilities):
        assert bool_eval(specs,'root',dict(zip('abc',completion))) == (node.truth == Truth.TRUE)


def replace_node(result, ref, **changes):
    return replace(result,nodes=tuple(replace(node,**changes) if node.id == ref else node for node in result.nodes))


@pytest.mark.parametrize('mutation', ['truth','proven','proof','witness','coverage','unknown-proof',
    'root','context','node-omitted','structure','narrow-evidence','bad-evidence','bad-profile','atom-conflict'])
def test_adversarial_results_rejected(mutation):
    ctx = context({'a':Truth.FALSE,'b':Truth.UNKNOWN}); result = evaluate(ctx)
    if mutation == 'truth': result=replace_node(result,'root',truth=Truth.TRUE)
    elif mutation == 'proven': result=replace_node(result,'root',decision_proven=False)
    elif mutation == 'proof': result=replace_node(result,'root',proof_ref='a')
    elif mutation == 'witness': result=replace_node(result,'root',sufficient_witness_refs=('b',))
    elif mutation == 'coverage': result=replace_node(result,'root',coverage=ScopeCoverage('test-scope',('a',),()))
    elif mutation == 'unknown-proof': result=replace_node(result,'b',decision_proven=True,proof_ref='b')
    elif mutation == 'root': result=replace(result,root_ref='a')
    elif mutation == 'context': result=replace(result,context_ref='other')
    elif mutation == 'node-omitted': result=replace(result,nodes=result.nodes[:-1])
    elif mutation == 'structure': result=replace_node(result,'root',spec=NodeSpec('root',Operator.ANY,('a','b')))
    elif mutation == 'narrow-evidence': ctx=replace(ctx,evidence=(replace(ctx.evidence[0],covered_domains=()),))
    elif mutation == 'bad-evidence': ctx=replace(ctx,propositions=(replace(ctx.propositions[0],evidence_refs=('missing',)),ctx.propositions[1]))
    elif mutation == 'bad-profile': ctx=replace(ctx,profile_refs=(('future','1'),))
    else: ctx=replace(ctx,evidence=(replace(ctx.evidence[0],truth=Truth.TRUE),))
    with pytest.raises(ResultValidationError): validate_proof_evaluation(result,ctx)


@pytest.mark.parametrize('case', ['cycle','missing-child','not-arity','conditional-arity','duplicate-atom','scope-omitted','unreachable'])
def test_invalid_structures_never_generate_a_success(case):
    base=[NodeSpec('a',Operator.ATOM,proposition_ref='a')]
    if case == 'cycle': specs=base+[NodeSpec('root',Operator.ALL,('root','a'))]
    elif case == 'missing-child': specs=base+[NodeSpec('root',Operator.ALL,('missing','a'))]
    elif case == 'not-arity': specs=base+[NodeSpec('root',Operator.NOT,())]
    elif case == 'conditional-arity': specs=base+[NodeSpec('root',Operator.CONDITIONAL,('a',))]
    elif case == 'duplicate-atom': specs=base+[NodeSpec('duplicate',Operator.ATOM,proposition_ref='a'),NodeSpec('root',Operator.ALL,('a','duplicate'))]
    elif case == 'scope-omitted': specs=base+[NodeSpec('root',Operator.ALL,())]
    else: specs=base+[NodeSpec('unused',Operator.ALL,()),NodeSpec('root',Operator.ALL,('a',))]
    ctx=context({'a':Truth.TRUE},specs=specs)
    with pytest.raises(ResultValidationError): evaluate(ctx)


def test_node_and_depth_budgets_include_shared_subgraphs():
    specs=[NodeSpec('a',Operator.ATOM,proposition_ref='a')]
    specs.extend(NodeSpec(str(i),Operator.NOT,('a' if i == 0 else str(i-1),)) for i in range(7))
    specs.append(NodeSpec('root',Operator.ALL,('a','6')))
    ctx=context({'a':Truth.TRUE},specs=specs)
    evaluate(ctx,max_depth=9,max_nodes=9)
    for limits in ({'max_nodes':8},{'max_depth':8},{'max_edges':8}):
        with pytest.raises(ResultValidationError): evaluate(ctx,**limits)


def test_deterministic_shared_graph_and_premise_serialization():
    ctx=context({'b':Truth.FALSE,'a':Truth.FALSE}); result=evaluate(ctx)
    reordered=replace(ctx,domains=list(reversed(ctx.domains)),propositions=list(reversed(ctx.propositions)),
                      structure=list(reversed(ctx.structure)),evidence=list(reversed(ctx.evidence)))
    assert evaluate(reordered).to_dict() == result.to_dict()
    assert root(result).sufficient_witness_refs == ('a',)
    json.dumps(asdict(ctx),allow_nan=False); json.dumps(result.to_dict(),allow_nan=False)


def test_old_plan_cannot_be_evaluated_against_new_content_or_mutated_route_observations():
    old=[source(after=code())]; initial=inspect_contract_plan(request(old),old,documents('/old'))
    evaluate_contract_plan(initial.plan,old,documents('/old'))
    with pytest.raises(ValueError,match='differ from plan'):
        evaluate_contract_plan(initial.plan,[source(after=code('/new'))],documents('/old'))
    assert inspect_contract_plan(request(old),[source(after=code('/new'))],documents('/old')).truth == Truth.FALSE
    for field,value in [('before_source',code('/different')),('status','added'),('before_routes',[('GET','/fake')]),('route_analysis_error','error')]:
        with pytest.raises(ValueError,match='differ from plan'):
            evaluate_contract_plan(initial.plan,[replace(old[0],**{field:value})],documents('/old'))


@pytest.mark.parametrize('state,expected', [('',Truth.UNKNOWN),('unavailable',Truth.UNKNOWN),('missing',Truth.FALSE)])
def test_deleted_env_document_retained_keys_are_never_positive_evidence(state,expected):
    files=[source(before=code(key='OLD'),after=code(key='NEW'))]
    result=inspect_contract_proof(request(files),files,[ChangedFile('.env.example','deleted',documented_env_keys=['NEW'],document_input_state=state)])
    assert result.root.truth == expected
    result.to_dict()


def test_inactive_declared_families_remain_distinct_in_serialized_scope():
    files=[source(before='x=1',after='x=2')]
    req=PlanRequest('review','scope',('src/api.py',),DocumentBindings('contract-document-bindings-v1'))
    outputs=[]
    for family in (ContractFamily.API_ROUTE,ContractFamily.ENV_KEY):
        discovery=discover_contracts(files,families=(family,))
        outputs.append(evaluate_contract_plan(plan_contracts(req,discovery),files,[]).to_dict())
    assert outputs[0] != outputs[1]
    assert all(row['truth'] == 'T' and row['complete_within_selection'] for row in outputs)


@pytest.mark.parametrize('stale,truth', [(True,Truth.FALSE),(False,Truth.UNKNOWN)])
def test_contract_proof_keeps_known_false_and_mandatory_open_guards(stale,truth):
    files=[source(),ChangedFile('src/opaque.go','modified',before_source='package api',after_source='package api')]
    result=inspect_contract_proof(request(files),files,documents('/old' if stale else '/new'))
    assert result.root.truth == truth and not result.root.coverage.complete
    output=result.to_dict()
    assert output['decision_proven'] == stale and output['proof_dag_attached']
    assert not output['proof']['source_authenticity_verified'] and not output['proof']['current_head_certified']
    assert {ref for ref in result.root.coverage.open_domains if ref.startswith('discovery:src/opaque.go:')}
    assert len(output['discovery']['domains']) == 6


def test_no_delta_skips_document_duty_but_preserves_discovery_scope():
    files=[source(after=code())]; result=inspect_contract_proof(request(files),files)
    assert result.root.truth == Truth.TRUE and result.root.coverage.complete
    assert not any(ref.startswith('requirement:') for ref in result.root.coverage.closed_domains)
    assert len(result.evaluation.plan.discovery.domains) == 3


def test_contract_envelope_refuses_substituted_context_or_missing_guard():
    files=[source(),ChangedFile('src/opaque.go','modified')]
    result=inspect_contract_proof(request(files),files,documents('/old'))
    with pytest.raises(ResultValidationError): replace(result,context=replace(result.context,input_ref='other')).to_dict()
    altered=replace_node(result.proof,result.proof.root_ref,coverage=ScopeCoverage(result.context.scope_ref,result.root.coverage.closed_domains,()))
    with pytest.raises(ResultValidationError): replace(result,proof=altered).to_dict()


def test_shadow_session_records_validated_proof_and_same_legacy_result():
    from drift_gate.core.evaluation.analysis_session import AnalysisSession
    from drift_gate.core.evaluation.contracts import content_requirement
    from drift_gate.core.models.policy import Group
    session=AnalysisSession(limit=1); files=[source(after=code('/new','NEW'))]
    result=content_requirement(Group('contracts',any_changed=['docs/api.md'],content='auto-strict'),files,documents(),session)
    assert result.decision == 'undetermined'
    assert len(session.shadow_contract_proofs) == len(session.shadow_contract_plans) == 1
    session.shadow_contract_proofs[0].validate()
    content_requirement(Group('other',any_changed=['docs/api.md'],content='auto-strict'),files,documents(),session)
    assert len(session.shadow_contract_proofs) == 1
    assert session.shadow_contract_proofs[0].evaluation.plan.request.group_id == 'other'


def test_roundtrip_json_requires_external_context_and_preserves_proof():
    ctx=context({'a':Truth.FALSE,'b':Truth.UNKNOWN}); result=evaluate(ctx)
    payload=json.loads(json.dumps(result.to_dict()))
    assert validate_proof_payload(payload,ctx) == result
    with pytest.raises(ResultValidationError): validate_proof_payload(payload,replace(ctx,input_ref='different'))


@pytest.mark.parametrize('mutation', ['unknown-field','unsupported-assurance','truth','missing-coverage','children','witness','node-limit','edge-limit'])
def test_serialized_malformed_or_forged_ir_is_rejected(mutation):
    ctx=context({'a':Truth.FALSE,'b':Truth.UNKNOWN}); payload=json.loads(json.dumps(evaluate(ctx).to_dict()))
    if mutation == 'unknown-field': payload['extra']=True
    elif mutation == 'unsupported-assurance': payload['current_head_certified']=True
    elif mutation == 'truth': payload['nodes'][0]['truth']='YES'
    elif mutation == 'missing-coverage': del payload['nodes'][0]['coverage']['open_domains']
    elif mutation == 'children': payload['nodes'][0]['spec']['children']='a'
    elif mutation == 'witness': payload['nodes'][0]['sufficient_witness_refs']=['a','a']
    elif mutation == 'node-limit': payload['nodes']*=2049
    else: payload['nodes'][-1]['spec']['children']=['a']*16385
    with pytest.raises(ResultValidationError): validate_proof_payload(payload,ctx)


def test_duplicate_proposition_or_evidence_ids_cannot_conflict():
    ctx=context({'a':Truth.TRUE})
    with pytest.raises(ValueError,match='duplicate'):
        replace(ctx,propositions=ctx.propositions+(replace(ctx.propositions[0],truth=Truth.FALSE),))
    with pytest.raises(ValueError,match='duplicate'):
        replace(ctx,evidence=ctx.evidence+(replace(ctx.evidence[0],truth=Truth.FALSE),))


def test_document_bytes_bind_context_even_when_content_decision_is_equal():
    files=[source()]; docs=documents()
    a=inspect_contract_proof(request(files),files,docs)
    docs[0]=replace(docs[0],after_source='GET /new\n\nAdditional explanation.\n')
    b=inspect_contract_proof(request(files),files,docs)
    assert a.root.truth == b.root.truth == Truth.TRUE
    assert a.context.ref != b.context.ref
    with pytest.raises(ResultValidationError): validate_proof_evaluation(a.proof,b.context)
    encoded=json.dumps(b.to_dict())
    assert docs[0].after_source not in encoded and files[0].after_source not in encoded


def test_invalid_proof_guard_terminates_inspection_before_return(monkeypatch):
    import drift_gate.core.evaluation.contract_proof as module
    def reject(*args,**kwargs): raise ResultValidationError('deliberate invalid IR')
    monkeypatch.setattr(module,'validate_proof_evaluation',reject)
    with pytest.raises(ResultValidationError,match='invalid IR'):
        inspect_contract_plan(request([source()]),[source()],documents())
