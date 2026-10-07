"""Contrast gate-label score with semantic verification; preserve original suite."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from drift_gate.adapters.ast.analyzer import enrich_semantic_signals
from drift_gate.core.engine import run
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.policy.loader import load_policy_from_dict


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True,type=Path);args=parser.parse_args()
    suite=json.loads((ROOT/'docs/assessment/generalization-audit-v1.json').read_text());rows=[]
    for case in suite['cases']:
        if case['scope']!='boundary': continue
        raw=deepcopy(suite['policies'][case['policy']])
        for rule in raw['rules']:
            rule['when']['min_change_intensity']='any'
            for group in rule['require']['groups']:
                if group.get('content','auto')=='auto': group['content']='api-routes'
        files=enrich_semantic_signals([ChangedFile.from_dict(f) for f in case['changed_files']])
        result=run(files,policy=load_policy_from_dict(raw)).to_dict()
        rows.append({'id':case['id'],'expected_gate':case['expected'],'actual':result['result'],
            'decision':result['rule_decisions'][0]['decision'],'verification':result['verification'],
            'gate_matched':case['expected']==result['result'],'result':result})
    payload={'experiment':'policy-only counterfactual; no product or frozen suite changes',
        'always_fail_matches':sum(c['expected_gate']=='fail' for c in rows),
        'modified_policy_matches':sum(c['gate_matched'] for c in rows),
        'verified_correct_matches':sum(c['gate_matched'] and c['verification']=='verified' for c in rows),
        'total':len(rows),'rows':rows}
    with args.out.open('x') as stream:json.dump(payload,stream,indent=2);stream.write('\n')
    print(json.dumps({k:v for k,v in payload.items() if k!='rows'}))
if __name__=='__main__': main()
