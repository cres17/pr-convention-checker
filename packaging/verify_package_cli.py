"""Check evidence storage, verification, replay, spans and run journals in a packaged executable.

Runs the shipped executable in headless ``--cli`` mode against a fresh Git
fixture (design W16): the bundle is written by the installed artifact, verified
and replayed by it after the repository is deleted, and its run journal is read
back. Results are compared with structural expectations, not with this
checkout's code.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

POLICY = """rules:
  - id: api-docs
    when: {any_changed: ['src/**']}
    require: {groups: [{name: API docs, any_changed: ['docs/api.md'], content: api-routes}]}
    severity: blocker
"""
ROUTE = 'from fastapi import FastAPI\napp = FastAPI()\n@app.get("{path}")\ndef h():\n    return 1\n'


def git(root, *args):
    return subprocess.check_output(['git', '-c', 'core.autocrlf=false', *args], cwd=root,
                                   stderr=subprocess.PIPE).decode().strip()


def commit(root, message):
    git(root, 'add', '-A')
    git(root, '-c', 'user.name=Package check', '-c', 'user.email=fixture@example.invalid', 'commit', '-q', '-m', message)
    return git(root, 'rev-parse', 'HEAD')


def fixture(root):
    root.mkdir(parents=True)
    git(root, 'init', '-q')
    (root / 'src').mkdir(); (root / 'docs').mkdir()
    (root / '.drift-gate.yml').write_text(POLICY, encoding='utf-8')
    (root / 'src/api.py').write_text(ROUTE.format(path='/old'), encoding='utf-8')
    (root / 'docs/api.md').write_text('GET /old\n', encoding='utf-8')
    base = commit(root, 'base')
    (root / 'src/api.py').write_text(ROUTE.format(path='/new'), encoding='utf-8')
    return base, commit(root, 'head')


def run(executable, args, cwd, env):
    completed = subprocess.run([str(executable), '--cli', *args], cwd=cwd, env=env, capture_output=True, timeout=180)
    return completed.returncode, completed.stdout.decode('utf-8', 'replace')[-4000:], \
        completed.stderr.decode('utf-8', 'replace')[-4000:]


def remove(path):
    def writable(function, failed, _):
        os.chmod(failed, stat.S_IRWXU)
        function(failed)
    shutil.rmtree(path, onerror=writable)


def verify(executable, output):
    executable = Path(executable).resolve(strict=True)
    output.mkdir(parents=True, exist_ok=False)
    steps = []
    with tempfile.TemporaryDirectory(prefix='driftgate-cli-check-') as temporary:
        root = Path(temporary)
        repo, evidence, runs = root / 'repo', root / 'evidence', root / 'runs'
        base, head = fixture(repo)
        cache = root / 'empty-parser-cache'
        cache.mkdir()
        env = {**os.environ, 'TREE_SITTER_LANGUAGE_PACK_CACHE_DIR': str(cache),
               'TREE_SITTER_LANGUAGE_PACK_LIBS_DIR': str(root / 'absent-user-libraries'), 'QT_QPA_PLATFORM': 'offscreen'}

        def step(name, args, cwd, expected_codes, out):
            code, stdout, stderr = run(executable, [*args, '--out-json', str(out)], cwd, env)
            data = json.loads(out.read_text(encoding='utf-8')) if out.exists() else None
            steps.append({'step': name, 'exit_code': code, 'expected': list(expected_codes),
                          'stderr_tail': stderr[-800:], 'ok': code in expected_codes and data is not None})
            if code not in expected_codes or data is None:
                raise RuntimeError(f'{name} failed with exit {code}: {stderr[-800:]}')
            return data

        pin = sha256(POLICY.encode()).hexdigest()
        check = step('check-with-evidence-and-journal',
                     ['check', '--base', base, '--head', head, '--trusted-policy-ref', base,
                      '--trusted-policy-sha256', pin, '--evidence-store', str(evidence), '--run-store', str(runs),
                      '--json'], repo, {1}, root / 'check.json')
        if check['result'] != 'fail' or check['execution']['run']['state'] != 'publication-skipped':
            raise RuntimeError('packaged check produced an unexpected result or run state')
        bundle = check['execution']['evidence_bundle']['path']
        remove(repo)  # replay must not need the repository
        verify_data = step('bundle-verify', ['bundle', 'verify', bundle, '--json'], root, {0}, root / 'verify.json')
        replay = step('bundle-replay', ['bundle', 'replay', bundle, '--json'], root, {1}, root / 'replay.json')
        if not replay['execution']['bundle_replay']['recorded_result_matches_current']:
            raise RuntimeError('packaged replay did not reproduce the stored result')
        spans = step('bundle-spans', ['bundle', 'spans', bundle], root, {0}, root / 'spans.json')
        if spans['total'] == 0 or spans['verified'] != spans['total']:
            raise RuntimeError('packaged span verification failed')
        frozen_producer = verify_data['receipt']['producer']
    summary = {'schema': 'packaged-cli-check-v1', 'executable': str(executable),
               'executable_sha256': sha256(executable.read_bytes()).hexdigest(), 'steps': steps,
               'gate_result': check['result'], 'run_history': check['execution']['run']['history'],
               'receipt_sha256': check['execution']['evidence_bundle']['receipt_sha256'],
               'replay_matches': True, 'spans_verified': spans['verified'],
               'producer': frozen_producer, 'repository_deleted_before_replay': True,
               'platform': sys.platform}
    (output / 'result.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"PASS: packaged CLI stored, verified, replayed and span-checked evidence; {output / 'result.json'}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path)
    parser.add_argument('--output', type=Path, default=Path('build/offline-cli'))
    args = parser.parse_args()
    verify(args.executable, args.output)
