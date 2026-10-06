"""Validate staged candidate contents without touching the user's Git index."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
EXCLUDED = {'docs/conversation-summary-2026-10-01.md', 'docs/handoff-2026-10-01.md'}
NEW_PATHS = ['.drift-gate.self.yml', 'scripts/check_self.py',
             'drift_gate/core/python_syntax.py', 'drift_gate/tests/test_self_policy.py',
             'docs/contracts', 'docs/ops/drift-gate-self-check.md']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    changed = subprocess.check_output(['git', 'diff', 'HEAD', '--name-only', '-z'], cwd=ROOT).decode().split('\0')
    paths = {p for p in changed if p and p not in EXCLUDED}
    for name in NEW_PATHS:
        path = ROOT / name
        paths.update(str(p.relative_to(ROOT)) for p in path.rglob('*') if p.is_file()) if path.is_dir() else paths.add(name)
    sources = {}
    with tempfile.TemporaryDirectory(prefix='driftgate-candidate-') as temporary:
        checkout = Path(temporary) / 'checkout'
        subprocess.run(['git', 'clone', '--shared', '--no-checkout', str(ROOT), str(checkout)], check=True, capture_output=True)
        subprocess.run(['git', 'checkout', '--detach', 'HEAD'], cwd=checkout, check=True, capture_output=True)
        for relative in sorted(paths):
            source, target = ROOT / relative, checkout / relative
            if source.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                sources[relative] = hashlib.sha256(source.read_bytes()).hexdigest()
            else:
                target.unlink(missing_ok=True)
        subprocess.run(['git', 'add', '-A'], cwd=checkout, check=True)
        env = {**os.environ, 'PYTHONPATH': str(checkout), 'ANTHROPIC_API_KEY': ''}
        commands = {
            'own-policy': ['scripts/check_self.py', '--base', 'HEAD', '--out', str(out / 'own-policy.json')],
            'own-policy-full-review': ['scripts/check_self.py', '--base', '729a3cd', '--out', str(out / 'own-policy-full-review.json')],
            'example-policy': ['-m', 'drift_gate', 'check', '--base', 'HEAD', '--json', '--anthropic-api-key', ''],
            'review': ['-m', 'drift_gate', 'review', '--base', 'HEAD', '--format', 'json'],
            'policy-controls': ['-m', 'pytest', '-q', 'drift_gate/tests/test_self_policy.py'],
        }
        results = {}
        for name, command in commands.items():
            process = subprocess.run([sys.executable, *command], cwd=checkout, env=env, capture_output=True, timeout=120)
            (out / (name + '.stdout')).write_bytes(process.stdout)
            (out / (name + '.stderr')).write_bytes(process.stderr)
            results[name] = {'exit_code': process.returncode, 'arguments': command}
        own = json.loads((out / 'own-policy.json').read_text())
        assert own['evaluation']['result'] == 'pass', own
        assert all(entry['exit_code'] == 0 for entry in results.values()), results
    receipt = {'base': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
               'scope': 'working candidate copied into isolated checkout and indexed there',
               'excluded_existing_deletions': sorted(EXCLUDED), 'source_sha256': sources, 'commands': results}
    (out / 'manifest.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'gate': own['evaluation']['result'], 'matched': len(own['coverage']['matched']),
                      'unmatched': own['coverage']['unmatched'], 'commands': results}, ensure_ascii=False))


if __name__ == '__main__':
    main()
