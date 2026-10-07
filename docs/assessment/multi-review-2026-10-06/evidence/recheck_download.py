"""Repeat original downloaded DMG execution in a guaranteed-new output directory."""
from pathlib import Path
import importlib.util
import json
import shutil
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'packaging/verify_package.py').is_file())
OLD=ROOT/'build/hardening-final-20261006/d262ec2'
OUT=ROOT/'build/multi-review-confirmation/fresh-downloaded'
OUT.mkdir(parents=True,exist_ok=False)
shutil.copyfile(OLD/'desktop-ci.json',OUT/'desktop-ci.json')
spec=importlib.util.spec_from_file_location('original_downloader',OLD/'verify_download.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.OUT=OUT
sys.argv=[str(__file__),str(OLD/'download/DriftGate-macOS-arm64.dmg')]
module.main()
result=json.loads((OUT/'downloaded-installed/result.json').read_text())
phases={'grammar':result['scan']['result'],**{c['case']:c['result'] for c in result['hardening_checks']}}
ids=[r['execution']['run_id'] for r in phases.values()]
assert len(set(ids))==3
old=json.loads((OLD/'downloaded-installed/result.json').read_text())
assert not set(ids)&{old['scan']['result']['execution']['run_id'],*(c['result']['execution']['run_id'] for c in old['hardening_checks'])}
sig=phases['signature']['violations'][0]['trigger_files']
ren=phases['rename']['violations'][0]['trigger_files']
assert len(sig)==1 and sig[0]['path']=='src/api.py'
assert '+        *extra,' in sig[0]['patch'] and '+        **options,' in sig[0]['patch']
assert len(ren)==1 and ren[0]['path']=='docs/api.py' and ren[0]['previous_path']=='src/api.py' and ren[0]['status']=='renamed'
summary={'fresh_output_required':True,'phase_ids':ids,'three_distinct_runs':True,'different_from_previous':True,'signature_diff_checked':True,'rename_endpoints_checked':True,'receipt':str(OUT/'downloaded-validation.json')}
(Path(__file__).parent/'fresh-download-results.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
