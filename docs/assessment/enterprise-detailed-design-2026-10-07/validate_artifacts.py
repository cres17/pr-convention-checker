"""Validate the detailed-design document and preserved evidence; no product tests."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('refusing to replace prior verification')
    document = ROOT / 'docs/architecture/drift-gate-enterprise-detailed-design-2026-10-07.md'
    previous_receipt = ROOT / 'docs/assessment/enterprise-update-2026-10-07/verification.json'
    previous = json.loads(previous_receipt.read_text())
    preserved, failures = {}, []
    for group in ('source_hashes', 'regression_hashes', 'frozen_input_hashes', 'evidence_hashes', 'document_hashes'):
        entries = previous[group]
        mismatches = [name for name, expected in entries.items()
                      if not (ROOT / name).is_file() or digest(ROOT / name) != expected]
        preserved[group] = {'checked': len(entries), 'mismatches': mismatches}
        failures.extend(f'{group}:{name}' for name in mismatches)
    docs = (document, HERE / 'README.md')
    checked_links = []
    for path in docs:
        content = path.read_text()
        if re.search(r'[\u3040-\u30ff\u4e00-\u9fff]', content):
            failures.append(f'non-Korean language residue:{path.name}')
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', content):
            if '://' in target or target.startswith('#'):
                continue
            resolved = (path.parent / target.split('#', 1)[0]).resolve()
            exists = resolved.is_file() or resolved == args.out.resolve()
            checked_links.append({'document': str(path.relative_to(ROOT)), 'target': target, 'exists': exists})
            if not exists:
                failures.append(f'broken link:{target}')
        for snippet in re.findall(r'```json\n(.*?)\n```', content, re.DOTALL):
            json.loads(snippet)
    model_path = HERE / 'model-check-final.json'
    model = json.loads(model_path.read_text())
    if not model['passed'] or model['failures']:
        failures.append('finite model failed')
    if model['script_sha256'] != digest(HERE / 'check_design.py'):
        failures.append('model script hash mismatch')
    before = digest(model_path)
    overwrite = subprocess.run([sys.executable, str(HERE / 'check_design.py'), '--out', str(model_path)],
                               capture_output=True, text=True, check=False)
    overwrite_rejected = overwrite.returncode == 2 and digest(model_path) == before
    if not overwrite_rejected:
        failures.append('existing model evidence was not protected')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip()
    hashes = {str(path.relative_to(ROOT)): digest(path)
              for path in (*docs, HERE / 'check_design.py', HERE / 'validate_artifacts.py',
                           HERE / 'model-check.json', model_path, previous_receipt)}
    result = {'schema': 'detailed-design-verification-v1', 'recorded_at': datetime.now(timezone.utc).isoformat(),
              'head': head, 'branch': branch, 'state': 'uncommitted-working-tree',
              'preserved_previous_receipt_entries': preserved, 'local_links': checked_links,
              'final_model_counts': model['counts'], 'model_hash_matches': model['script_sha256'] == digest(HERE / 'check_design.py'),
              'existing_evidence_overwrite_rejected': overwrite_rejected,
              'artifact_hashes': hashes, 'failures': failures, 'passed': not failures,
              'scope': 'Design document, reference model and evidence preservation only.',
              'unverified': ['Production full test suite not rerun in this design turn.',
                             'No production parser/scope soundness or real concurrent publisher verification.',
                             'No latest remote CI, installed artifact, OS matrix or independent human holdout.'],
              'git_mutations': 'No commit or push in this design turn.'}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'passed': result['passed'], 'preserved': preserved,
                      'local_link_count': len(checked_links), 'failures': failures}, ensure_ascii=False, indent=2))
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
