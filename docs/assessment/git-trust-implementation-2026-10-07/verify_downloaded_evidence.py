"""Recheck downloaded native result JSON; this does not execute an installer."""
import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from drift_gate.desktop.package_git_check import validate_git_controls

spec = importlib.util.spec_from_file_location('native_package_verifier', ROOT / 'packaging/verify_package.py')
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    reports = sorted(args.directory.rglob('result.json'))
    if not reports:
        raise SystemExit('No native verification result JSON found')
    cases = []
    for report in reports:
        data = json.loads(report.read_text(encoding='utf-8'))
        verifier.validate(data)
        validate_git_controls(data.get('git_object_checks', {}))
        if any(Path(name).suffix in {'.so', '.dll', '.dylib'}
               for name in data.get('fresh_cache_files', [])):
            raise SystemExit('Parser cache contains downloaded native libraries')
        cases.append({'path': str(report.relative_to(args.directory)),
                      'sha256': sha256(report.read_bytes()).hexdigest(),
                      'bytes': report.stat().st_size,
                      'frozen': data['frozen'], 'bridge_ready': data['bridge_ready'],
                      'network_isolation': data.get('isolation'),
                      'grammar_analyses': sum(n['method'] == 'grammar+heuristic'
                          for n in data['scan']['result']['scan_metrics']['analysis_notes']),
                      'git_object_checks': data['git_object_checks']['checks'],
                      'verification_identity': data['verification']})
    args.out.write_text(json.dumps({'schema': 'native-evidence-recheck-v1',
        'kind': 'downloaded JSON protocol validation, not installer execution',
        'passed': len(cases), 'cases': cases}, indent=2) + '\n', encoding='utf-8')
    print(f'{len(cases)} downloaded native reports validated')


if __name__ == '__main__':
    main()
