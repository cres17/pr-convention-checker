"""Cross-check preserved reports beyond the product verifier's assertions."""
import hashlib
import json
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'packaging/verify_package.py').is_file())
FINAL=ROOT/'build/hardening-final-20261006/d262ec2'
receipt=json.loads((FINAL/'final-validation.json').read_text())
assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in receipt['files'].items())
reports=[FINAL/'downloaded-installed/result.json',*sorted((FINAL/'remote-evidence').glob('*/offline-*/result.json'))]
results=[]
for path in reports:
    r=json.loads(path.read_text())
    checks={c['case']:c['result'] for c in r['hardening_checks']}
    ids=[r['scan']['result']['execution']['run_id'],*(c['execution']['run_id'] for c in checks.values())]
    assert len(set(ids))==3
    sig=checks['signature']['violations'][0]['trigger_files']
    ren=checks['rename']['violations'][0]['trigger_files']
    assert len(sig)==1 and sig[0]['path']=='src/api.py'
    assert '+        *extra,' in sig[0]['patch'] and '+        **options,' in sig[0]['patch']
    assert len(ren)==1 and ren[0]['path']=='docs/api.py' and ren[0]['previous_path']=='src/api.py' and ren[0]['status']=='renamed'
    results.append({'path':str(path.relative_to(ROOT)),'distinct_phase_ids':ids,'signature_and_rename_payloads_match':True})
(Path(__file__).parent/'saved-phase-results.json').write_text(json.dumps({'hashes_checked':len(receipt['files']),'reports':results},indent=2)+'\n')
print(f'{len(receipt["files"])} hashes, {len(results)} reports: distinct phase IDs and exact signature/rename inputs confirmed')
