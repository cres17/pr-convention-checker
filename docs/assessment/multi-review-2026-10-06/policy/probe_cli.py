import json, subprocess, tempfile
from pathlib import Path
OUT=Path(__file__).resolve().parent
PYTHON='/private/tmp/driftgate-final-review-venv/bin/python'
with tempfile.TemporaryDirectory(prefix='drift-temporal-probe-') as temp:
    root=Path(temp)
    def git(*args): return subprocess.run(['git',*args],cwd=root,check=True,capture_output=True)
    git('init','-q'); git('config','user.email','probe@example.invalid'); git('config','user.name','probe')
    (root/'src').mkdir(); (root/'src/api.py').write_text('x = 1\n')
    (root/'.drift-gate.yml').write_text('rules:\n  - id: api\n    severity: blocker\n    when:\n      any_changed: [src/**]\n    require:\n      groups:\n        - name: docs\n          all_changed: [docs/api.md]\n')
    git('add','.'); git('commit','-qm','fixture')
    (root/'src/api.py').write_text('x = 2\n')
    json_path=OUT/'temporal-result.json'; html_path=OUT/'temporal-result.html'
    json_path.write_text('{"result":"pass","execution":{"run_id":"OLD"}}\n')
    html_path.write_text('OLD PASS')
    args=[PYTHON,'-m','drift_gate','check','--temporal-gate','--temporal-window','nonsense','--json','--out-json',str(json_path),'--out-html',str(html_path)]
    proc=subprocess.run(args,cwd=root,text=True,capture_output=True)
    result={'command':args,'exit':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr,'json_after':json.loads(json_path.read_text()),'html_after':html_path.read_text()}
    (OUT/'cli-result.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
