"""Authored stale/current Git controls retained as actual portable disk bundles."""
import argparse
from datetime import date
from hashlib import sha256
from pathlib import Path
import shutil
import subprocess
import tempfile

from drift_gate.adapters.evidence_bundle import load_bundle, save_bundle
from drift_gate.adapters.execution import atomic_json
from drift_gate.adapters.git.immutable import collect_git_snapshot
from drift_gate.adapters.inspection import inspect_snapshot
from drift_gate.core.models.evaluation_context import EvaluationContext
from drift_gate.desktop.package_git_check import POLICY, source


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.out_dir.resolve()
    if (output / 'probe-results.json').exists() or (output / 'probe-store').exists():
        parser.error('Use a new output directory; existing evidence must not be overwritten')
    output.mkdir(parents=True, exist_ok=True)
    selected_policy = POLICY.replace('api-routes', 'auto-strict')
    pin = sha256(selected_policy.encode()).hexdigest()
    controls = {}
    bundles = {}
    with tempfile.TemporaryDirectory(prefix='driftgate-bundle-probe-') as directory:
        root = Path(directory)
        def git(*arguments):
            return subprocess.check_output(['git', '-c', 'core.autocrlf=false', *arguments],
                                           cwd=root, stderr=subprocess.PIPE)
        def commit(message):
            git('add', '.')
            git('-c', 'user.name=Bundle control', '-c', 'user.email=fixture@example.invalid',
                'commit', '-m', message)
            return git('rev-parse', 'HEAD').decode('ascii').strip()
        git('init')
        (root / 'src').mkdir(); (root / 'docs').mkdir()
        (root / '.drift-gate.yml').write_bytes(selected_policy.encode())
        (root / 'src/api.py').write_bytes(source('/old').encode())
        (root / 'docs/api.md').write_bytes(b'GET /old\r\n')
        base = commit('before')
        (root / 'src/api.py').write_bytes(source('/new').encode())
        stale = commit('stale')
        (root / 'docs/api.md').write_bytes(b'GET /new\r\n')
        current = commit('current')
        for name, head, expected in [('stale', stale, 'fail'), ('current', current, 'pass')]:
            snapshot = collect_git_snapshot(root=root, base=base, head=head,
                trusted_policy_ref=base, trusted_policy_sha256=pin, contract_proofs=True,
                context=EvaluationContext(date(2026, 10, 8)))
            result = inspect_snapshot(snapshot)
            bundle = save_bundle(result, output / 'probe-store')
            raw = bundle.snapshot.git_evidence.get(head, 'src/api.py').content
            assert result.result == expected
            assert raw == source('/new').encode() and b'\r\n' in raw
            bundles[name] = bundle
            controls[name] = {'bundle_id': bundle.path.name, 'gate': result.result,
                'verification': result.verification, 'receipt_sha256': bundle.path.name,
                'source_raw_sha256': sha256(raw).hexdigest(), 'crlf_preserved': True,
                'shadow_records': len(result.to_dict()['contract_diagnostics']['entries'])}
        shutil.rmtree(root / '.git')
        (root / 'src/api.py').unlink()
        (root / '.drift-gate.yml').unlink()
        for name, original in bundles.items():
            loaded = load_bundle(original.path, expected_receipt_sha256=original.path.name)
            replay = loaded.replay()
            assert replay.execution['bundle_replay']['recorded_result_matches_current']
            controls[name]['replay_after_repository_removed'] = replay.execution['bundle_replay']
    files = {path.relative_to(output).as_posix(): sha256(path.read_bytes()).hexdigest()
             for path in (output / 'probe-store').rglob('*') if path.is_file()}
    atomic_json(output / 'probe-results.json', {'schema': 'authored-bundle-controls-v1',
        'cases': controls, 'file_hashes': files, 'policy_pin': pin,
        'scope': 'authored-static-fastapi-fixtures-not-production-accuracy'})


if __name__ == '__main__':
    main()
