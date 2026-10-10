"""Real pinned engine followed by deterministic branch movement before shadow capture."""
import json
import os
import subprocess
import tempfile
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from drift_gate.adapters import engine_artifact as engines
from drift_gate.adapters.trusted_validation import trusted_check

REVIEW = os.environ['DRIFT_GATE_REVIEW_ROOT']

def git(root, *args):
    return subprocess.check_output(['git', '-c', 'core.autocrlf=false', *args], cwd=root, stderr=subprocess.PIPE).decode().strip()

def commit(root, files):
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    git(root, 'add', '.')
    git(root, '-c', 'user.name=review', '-c', 'user.email=review@example.invalid', 'commit', '-qm', 'fixture')
    return git(root, 'rev-parse', 'HEAD')

with tempfile.TemporaryDirectory(prefix='driftgate-ref-review-') as temp:
    root = Path(temp)
    git(root, 'init', '-q')
    engine_commit = git(Path(REVIEW), 'rev-parse', 'ed9f904')
    git(root, 'fetch', '-q', '--no-tags', REVIEW, engine_commit)
    policy = 'rules:\n  - id: docs\n    when: {any_changed: ["src/**"]}\n    require: {groups: [{name: docs, any_changed: ["docs/api.md"]}]}\n    severity: blocker\n'
    source = lambda path: f'from fastapi import FastAPI\napp=FastAPI()\n@app.get("{path}")\ndef h():\n    return 1\n'
    base = commit(root, {'.drift-gate.yml': policy, 'src/api.py': source('/old'), 'docs/api.md': 'GET /old\n'})
    a = commit(root, {'src/api.py': source('/new'), 'docs/api.md': 'GET /new\n'})
    b = commit(root, {'src/api.py': source('/another'), 'docs/api.md': 'GET /another\n'})
    git(root, 'branch', 'candidate', a)
    manifest = engines.build_manifest(root, engine_commit)
    real = engines.run_pinned
    observed = {}
    def after_trusted(*args, **kwargs):
        envelope = real(*args, **kwargs)
        observed['trusted_report'] = json.loads(envelope['stdout'])
        git(root, 'update-ref', 'refs/heads/candidate', b, a)
        return envelope
    with patch.object(engines, 'run_pinned', after_trusted):
        result = trusted_check(root=root, base=base, head='candidate', policy='.drift-gate.yml',
            trusted_policy_ref=base, trusted_policy_sha256=sha256(policy.encode()).hexdigest(), manifest=manifest)
    print(json.dumps({'expected_old_head': a, 'actual_new_head': b, 'result': result,
        'trusted_input_capture': observed['trusted_report'].get('execution', {}).get('input_capture')}, indent=2))
