"""Check pending implementation files including new modules, without staging the user's index.

The temporary repository contains a projection of changed files and required
contracts, not the complete original repository. The report declares that scope.
"""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts.check_self import inspect_repository


def git(root, *args):
    return subprocess.check_output(['git', '-c', 'core.autocrlf=false', '-c', 'commit.gpgSign=false',
        '-c', 'core.hooksPath=/dev/null', *args], cwd=root, stderr=subprocess.PIPE)


def main():
    head = git(ROOT, 'rev-parse', 'HEAD').decode().strip()
    changed = git(ROOT, 'diff', '--name-only', '--diff-filter=ACMR', head).decode().splitlines()
    new = git(ROOT, 'ls-files', '--others', '--exclude-standard').decode().splitlines()
    changed += [path for path in new if path.startswith('drift_gate/') and path.endswith('.py')
                or path in {'scripts/check_focused.py', 'docs/focused-python.md'}]
    required = ['.drift-gate.self.yml', 'docs/contracts/gate-and-inputs.md', 'docs/contracts/mcp-transport.md',
                'docs/contracts/progress-storage.md', 'docs/contracts/desktop-bridge.md', 'docs/ops/drift-gate-self-check.md']
    paths = sorted(set(changed + required))
    with TemporaryDirectory(prefix='driftgate-pending-self-') as temporary:
        root = Path(temporary)
        git(root, 'init', '-q')
        for path in paths:
            try:
                raw = git(ROOT, 'show', f'{head}:{path}')
            except subprocess.CalledProcessError:
                continue  # new implementation files have no baseline blob
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        git(root, 'add', '-A')
        git(root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'baseline projection')
        base = git(root, 'rev-parse', 'HEAD').decode().strip()
        for path in paths:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / path).read_bytes())
        git(root, 'add', '-A')  # only the disposable repository index is staged
        report = inspect_repository(root, base, base)
        report['projection'] = {'source_head': head, 'kind': 'pending implementation paths and required contracts',
                                'paths': paths, 'complete_repository': False, 'user_index_changed': False}
        target = Path(__file__).with_name('self-check.json')
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'gate': report['evaluation']['result'], 'paths': len(paths), 'report': str(target)}))
        return int(report['evaluation']['result'] == 'fail')


if __name__ == '__main__':
    raise SystemExit(main())
