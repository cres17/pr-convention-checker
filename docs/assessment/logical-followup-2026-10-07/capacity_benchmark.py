"""Larger paired workload; identical final code, cache enabled vs disabled."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from drift_gate.core.engine import run
from drift_gate.core.evaluation import evaluator
from drift_gate.core.evaluation.analysis_session import AnalysisSession
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.policy.loader import load_policy_from_dict


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    if args.out.exists(): parser.error('Output already exists')
    fields='\n'.join(f'    field{i}: int' for i in range(80))
    files=[];paths={}
    for i in range(32):
        after=f"from fastapi import FastAPI\nfrom pydantic import BaseModel\napp = FastAPI()\nclass Item(BaseModel):\n{fields}\n@app.get('/items/{i}', response_model=Item)\ndef items(): return {{}}\n"
        before=after.replace('    field0: int','    field0: str')
        files.append(ChangedFile(f'src/api{i}.py','modified',patch='-    field0: str\n+    field0: int\n',before_source=before,after_source=after))
        schema={'type':'object','properties':{f'field{f}':{'type':'integer'} for f in range(80)},'required':[f'field{f}' for f in range(80)]}
        paths[f'/items/{i}']={'get':{'responses':{'200':{'content':{'application/json':{'schema':schema}}}}}}
    text=json.dumps({'openapi':'3.1.0','paths':paths});files.append(ChangedFile('openapi.json','unchanged',after_source=text))
    rule={'id':'r','severity':'blocker','when':{'any_changed':['src/**'],'min_change_intensity':'route-contract-change'},'require':{'groups':[{'name':'api','all_changed':['openapi.json'],'content':'api-schema'}]}}
    rules=[]
    for i in range(8): item=deepcopy(rule);item['id']=f'r{i}';rules.append(item)
    policy=load_policy_from_dict({'rules':rules})
    expected=None; measurements={}
    for limit in [0,128]:
        durations=[]
        for _ in range(3):
            with patch.object(evaluator,'AnalysisSession',lambda:AnalysisSession(limit=limit)):
                started=time.perf_counter();result=run(files,policy=policy);durations.append(time.perf_counter()-started)
            payload=result.to_dict()
            assert payload['result']=='pass' and payload['verification']=='verified'
            if expected is None: expected=payload
            else: assert expected==payload
        measurements[str(limit)]={'seconds':durations,'median_seconds':statistics.median(durations),'report_bytes':len(json.dumps(payload).encode())}
    data={'workload':{'modules':32,'fields_per_module':80,'rules':8,'repeats':3},
          'input_sha256':hashlib.sha256(json.dumps([{'before':f.before_source,'after':f.after_source,'path':f.path} for f in files],sort_keys=True).encode()).hexdigest(),
          'openapi_bytes':len(text.encode()),'measurements_by_cache_entries':measurements,'full_reports_identical':True}
    with args.out.open('x') as handle:json.dump(data,handle,indent=2);handle.write('\n')
    print(json.dumps(data))
if __name__=='__main__':main()
