"""Read-only synthetic counterexample for content scope in cross-file rules."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from drift_gate.core.engine import run
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.policy.loader import load_policy_from_dict
from drift_gate.tests.test_logical_contracts import changed,document,openapi


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    policy={'rules':[{'id':'conditional-schema','severity':'blocker','when':{'any_changed':['src/config.py']},'require':{'groups':[{'name':'API','required':False,'all_changed':['openapi.json'],'content':'api-schema'}],'cross_file':[{'name':'API changed','when_any_changed':['src/api.py'],'require_groups':['API']}]}}]}
    config=ChangedFile('src/config.py','modified',patch='-x = 1\n+x = 2\n',before_source='x = 1\n',after_source='x = 2\n')
    api=changed()
    stale=document(openapi({'id':{'type':'integer'},'label':{'type':'string'}}))
    result=run([config,api,stale],policy=load_policy_from_dict(policy)).to_dict()
    control=json.loads(json.dumps(policy));control['rules'][0]['when']['any_changed']=['src/api.py']
    direct=run([config,api,stale],policy=load_policy_from_dict(control)).to_dict()
    payload={'policy':policy,'inputs':[{**f.to_dict(),'before_source':f.before_source,'after_source':f.after_source} for f in [config,api,stale]],'relation_result':result,'direct_trigger_control':direct,'expected_relation':'violated: API response field removed while OpenAPI retains label'}
    with args.out.open('x') as handle:json.dump(payload,handle,indent=2);handle.write('\n')
    print(json.dumps({'relation':result['result'],'relation_verification':result['verification'],'direct':direct['result'],'direct_verification':direct['verification']}))
if __name__=='__main__': main()
