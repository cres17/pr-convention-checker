"""Load test for the whole-inspection budget (design W12, review 791565f item 18).

Builds a synthetic Git repository with many Python modules, then runs ``drift-gate scope``
in a child process twice: with the default budget and with ``max_total_bytes`` set below
the repository's module bytes. Records wall time, the child's peak RSS and whether the
over-budget run stopped with ``resource_limit`` before reading object contents.

This measures one synthetic shape on one machine. It is not a capacity guarantee.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def git(root, *args):
    return subprocess.check_output(['git', '-c', 'core.autocrlf=false', *args], cwd=root, stderr=subprocess.PIPE)


def build(root, modules, module_bytes, budget):
    git(root, 'init', '-q')
    policy = ('rules:\n  - id: api\n    when: {any_changed: ["svc/**"]}\n'
              '    require: {groups: [{name: docs, any_changed: ["docs/api.md"]}]}\n    severity: major\n')
    if budget:
        policy += 'budget: {' + ', '.join(f'{k}: {v}' for k, v in budget.items()) + '}\n'
    (root / '.drift-gate.yml').write_text(policy, encoding='utf-8', newline='\n')
    (root / 'docs').mkdir()
    (root / 'docs/api.md').write_text('GET /health\n', encoding='utf-8', newline='\n')
    filler = '# ' + 'x' * 70 + '\n'
    body = filler * max(1, module_bytes // len(filler))
    for index in range(modules):
        path = root / 'svc' / f'pkg{index // 500}' / f'mod{index}.py'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'import os\nVALUE = os.getenv("KEY_{index}")\n' + body, encoding='utf-8', newline='\n')
    git(root, 'add', '-A')
    git(root, '-c', 'user.name=Load', '-c', 'user.email=load@example.invalid', 'commit', '-q', '-m', 'base')
    return git(root, 'rev-parse', 'HEAD').decode().strip(), policy


CHILD = r'''
import json, resource, sys, time
from drift_gate.adapters.cli.runner import run_cli
started = time.monotonic()
try:
    run_cli(sys.argv[1:])
    code = 0
except SystemExit as exc:
    code = exc.code
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
sys.stderr.write(json.dumps({'exit': code, 'seconds': round(time.monotonic() - started, 3), 'peak_rss_raw': peak}))
'''


def run_scope(root, head, policy, out):
    args = ['scope', '--base', head, '--head', head, '--trusted-policy-ref', head,
            '--trusted-policy-sha256', sha256(policy.encode()).hexdigest(), '--out-json', str(out)]
    env = {**os.environ, 'PYTHONPATH': str(ROOT)}
    completed = subprocess.run([sys.executable, '-c', CHILD, *args], cwd=root, env=env, capture_output=True,
                               text=True, timeout=1800)
    stats = json.loads(completed.stderr.strip().splitlines()[-1])
    # ru_maxrss is KiB on Linux and bytes on macOS.
    stats['peak_rss_bytes'] = stats.pop('peak_rss_raw') * (1 if sys.platform == 'darwin' else 1024)
    report = json.loads(out.read_text(encoding='utf-8'))
    stats['complete'] = report.get('complete')
    stats['resource_limit'] = report.get('resource_limit') or (report.get('error') or {}).get('resource')
    stats['budget_usage'] = (report.get('budget') or {}).get('usage')
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--modules', type=int, default=4000)
    parser.add_argument('--module-bytes', type=int, default=20_000)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit(f'{args.out} exists; results are never overwritten')
    total = args.modules * args.module_bytes
    rows = {}
    for name, budget in (('default-budget', None), ('bytes-below-repository', {'max_total_bytes': total // 4})):
        with tempfile.TemporaryDirectory(prefix='driftgate-load-') as temporary:
            root = Path(temporary)
            head, policy = build(root, args.modules, args.module_bytes, budget)
            rows[name] = {'budget': budget, **run_scope(root, head, policy, root / 'scope.json')}
    result = {'schema': 'budget-load-test-v1', 'modules': args.modules, 'module_bytes': args.module_bytes,
              'approximate_module_bytes_total': total, 'python': sys.version.split()[0],
              'platform': platform.platform(), 'runs': rows,
              'interpretation': 'one synthetic repository shape on one machine; not a capacity guarantee'}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, 'x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps({name: {k: row[k] for k in ('exit', 'seconds', 'peak_rss_bytes', 'complete')}
                      for name, row in rows.items()}))


if __name__ == '__main__':
    main()
