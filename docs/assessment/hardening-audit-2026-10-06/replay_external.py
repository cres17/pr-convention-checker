"""Replay the imported Linux audit on a clean ae0028d checkout on this host."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
HEAD = 'ae0028d5edd95d5dd4819939a5801cb028639a6b'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True, type=Path)
    out = parser.parse_args().out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='driftgate-imported-review-') as tmp:
        repo = Path(tmp) / 'repo'
        subprocess.run(['git', 'clone', '--shared', '--no-checkout', str(ROOT), str(repo)], check=True, capture_output=True)
        subprocess.run(['git', 'checkout', '--detach', HEAD], cwd=repo, check=True, capture_output=True)
        changes = subprocess.check_output(['git', 'diff', '--name-only', 'f43cada', HEAD], cwd=repo, text=True).splitlines()
        assert all(p.startswith('docs/') for p in changes)
        harness = repo / 'docs/assessment/ai-claim-rejection-2026-10-06/reproduce.py'
        result = subprocess.run([sys.executable, str(harness), '--repo', str(repo), '--out', str(out / 'results.json')],
            cwd=repo, env={**os.environ, 'PYTHONPATH': str(repo)}, capture_output=True, timeout=180)
        (out / 'stdout.log').write_bytes(result.stdout)
        (out / 'stderr.log').write_bytes(result.stderr)
        assert result.returncode == 0, result.stderr.decode(errors='replace')
        original = json.loads((repo / 'docs/assessment/ai-claim-rejection-2026-10-06/results.json').read_text())
        replay = json.loads((out / 'results.json').read_text())
        comparison = {key: {'linux': value['independent_verdict'],
                           'mac': replay['claims'][key]['independent_verdict']} for key, value in original['claims'].items()}
        manifest = {'revision': HEAD, 'platform': platform.platform(), 'python': sys.version,
                    'harness_sha256': hashlib.sha256(harness.read_bytes()).hexdigest(),
                    'source_changes_since_f43cada': changes, 'claim_verdicts': comparison,
                    'same_verdicts': all(v['linux'] == v['mac'] for v in comparison.values())}
        (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(manifest, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
