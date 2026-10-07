"""Versioned proof projection and real local entrypoint parity controls."""
from copy import deepcopy
from dataclasses import replace
import html
import json
import re
import subprocess

import pytest
import yaml

from drift_gate.adapters.cli.runner import run_cli
from drift_gate.adapters.docs.content import attach_env_documents, local_document_reader
from drift_gate.adapters.git.client import GitAdapter
from drift_gate.adapters.github_action import runner as action
from drift_gate.adapters.mcp import tools
from drift_gate.core.compat.legacy_result import ContractDiagnostics, project_contract_proof
from drift_gate.core.contracts.planner import DocumentBindings, DocumentBinding
from drift_gate.core.engine import run
from drift_gate.core.evaluation.analysis_session import AnalysisSession
from drift_gate.core.evaluation.contract_proof import inspect_contract_proof
from drift_gate.core.evaluation.result_guard import ResultValidationError, validate_proof_payload
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.desktop.service import scan_repository
from drift_gate.reporters.html import HtmlReporter
from drift_gate.reporters.json_reporter import JsonReporter
from drift_gate.reporters.markdown import MarkdownReporter
from drift_gate.tests.test_obligation_planner import code, documents, request, source


@pytest.mark.parametrize('kind,decision,verification', [
    ('satisfied','satisfied','verified'),('violated','violated','verified'),
    ('unknown','undetermined','unverified'),('partial','violated','partial'),
    ('inactive','not-applicable','not-applicable'),
])
def test_projection_only_maps_validated_truth_and_coverage(kind,decision,verification):
    files=[source(after=code() if kind == 'inactive' else code('/new'))]
    docs=documents('/old' if kind in {'violated','partial'} else '/new')
    if kind == 'unknown': docs=[]
    if kind == 'partial': files.append(ChangedFile('src/opaque.go','modified'))
    proof=inspect_contract_proof(request(files),files,docs)
    projection=project_contract_proof(proof)
    assert (projection['decision'],projection['verification']) == (decision,verification)
    assert projection['truth']==proof.root.truth.value and projection['decision_proven']==proof.root.decision_proven
    assert projection['complete_within_selection']==proof.root.coverage.complete
    assert not projection['gate_action_applied'] and 'result' not in projection
    assert projection['open_domains']==list(proof.root.coverage.open_domains)


def test_projection_rejects_forged_proof_and_nonproof_objects():
    files=[source()]; proof=inspect_contract_proof(request(files),files,documents('/old'))
    nodes=tuple(replace(node,decision_proven=False) if node.id==proof.proof.root_ref else node for node in proof.proof.nodes)
    with pytest.raises(ResultValidationError): project_contract_proof(replace(proof,proof=replace(proof.proof,nodes=nodes)))
    with pytest.raises(ResultValidationError): project_contract_proof({})


def test_positive_witness_with_unknown_alternative_projects_partial_without_changing_truth():
    files=[source()]
    bindings=DocumentBindings('contract-document-bindings-v1',(
        DocumentBinding('api',('python-fastapi-routes','1'),('docs/api.md','docs/other.md')),))
    proof=inspect_contract_proof(replace(request(files),bindings=bindings),files,documents())
    row=project_contract_proof(proof)
    assert row['truth']=='T' and row['decision']=='satisfied' and row['decision_proven']
    assert row['verification']=='partial' and not row['complete_within_selection']


@pytest.mark.parametrize('limit',[0,1,2])
def test_diagnostic_retention_never_claims_complete_policy_coverage(limit):
    session=AnalysisSession(limit=limit)
    for path in ('src/a.py','src/b.py','src/c.py'):
        files=[source(path=path)]
        session.record_contract_plan(inspect_contract_proof(request(files),files,documents()).evaluation)
    diagnostics=ContractDiagnostics(session.shadow_contract_proofs,session.contract_records_seen,limit)
    payload=diagnostics.to_dict()
    assert payload['records_seen']==3 and payload['retained_count']==limit
    assert payload['omitted_record_count']==3-limit and payload['trace_truncated']
    assert not payload['complete_policy_coverage'] and not payload['gate_action_applied']


def test_repeated_records_disclose_overwritten_history():
    session=AnalysisSession(); files=[source()]
    proof=inspect_contract_proof(request(files),files,documents())
    for _ in range(3): session.record_contract_plan(proof.evaluation)
    data=ContractDiagnostics(session.shadow_contract_proofs,session.contract_records_seen,session.limit).to_dict()
    assert data['retained_count']==1 and data['omitted_record_count']==2 and data['trace_truncated']


