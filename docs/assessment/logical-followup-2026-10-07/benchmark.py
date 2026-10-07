"""Fixed workload: repeated rules over 24 modules; output never overwritten."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from drift_gate.core.engine import run
from drift_gate.core.evaluation import api_schema
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.policy.loader import load_policy_from_dict


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--out',type=Path,required=True); args=parser.parse_args()
    if args.out.exists(): parser.error('Output already exists')
    module="from fastapi import FastAPI\nfrom pydantic import BaseModel\napp = FastAPI()\nclass Item(BaseModel):\n    id: int\n{field}\n@app.get('/items/{index}', response_model=Item)\ndef items(): return {{}}\n"
    files=[ChangedFile(f'src/api{i}.py','modified',patch='-    label: str\n',before_source=module.format(index=i,field='    label: str'),after_source=module.format(index=i,field='')) for i in range(24)]
    paths={f'/items/{i}':{'get':{'responses':{'200':{'content':{'application/json':{'schema':{'type':'object','properties':{'id':{'type':'integer'}},'required':['id']}}}}}}} for i in range(24)}
    text=json.dumps({'openapi':'3.1.0','paths':paths})
    files.append(ChangedFile('openapi.json','unchanged',after_source=text))
    rule={'id':'r','severity':'blocker','when':{'any_changed':['src/**'],'min_change_intensity':'route-contract-change'},'require':{'groups':[{'name':'api','all_changed':['openapi.json'],'content':'api-schema'}]}}
    rules=[]
    for i in range(8):
        item=deepcopy(rule); item['id']=f'r{i}'; rules.append(item)
    policy=load_policy_from_dict({'rules':rules})
    inputs=[{**f.to_dict(),'before_source':f.before_source,'after_source':f.after_source} for f in files]
    durations=[]; counts=[]
    for _ in range(5):
        with patch.object(api_schema.ast,'parse', wraps=api_schema.ast.parse) as parser_spy:
            started=time.perf_counter(); result=run(files,policy=policy); durations.append(time.perf_counter()-started); counts.append(parser_spy.call_count)
        assert result.result=='pass' and result.verification=='verified'
    record={'workload':{'modules':24,'rules':8,'repeats':5},'input_sha256':hashlib.sha256(json.dumps({'files':inputs,'rules':rules},sort_keys=True).encode()).hexdigest(),'seconds':durations,'median_seconds':statistics.median(durations),'ast_parses':counts,'report_bytes':len(json.dumps(result.to_dict()).encode()),'gate':result.result,'verification':result.verification}
    with args.out.open('x') as f: json.dump(record,f,indent=2); f.write('\n')
    print(json.dumps(record))
if __name__=='__main__': main()
