"""Real CLI/MCP processes; GitHub network boundary stubbed, no outbound calls."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
from drift_gate.adapters.github_action import runner
from drift_gate.core.models.changed_file import ChangedFile
OUT=Path(__file__).resolve().parent
results={}
with tempfile.TemporaryDirectory(prefix='drift-adapters-probe-') as tmp:
    root=Path(tmp)
    def git(*args):
        return subprocess.run(['git',*args],cwd=root,capture_output=True,check=True)
    git('init','-q')
    (root/'src').mkdir()
    (root/'src/api.py').write_text('value = 1\n')
    policy=root/'.drift-gate.yml'
    policy.write_text('rules: []\n')
    git('add','.')
    git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture')
    (root/'src/api.py').write_text('value = 2\n')
    def cli():
        p=subprocess.run([sys.executable,'-m','drift_gate','check','--json'],cwd=root,capture_output=True,text=True)
        return {'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
    def mcp():
        frames=[{'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'drift_gate_check_local','arguments':{}}},
                {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'drift_gate_check_local','arguments':{'mode':'full'}}}]
        p=subprocess.run([sys.executable,'-m','drift_gate','serve','--repo',str(root)],input='\n'.join(map(json.dumps,frames))+'\n',capture_output=True,text=True)
        return {'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
    results['empty_policy_cli']=cli()
    results['empty_policy_mcp']=mcp()
    files=[ChangedFile('src/api.py','modified',patch='@@ -1 +1 @@\n-value = 1\n+value = 2\n')]
    with patch.dict(os.environ,{'GITHUB_TOKEN':'fixture','REPO':'fixture/project','PR_NUMBER':'1','POLICY_FILE':str(policy),'RUNNER_TEMP':tmp,'POST_COMMENT':'false','GITHUB_OUTPUT':str(root/'action.out'),'GITHUB_STEP_SUMMARY':'','ANTHROPIC_API_KEY':''}), patch.object(runner,'GitHubAdapter') as GH, contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
        GH.return_value.get_pr_files_and_body.return_value=(files,'')
        GH.return_value.attach_env_documents.return_value=files
        runner.main()
    results['empty_policy_action']={'boundary':'GitHub API stub; actual Action runner and policy engine','output':(root/'action.out').read_text(),'report':json.loads((root/'drift_gate_report.json').read_text())}
    policy.write_text('rules:\n  - id: contract\n    when:\n      any_changed: [src/**]\n    severity: blocker\n    require:\n      groups:\n        - name: docs\n          all_changed: [docs/api.md]\n')
    results['valid_policy_mcp_control']=mcp()
    git('add','.')
    git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','second fixture')
    (root/'src/new.py').write_text('value = 3\n')
    results['untracked_cli']=cli()
    results['untracked_mcp']=mcp()
(OUT/'adapters-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
for key,value in results.items():
    if 'mcp' in key:
        parsed=[json.loads(json.loads(row)['result']['content'][0]['text']) for row in value['stdout'].splitlines()]
        print(key,[(p.get('result'),p.get('no_policy'),p.get('execution',{})) for p in parsed])
    elif 'action' in key: print(key,value['report']['result'])
    else: print(key,value['exit'])