@pytest.mark.parametrize('metadata',[(-1,128),(0,0),(1,-1),(True,128),(1,True)])
def test_invalid_retention_metadata_rejected(metadata):
    files=[source()]; proof=inspect_contract_proof(request(files),files,documents())
    with pytest.raises(ResultValidationError): ContractDiagnostics((proof,),*metadata)


def git(root,*args):
    return subprocess.check_output(['git',*args],cwd=root,stderr=subprocess.PIPE)


def repository(root,kind='stale'):
    git(root,'init'); (root/'src').mkdir(); (root/'docs').mkdir()
    before=code(); after=code().replace('return {}','return {"value": 1}') if kind=='inactive' else code('/new')
    if kind=='unsupported': after=code('/new',dynamic=True)
    (root/'src/api.py').write_text(before)
    (root/'docs/api.md').write_text('GET /old\n')
    (root/'.env.example').write_text('KNOWN=example\n')
    policy={'rules':[{'id':'api','when':{'any_changed':['src/**']},'require':{'groups':[{
        'name':'contract','any_changed':['docs/api.md'],'content':'auto-strict'}]},'severity':'blocker'}]}
    (root/'.drift-gate.yml').write_text(yaml.safe_dump(policy))
    git(root,'add','.'); git(root,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','baseline')
    (root/'src/api.py').write_text(after)
    if kind=='correct': (root/'docs/api.md').write_text('GET /new\n')


@pytest.mark.parametrize('kind',['stale','correct','unsupported','inactive'])
@pytest.mark.parametrize('enabled',[False,True])
def test_cli_mcp_desktop_action_html_use_one_projection(tmp_path,monkeypatch,capsys,kind,enabled):
    repository(tmp_path,kind); monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        run_cli(['check','--base','HEAD','--json']+(['--contract-proofs'] if enabled else []))
    cli=json.loads(capsys.readouterr().out)
    mcp=tools.drift_gate_check_local(mode='full',contract_proofs=enabled)
    scan=scan_repository(tmp_path,contract_proofs=enabled); desktop=scan.result.to_dict()
    compact=tools.drift_gate_check_local(mode='compact',token_budget=100000,contract_proofs=enabled)
    class Remote:
        def __init__(self,**kwargs): pass
        def get_pr_files_and_body(self,number): return deepcopy(GitAdapter(tmp_path).get_changed_files('HEAD')),''
        def attach_env_documents(self,number,files,policy): return attach_env_documents(files,policy,local_document_reader(tmp_path))
    monkeypatch.setattr(action,'GitHubAdapter',Remote)
    monkeypatch.setattr(tools,'GitHubAdapter',Remote)
    monkeypatch.setattr('drift_gate.adapters.github.approvals.verify_ignores',lambda *args: [])
    env={'GITHUB_TOKEN':'fixture','REPO':'fixture/repo','PR_NUMBER':'1','GITHUB_WORKSPACE':str(tmp_path),
         'RUNNER_TEMP':str(tmp_path),'POST_COMMENT':'false','ANTHROPIC_API_KEY':'','GITHUB_EVENT_PATH':'',
         'GITHUB_OUTPUT':'','GITHUB_STEP_SUMMARY':'','CONTRACT_PROOFS':str(enabled).lower()}
    for key,value in env.items(): monkeypatch.setenv(key,value)
    action.main()
    github=json.loads((tmp_path/'drift_gate_report.json').read_text())
    remote_mcp=tools.drift_gate_check_pr(1,repo='fixture/repo',token='fixture',mode='full',contract_proofs=enabled)
    for payload in (mcp,desktop,github,compact,remote_mcp):
        assert payload['result']==cli['result'] and payload['verification']==cli['verification']
        assert payload['summary']==cli['summary']
    for payload in (cli,mcp,desktop,github,remote_mcp):
        assert payload.get('contract_diagnostics')==cli.get('contract_diagnostics')
        assert ('contract_diagnostics' in payload)==enabled
    report=HtmlReporter().render(scan.result)
    raw=[html.unescape(value) for value in re.findall(r'<pre>(.*?)</pre>',report,re.S) if html.unescape(value).lstrip().startswith('{')]
    assert json.loads(raw[-1])==desktop
    if enabled:
        data=cli['contract_diagnostics']; assert data['retained_count']>0
        assert not data['complete_policy_coverage'] and not data['gate_action_applied']
        for entry in data['entries']:
            # The expectation is separately generated from live inputs in the
            # proof roundtrip control; here check linkage after transport.
            assert entry['projection']['context_ref']==entry['proof_result']['proof']['context_ref']
        assert [entry['projection'] for entry in compact['contract_diagnostics']['entries']]==[entry['projection'] for entry in data['entries']]
        for entry in data['entries']:
            p=entry['projection']; assert f"{p['truth']} / {p['decision']} / {p['verification']}" in report
        assert 'Contract proof diagnostics' in MarkdownReporter().render(scan.result)
    else:
        assert 'Contract proof diagnostics' not in report


def test_compact_budget_discloses_proof_and_entry_omission(tmp_path,monkeypatch):
    repository(tmp_path); monkeypatch.chdir(tmp_path)
    full=tools.drift_gate_check_local(mode='full',contract_proofs=True)
    short=tools.drift_gate_check_local(mode='compact',token_budget=200,contract_proofs=True)
    data=short['contract_diagnostics']
    assert data['full_proofs_omitted'] and data['display_truncated']
    assert data['entries']==[] and data['omitted_entry_count']==full['contract_diagnostics']['retained_count']
    assert data['records_seen']==full['contract_diagnostics']['records_seen']
    assert not data['complete_policy_coverage'] and short['result']==full['result']


def test_reporters_and_json_projection_terminate_on_invalid_diagnostics():
    result=run([]); result.contract_diagnostics={}
    for render in (result.to_dict,lambda: JsonReporter().render(result),
                   lambda: HtmlReporter().render(result),lambda: MarkdownReporter().render(result)):
        with pytest.raises((ResultValidationError,TypeError)): render()


def test_proof_roundtrip_remains_valid_after_projection():
    files=[source()]; proof=inspect_contract_proof(request(files),files,documents('/old'))
    entry=ContractDiagnostics((proof,),1,128).to_dict()['entries'][0]
    validate_proof_payload(json.loads(json.dumps(entry['proof_result']['proof'])),proof.context)


def test_cli_invalid_proof_never_prints_success_payload(tmp_path,monkeypatch,capsys):
    repository(tmp_path); monkeypatch.chdir(tmp_path)
    import drift_gate.core.evaluation.contract_proof as module
    def invalid(*args,**kwargs): raise ResultValidationError('invalid proof')
    monkeypatch.setattr(module,'validate_proof_evaluation',invalid)
    with pytest.raises(SystemExit) as exc: run_cli(['check','--base','HEAD','--json','--contract-proofs'])
    assert exc.value.code==2
    payload=json.loads(capsys.readouterr().out)
    assert payload['error']['code']=='result_validation_error' and 'result' not in payload


@pytest.mark.parametrize('enabled',[None,0,1,'true'])
def test_nonboolean_optin_rejected(enabled):
    with pytest.raises(ValueError,match='boolean'): run([],contract_proofs=enabled)


@pytest.mark.parametrize('mode',['empty','no-policy','docs-only'])
def test_no_shadow_records_does_not_claim_any_proof_or_complete_scope(mode):
    from drift_gate.core.models.policy import Policy
    files=[] if mode=='empty' else [ChangedFile('docs/notes.md','modified',patch='+text')]
    result=run(files,policy=None if mode=='no-policy' else Policy(),contract_proofs=True)
    data=result.to_dict()['contract_diagnostics']
    assert data['status']=='no-shadow-records' and data['entries']==[] and not data['complete_policy_coverage']


def test_mcp_advertises_boolean_proof_optin_and_rejects_string_value():
    from drift_gate.adapters.mcp.server import _tool_schema, _call_tool
    assert _tool_schema('drift_gate_check_local')['inputSchema']['properties']['contract_proofs']['type']=='boolean'
    with pytest.raises(TypeError,match='bool'):
        _call_tool('drift_gate_check_local',{'contract_proofs':'true'})


def test_public_action_rejects_invalid_optin(monkeypatch):
    monkeypatch.setenv('CONTRACT_PROOFS','maybe')
    with pytest.raises(ValueError,match='true or false'): action.main()


def test_projection_labels_are_escaped_in_html_and_markdown():
    files=[source()]; label='<script>alert(1)</script> [link](javascript:bad) _em_'
    proof=inspect_contract_proof(replace(request(files),group_id=label),files,documents())
    result=run([]); result.contract_diagnostics=ContractDiagnostics((proof,),1,128)
    html_report=HtmlReporter().render(result); markdown=MarkdownReporter().render(result)
    assert label not in html_report and '<script>alert(1)</script>' not in html_report
    assert '<script>alert(1)</script>' not in markdown and '[link](javascript:bad)' not in markdown
    assert '\\_em\\_' in markdown
