"""Inventory declared policy coverage for an explicitly bounded tracked scope."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from drift_gate.adapters.policy_loader import load_policy
from drift_gate.utils.glob_matcher import matches_any

def included(path):
    return ((path.startswith('drift_gate/') and path.endswith('.py') and not path.startswith('drift_gate/tests/'))
        or (path.startswith('desktop-ui/src/') and path.endswith(('.ts', '.tsx', '.css')))
        or path.startswith(('packaging/', '.github/workflows/'))
        or path in ['scripts/check_self.py', 'main.py', 'pyproject.toml', 'action.yml',
                    'desktop-ui/package.json', 'desktop-ui/package-lock.json', 'desktop-ui/vite.config.ts',
                    'drift_gate/adapters/parser_hashes.json'])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    out = parser.parse_args().out
    if out.exists():
        parser.error('Use a new output path')
    policy = load_policy(ROOT / '.drift-gate.self.yml')
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().strip('\0').split('\0')
    rows = [{'path': p, 'ignored': matches_any(p, policy.ignore_paths),
             'rules': [r.id for r in policy.rules if matches_any(p, r.when.any_changed)]}
            for p in paths if included(p)]
    out.write_text(json.dumps({'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'scope': 'Tracked Python product files including __init__, UI ts/tsx/css, packaging, workflows, explicit build config; excludes Python tests and other audit scripts, retains UI tests as ignored.',
        'files': rows}, ensure_ascii=False, indent=2) + '\n')

if __name__ == '__main__':
    main()
