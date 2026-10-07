import copy, json
from pathlib import Path
from drift_gate.core.policy.loader import load_policy_from_dict
from drift_gate.core.policy.guard import weakening_reasons
from drift_gate.core.engine import run
from drift_gate.core.models.changed_file import ChangedFile

base = {'rules':[{'id':'contract', 'when':{'any_changed':['src/**']}, 'require':{'groups':[{'name':'API', 'all_changed':['docs/api.md'], 'required':False}], 'cross_file':[{'name':'api-sync','when_any_changed':['src/**'], 'require_groups':['API']}]}, 'severity':'blocker'}]}
files=[ChangedFile(path='src/api.py',status='modified',patch='@@ -1 +1 @@\n-a=1\n+a=2\n')]
results=[]
def check(name, trusted_raw, candidate_raw):
    trusted=load_policy_from_dict(trusted_raw)
    candidate=load_policy_from_dict(candidate_raw)
    a,b=run(files,policy=trusted),run(files,policy=candidate)
    results.append({'case':name, 'trusted':trusted_raw,'candidate':candidate_raw,'guard_reasons':weakening_reasons(trusted,candidate),'trusted_result':a.to_dict(),'candidate_result':b.to_dict()})
candidate=copy.deepcopy(base)
candidate['rules'][0]['require']['groups'][0]['all_changed']=['src/**']
check('cross-file-required-optional-group-weakening', base, candidate)
base2=copy.deepcopy(base)
base2['rules'][0]['require']['groups'][0]['required']=True
base2['rules'][0]['severity']='major'
base2['gate']={'fail_on_blocker':False,'fail_on_major_count':1}
candidate2=copy.deepcopy(base2)
candidate2['rules'][0]['severity']='blocker'
check('severity-promotion-disables-major-failure',base2,candidate2)
Path(__file__).with_name('results.json').write_text(json.dumps(results,indent=2))
for result in results: print(result['case'], result['guard_reasons'], result['trusted_result']['result'], '->',result['candidate_result']['result'])
