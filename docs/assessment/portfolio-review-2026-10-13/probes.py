import json
from pathlib import Path
from jsonschema import Draft202012Validator as Oracle
from drift_gate.adapters.inspection import inspect
from drift_gate.core.evaluation.compatibility import compare_documents
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.policy.loader import load_policy_from_dict
from drift_gate.adapters import holdout as h
from drift_gate.core.evaluation_stats import score

results={}
def document(schema):
 return {'openapi':'3.1.0','info':{'title':'probe','version':'1'},'paths':{'/x':{'get':{'responses':{'200':{'description':'result','content':{'application/json':{'schema':schema}}}}}}}}
policy=load_policy_from_dict({'rules':[{'id':'compat','when':{'any_changed':['openapi.json']},'require':{'groups':[{'name':'compatible','any_changed':['openapi.json'],'content':'api-compatibility','direction':'response'}]},'severity':'blocker'}]})
for key,old,new,value in [
 ('enum_numeric_overlap', {'oneOf':[{'enum':[1]},{'enum':[1.0]}]}, {'enum':[1]},1),
 ('integer_float_enum', {'type':'string'}, {'type':'integer','enum':[1.0]},1.0),
 ('object_singleton_false_break',{'enum':[{}]}, {'type':'object','additionalProperties':False}, {}),
]:
 before,after=document(old),document(new)
 result=inspect(changed_files=[ChangedFile(path='openapi.json',status='modified',patch='@@ -1 +1 @@\n-'+json.dumps(before)+'\n+'+json.dumps(after)+'\n',before_source=json.dumps(before),after_source=json.dumps(after))], policy=policy)
 results[key]={'old':old,'new':new,'witness':value,'old_accepts':Oracle(old).is_valid(value),'new_accepts':Oracle(new).is_valid(value),'comparison':compare_documents(before,after,'response').to_dict(),'gate':result.result}

# Independent score inputs: a verified violation on an inapplicable rule is wrong, not correct evidence.
results['verified_vs_inapplicable']=score([{'unit_id':'case::rule','case_id':'case','decision':'violated','verification':'verified','expected_support':'supported'}],[{'unit_id':'case::rule','source':'human','label':'not-applicable'}],label_source='human')

case={'case_id':'one','repository':'fixture/repo','source_family':'family','policy':{'rules':[
 {'id':'visible','when':{'any_changed':['src/**']},'require':{'groups':[{'name':'ok','any_changed':['docs/ok.md']}]},'severity':'blocker'},
 {'id':'omitted','when':{'any_changed':['src/**']},'require':{'groups':[{'name':'missing','any_changed':['docs/missing.md']}]},'severity':'blocker'}]},
 'changed_files':[{'path':'src/a.py','status':'modified','patch':'@@\n-x=1\n+x=2\n','before_source':'x=1\n','after_source':'x=2\n'},{'path':'docs/ok.md','status':'modified','patch':'@@\n+updated\n','after_source':'updated\n'}],
 'expected':{'gate':'fail','rules':{'visible':{'decision':'satisfied','support':'supported'}}}}
frozen=h.freeze({'schema':h.CASES,'split':'holdout','cases':[case]},protocol='probe')
r=h.run_frozen(frozen,h.artifact_sha256(frozen))
results['omitted_rule_denominator']={'policy_rules':[x['id'] for x in case['policy']['rules']],'units':r['units'],'cases':r['cases']}
# Write a fresh result through stdout; do not overwrite recorded evidence.
print(json.dumps(results,indent=2))
