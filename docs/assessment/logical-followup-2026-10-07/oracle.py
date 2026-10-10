"""Controlled FastAPI oracle; fixed authored source only, never user projects."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from drift_gate.core.engine import run
from drift_gate.core.evaluation.api_schema import extract_responses
from drift_gate.tests.test_fastapi_oracle import controlled_app
from drift_gate.tests.test_contract_followup import router_source, partial_files
from drift_gate.tests.test_logical_contracts import source, changed, document, policy, openapi


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--out',required=True,type=Path);args=parser.parse_args()
    if args.out.exists(): parser.error('Output already exists')
    cases=[]
    for fields in ['id: int','id: str','id: bool','id: float','id: int = 1','id: str = "value"','id: bool = True','id: float = 1.5']:
        for layout in ['direct','router','nested','repeated']:
            text=source(fields) if layout=='direct' else router_source(fields,nested=layout=='nested',repeat=layout=='repeated')
            doc=controlled_app(text).openapi()
            correct_doc=json.loads(json.dumps(doc))
            file=changed(before='',after=text,status='added')
            positive=run([file,document(json.dumps(doc))],policy=policy()).to_dict()
            prop=next(iter(doc['components']['schemas'].values()))['properties']['id']
            prop['type']='string' if prop['type']!='string' else 'integer'; prop.pop('default',None)
            negative=run([file,document(json.dumps(doc))],policy=policy()).to_dict()
            assert positive['result']=='pass' and positive['verification']=='verified'
            assert negative['result']=='fail' and negative['rule_decisions'][0]['decision']=='violated'
            cases.append({'fields':fields,'layout':layout,'controlled_source':text,'framework_openapi':correct_doc,
                          'extracted_paths':[list(key) for key in extract_responses(text)],
                          'positive':positive,'negative':negative})
    partial=run([*partial_files(),document(openapi({'id':{'type':'integer'},'label':{'type':'string'}}))],policy=policy(action='warn')).to_dict()
    assert partial['result']=='fail' and partial['verification']=='partial'
    payload={'versions':{name:importlib.metadata.version(name) for name in ['fastapi','pydantic','starlette']},
             'scope':'controlled OpenAPI generation; no live HTTP/deployment claim',
             'matched':len(cases),'total':32,'cases':cases,'partial_source_example':partial}
    with args.out.open('x',encoding='utf-8') as handle: json.dump(payload,handle,ensure_ascii=False,indent=2);handle.write('\n')
    print(json.dumps({'matched':len(cases),'total':32,'partial':partial['verification']}))
if __name__=='__main__':main()
