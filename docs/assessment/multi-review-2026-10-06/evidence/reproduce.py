"""Adversarial package verification probes; never changes production code."""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import shutil

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'packaging/verify_package.py').is_file())
OUT = ROOT / 'build/multi-review-confirmation/evidence'
OUT.mkdir(parents=True, exist_ok=True)
FINAL = ROOT / 'build/hardening-final-20261006/d262ec2'
spec = importlib.util.spec_from_file_location('verifier', ROOT / 'packaging/verify_package.py')
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)
valid = json.loads((FINAL / 'downloaded-installed/result.json').read_text())
results = {}
receipt = json.loads((FINAL / 'final-validation.json').read_text())
results['receipt'] = {
    'files': len(receipt['files']),
    'mismatches': [p for p, h in receipt['files'].items()
                   if hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != h],
    'dmg_matches': hashlib.sha256((FINAL / 'download/DriftGate-macOS-arm64.dmg').read_bytes()).hexdigest() == receipt['dmg_sha256'],
}

# The checker accepts the exact same unrelated eight-file result for both
# hardening phases, with no signature or rename actually present.
mutated = copy.deepcopy(valid)
for check in mutated['hardening_checks']:
    check['result'] = copy.deepcopy(mutated['scan']['result'])
verifier.validate(mutated)
results['unrelated_hardening_result'] = {'accepted': True, 'description': 'Both signature and rename replaced by initial eight-file scan'}
(OUT / 'unrelated-hardening-result.json').write_text(json.dumps(mutated, indent=2))

# Real subprocess, real macOS OS sandbox. The executable simply exits zero,
# while the output directory already contains an older successful report.
app = OUT / 'empty-app.app/Contents'
exe = app / 'MacOS/DriftGate'
exe.parent.mkdir(parents=True, exist_ok=True)
exe.write_text('#!/bin/sh\nexit 0\n')
exe.chmod(0o755)
grammar = app / 'Frameworks/drift_gate/grammars'
grammar.mkdir(parents=True, exist_ok=True)
manifest = json.loads((FINAL / 'downloaded-installed/bundled-grammars.json').read_text())
# Preserve library-name structure. Nothing is loaded by the dummy process.
for item in manifest['libraries']:
    (grammar / item['name']).write_bytes(b'not a native library')
(grammar / 'manifest.json').write_text(json.dumps(manifest))
stale = OUT / 'stale-output'
stale.mkdir(exist_ok=True)
shutil.copyfile(FINAL / 'downloaded-installed/result.json', stale / 'result.json')
old_run = valid['scan']['result']['execution']['run_id']
try:
    verifier.verify(exe, stale)
except Exception as exc:
    results['stale_report'] = {'accepted': False, 'error': str(exc)}
else:
    actual = json.loads((stale / 'result.json').read_text())
    results['stale_report'] = {'accepted': True, 'same_run_id': actual['scan']['result']['execution']['run_id'] == old_run, 'exe': str(exe)}
fresh = OUT / 'fresh-empty-control'
shutil.rmtree(fresh, ignore_errors=True)
try:
    verifier.verify(exe, fresh)
except Exception as exc:
    results['fresh_empty_control'] = {'accepted': False, 'error': str(exc)}
else:
    results['fresh_empty_control'] = {'accepted': True}
(OUT / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
print(json.dumps(results, indent=2))
