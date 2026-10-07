"""Small offline Git-object controls executed inside the frozen product."""
from hashlib import sha256
from pathlib import Path
import subprocess
import tempfile

from drift_gate.adapters.git.immutable import collect_git_snapshot
from drift_gate.adapters.inspection import inspect_snapshot
from drift_gate.core.models.git_input import object_oid


POLICY = """rules:
  - id: pinned-api
    when:
      any_changed: [src/**]
    require:
      groups:
        - name: api-contract
          any_changed: [docs/api.md]
          content: api-routes
    severity: blocker
"""


def source(route):
    return f"from fastapi import FastAPI\r\napp = FastAPI()\r\n@app.get('{route}')\r\ndef api(): return {{}}\r\n"


def run_git_controls():
    with tempfile.TemporaryDirectory(prefix='driftgate-git-objects-') as directory:
        root = Path(directory)
        def git(*args):
            return subprocess.check_output(['git', '-c', 'core.autocrlf=false', *args], cwd=root, stderr=subprocess.PIPE)
        def commit(message):
            git('add', '.'); git('-c', 'user.name=Object control', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', message)
            return git('rev-parse', 'HEAD').decode('ascii').strip()
        git('init'); (root / 'src').mkdir(); (root / 'docs').mkdir()
        (root / '.drift-gate.yml').write_bytes(POLICY.encode())
        (root / 'src/api.py').write_bytes(source('/old').encode())
        (root / 'docs/api.md').write_bytes(b'GET /old\n')
        base = commit('approved policy and old API')
        (root / 'src/api.py').write_bytes(source('/new').encode())
        stale = commit('stale document')
        (root / 'docs/api.md').write_bytes(b'GET /new\n')
        current = commit('current document')
        pin = sha256(POLICY.encode()).hexdigest()
        def inspect(head, digest=pin):
            return inspect_snapshot(collect_git_snapshot(root=root, base=base, head=head,
                trusted_policy_ref=base, trusted_policy_sha256=digest)).to_dict()
        old_result, new_result = inspect(stale), inspect(current)
        (root / '.drift-gate.yml').write_bytes(POLICY.replace('severity: blocker', 'severity: minor').encode())
        weakened = commit('weakened candidate')
        rejected = {}
        for name, head, digest in [('wrong-pin', current, '0' * 64), ('weakened-policy', weakened, pin)]:
            try:
                inspect(head, digest)
            except ValueError as exc:
                rejected[name] = str(exc)
            else:
                raise RuntimeError(f'Immutable package control accepted {name}')
        (root / 'src/api.py').write_bytes(source('/uncommitted').encode())
        (root / '.drift-gate.yml').write_bytes(b'rules: []\n')
        replay = inspect(stale)
        evidence = old_result['execution']['input_capture']['git_input']
        entries = evidence['artifacts']
        after = next(a for a in entries if a['revision'] == stale and a['path'] == 'src/api.py')
        checks = {'stale_document_rejected': old_result['result'] == 'fail',
                  'current_document_accepted': new_result['result'] == 'pass',
                  'wrong_pin_rejected': 'SHA-256' in rejected['wrong-pin'],
                  'weakening_rejected': 'weakened' in rejected['weakened-policy'],
                  'working_tree_ignored': replay['rule_decisions'] == old_result['rule_decisions'],
                  'original_crlf_bytes_bound': after['raw_sha256'] == sha256(source('/new').encode()).hexdigest()}
        if not all(checks.values()):
            raise RuntimeError('Frozen Git object/policy controls failed')
        return {'schema': 'packaged-git-controls-v1', 'checks': checks,
                'subject': {'base': base, 'stale': stale, 'current': current, 'weakened': weakened},
                'policy_pin': pin, 'rejected': rejected,
                'cases': {'stale': old_result, 'current': new_result, 'working-tree-edited': replay}}


def validate_git_controls(data):
    expected_checks = {'stale_document_rejected', 'current_document_accepted', 'wrong_pin_rejected',
                       'weakening_rejected', 'working_tree_ignored', 'original_crlf_bytes_bound'}
    if (data.get('schema') != 'packaged-git-controls-v1' or set(data.get('checks', {})) != expected_checks
        or any(value is not True for value in data['checks'].values())):
        raise RuntimeError('Missing packaged Git object/policy controls')
    expected_pin = sha256(POLICY.encode()).hexdigest()
    if data.get('policy_pin') != expected_pin:
        raise RuntimeError('Packaged policy control does not match frozen fixture')
    for case, expected in [('stale', 'fail'), ('current', 'pass'), ('working-tree-edited', 'fail')]:
        result = data['cases'][case]
        git = result['execution']['input_capture']['git_input']
        if (result['result'] != expected or git['policy_anchor']['sha256'] != expected_pin
            or git['policy_anchor']['organization_approval_verified']
            or git['subject']['base_oid'] != data['subject']['base']
            or git['subject']['head_oid'] != data['subject']['current' if case == 'current' else 'stale']):
            raise RuntimeError('Packaged Git/policy control identity mismatch')
        entry = next((a for a in git['artifacts'] if a['path'] == 'src/api.py'
                      and a['revision'] == git['subject']['head_oid']), None)
        raw = source('/new').encode()
        if (entry is None or entry['raw_sha256'] != sha256(raw).hexdigest()
            or entry['object_id'] != object_oid('blob', raw, len(entry['object_id']))):
            raise RuntimeError('Packaged raw Git blob does not match frozen fixture')
