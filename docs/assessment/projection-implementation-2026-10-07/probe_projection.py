"""Real Git/CLI/MCP/Desktop/reporter parity; GitHub transport is simulated."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from drift_gate.adapters.cli.runner import run_cli
from drift_gate.adapters.docs.content import attach_env_documents, local_document_reader
from drift_gate.adapters.git.client import GitAdapter
from drift_gate.adapters.github_action import runner as action
from drift_gate.adapters.mcp import tools
from drift_gate.desktop.service import scan_repository
from drift_gate.reporters.html import HtmlReporter
from drift_gate.reporters.markdown import MarkdownReporter
import yaml


def source(path='/old', body='{}', dynamic=False):
    return ('from fastapi import FastAPI\napp = FastAPI()\n' +
            ('route = read_path()\n' if dynamic else '') +
            f'@app.get({"route" if dynamic else repr(path)})\ndef endpoint(): return {body}\n')


def evaluate_case(kind, enabled):
    with tempfile.TemporaryDirectory(prefix='driftgate-projection-') as directory:
        root=Path(directory).resolve(); old_cwd=Path.cwd()
        def git(*args): return subprocess.check_output(['git',*args],cwd=root,stderr=subprocess.PIPE)
        git('init'); (root/'src').mkdir(); (root/'docs').mkdir()
        (root/'src/api.py').write_text(source())
        (root/'docs/api.md').write_text('GET /old\n')
        policy={'rules':[{'id':'api','when':{'any_changed':['src/**']},'require':{'groups':[
            {'name':'API','any_changed':['docs/api.md'],'content':'auto-strict'}]},'severity':'blocker'}]}
        (root/'.drift-gate.yml').write_text(yaml.safe_dump(policy))
        git('add','.'); git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','baseline')
        after=source('/old',body='{"value": 1}') if kind=='inactive' else source('/new',dynamic=kind=='unsupported')
        (root/'src/api.py').write_text(after)
        if kind=='correct': (root/'docs/api.md').write_text('GET /new\n')
        class Remote:
            def __init__(self,**kwargs): pass
            def get_pr_files_and_body(self,number): return deepcopy(GitAdapter(root).get_changed_files('HEAD')),''
            def attach_env_documents(self,number,files,loaded): return attach_env_documents(files,loaded,local_document_reader(root))
        env={'ANTHROPIC_API_KEY':'','GITHUB_TOKEN':'fixture','REPO':'fixture/repo','PR_NUMBER':'1',
             'GITHUB_WORKSPACE':str(root),'RUNNER_TEMP':str(root),'POST_COMMENT':'false','GITHUB_EVENT_PATH':'',
             'GITHUB_OUTPUT':'','GITHUB_STEP_SUMMARY':'','CONTRACT_PROOFS':str(enabled).lower()}
        try:
            os.chdir(root)
            with patch.dict(os.environ,env), patch.object(action,'GitHubAdapter',Remote), patch.object(tools,'GitHubAdapter',Remote), \
                 patch('drift_gate.adapters.github.approvals.verify_ignores',return_value=[]):
                stream=io.StringIO()
                with redirect_stdout(stream),redirect_stderr(io.StringIO()):
                    try: run_cli(['check','--base','HEAD','--json']+(['--contract-proofs'] if enabled else []))
                    except SystemExit as exc: exit_code=exc.code
                cli=json.loads(stream.getvalue())
                local=tools.drift_gate_check_local(mode='full',contract_proofs=enabled)
                remote=tools.drift_gate_check_pr(1,repo='fixture/repo',token='fixture',mode='full',contract_proofs=enabled)
                scan=scan_repository(root,contract_proofs=enabled); desktop=scan.result.to_dict()
                with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()): action.main()
                github=json.loads((root/'drift_gate_report.json').read_text())
                compact=tools.drift_gate_check_local(mode='compact',token_budget=200,contract_proofs=enabled)
                payloads={'cli':cli,'mcp_local':local,'mcp_pr':remote,'desktop_service':desktop,'action_simulation':github}
                comparable={name:{key:payload.get(key) for key in ('result','verification','summary','contract_diagnostics')}
                            for name,payload in payloads.items()}
                parity=all(payload==comparable['cli'] for payload in comparable.values())
                html_report=HtmlReporter().render(scan.result); markdown=MarkdownReporter().render(scan.result)
                return {'id':kind+(' enabled' if enabled else ' default'),'enabled':enabled,
                    'before':{'src/api.py':source(),'docs/api.md':'GET /old\n'},
                    'after':{'src/api.py':after,'docs/api.md':'GET /new\n' if kind=='correct' else 'GET /old\n'},
                    'policy':policy,'cli_exit_code':exit_code,'matched':parity,
                    'outputs':comparable,'compact':compact,
                    'html_diagnostics_present':'Contract proof diagnostics' in html_report,
                    'markdown_diagnostics_present':'Contract proof diagnostics' in markdown}
        finally:
            os.chdir(old_cwd)


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    cases=[evaluate_case(kind,enabled) for kind in ('stale','correct','unsupported','inactive') for enabled in (False,True)]
    for i in range(0,len(cases),2):
        before,after=cases[i:i+2]
        for key in ('result','verification','summary'):
            assert before['outputs']['cli'][key]==after['outputs']['cli'][key]
    checks={row['id']:row['matched'] and row['html_diagnostics_present']==row['enabled']
            and row['markdown_diagnostics_present']==row['enabled'] for row in cases}
    result={'schema':'contract-projection-entrypoints-v1',
            'scope':'Authored nonblind local Git/entrypoint controls; GitHub transport simulated, no remote CI or installer',
            'matched':sum(checks.values()),'total':len(checks),'checks':checks,'cases':cases}
    with args.out.open('x',encoding='utf-8') as stream: json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False)
    print(json.dumps(checks)); raise SystemExit(0 if all(checks.values()) else 1)


if __name__=='__main__': main()
