"""Published evidence is complete, bounded, byte-exact and never approval authority."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

import pytest

from drift_gate.adapters import evidence_bundle as store
from drift_gate.adapters.bundle_codec import BundleError, semantic_result
from drift_gate.adapters.cli.runner import run_cli
from drift_gate.adapters.inspection import inspect_snapshot
from drift_gate.core.models.input_manifest import ArtifactState, canonical_bytes
from drift_gate.core.models.result import DriftIgnoreDirective
from drift_gate.core.policy.loader import load_policy_from_text
from drift_gate.tests.test_input_snapshot import capture, POLICY_TEXT
from drift_gate.tests.test_git_immutable import repo as repository_fixture, capture as capture_git


@pytest.fixture
def result():
    source = POLICY_TEXT.replace('api-routes', 'auto-strict')
    return inspect_snapshot(capture(contract_proofs=True, policy_source=source,
                                    policy=load_policy_from_text(source)))


@pytest.fixture
def git_repository(tmp_path):
    return repository_fixture.__wrapped__(tmp_path)


def published(root):
    parent = root / 'bundles'
    return [p for p in parent.iterdir() if not p.name.startswith('.')] if parent.exists() else []


def reseal(path, *, receipt_edit=None, result_edit=None):
    """Model an unsigned whole-bundle rewrite, not just accidental corruption."""
    receipt = json.loads((path / store.RECEIPT).read_bytes())
    if result_edit:
        data = json.loads((path / 'result.json').read_bytes())
        result_edit(data)
        raw = canonical_bytes(data)
        (path / 'result.json').write_bytes(raw)
        receipt['files']['result.json'] = {'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)}
        receipt['result_sha256'] = sha256(raw).hexdigest()
    if receipt_edit:
        receipt_edit(receipt)
    raw = canonical_bytes(receipt)
    (path / store.RECEIPT).write_bytes(raw)
    (path / store.COMMIT).write_bytes(canonical_bytes(store._commit(raw)))
    target = path.with_name(sha256(raw).hexdigest())
    path.rename(target)
    return target


def fake_pass(data):
    data.update(result='pass', violations=[], rule_decisions=[], verification='not-applicable')
    data['summary'].update(gate_decision='pass', blocker=0, major=0, minor=0, nit=0,
                           undetermined_rules=0, unverified_rules=0)
    data['scan_metrics']['evaluated_rules'] = 0


def remove_git_fixture(path):
    # Windows Git marks loose objects read-only. This changes only a disposable
    # fixture before deletion; a failure to delete it must not fake no-Git replay.
    def retry_readonly(function, failed_path, error):
        if not isinstance(error[1], PermissionError):
            raise error[1]
        os.chmod(failed_path, stat.S_IRWXU)
        function(failed_path)
    shutil.rmtree(path, onerror=retry_readonly)


def test_disk_roundtrip_retains_full_shadow_proofs_and_attempt_identity(tmp_path, result):
    bundle = store.save_bundle(result, tmp_path)
    assert bundle.snapshot == result.input_snapshot
    assert bundle.recorded_result == result.to_dict()
    assert bundle.receipt['run_id'] == result.execution['run_id']
    assert bundle.recorded_result['contract_diagnostics']['entries']
    assert bundle.receipt['producer_authenticated'] is False
    replay = bundle.replay()
    assert replay.execution['run_id'] != result.execution['run_id']
    assert replay.execution['bundle_replay']['recorded_result_matches_current'] is True
    assert semantic_result(replay.to_dict()) == semantic_result(result.to_dict())
    assert 'GET /old' not in json.dumps(bundle.to_dict())


def test_git_originals_survive_deleted_repository_and_no_git_replay(git_repository, tmp_path, monkeypatch):
    root, _, head = git_repository
    result = inspect_snapshot(capture_git(git_repository, contract_proofs=True))
    bundle = store.save_bundle(result, tmp_path / 'evidence')
    raw = bundle.snapshot.git_evidence.get(head, 'src/api.py').content
    assert b'\r\n' in raw
    assert (bundle.path / ('objects/' + sha256(raw).hexdigest())).read_bytes() == raw
    remove_git_fixture(root / '.git')
    assert not (root / '.git').exists()
    (root / 'src/api.py').unlink()
    from drift_gate.adapters.git import immutable
    monkeypatch.setattr(immutable, '_git', lambda *a, **k: pytest.fail('replay read repository'))
    loaded = store.load_bundle(bundle.path)
    assert loaded.snapshot.git_evidence == result.input_snapshot.git_evidence
    assert loaded.replay().execution['bundle_replay']['recorded_result_matches_current'] is True


def test_same_attempt_is_idempotent_and_new_attempt_is_separate(tmp_path, result):
    first = store.save_bundle(result, tmp_path)
    before = {p.relative_to(first.path): p.read_bytes() for p in first.path.rglob('*') if p.is_file()}
    again = store.save_bundle(result, tmp_path)
    assert first.path == again.path
    assert before == {p.relative_to(first.path): p.read_bytes() for p in first.path.rglob('*') if p.is_file()}
    next_attempt = store.save_bundle(inspect_snapshot(result.input_snapshot), tmp_path)
    assert first.path != next_attempt.path
    assert len(published(tmp_path)) == 2


def test_simultaneous_writers_publish_same_attempt_once(tmp_path, result):
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(lambda _: store.save_bundle(result, tmp_path).path, range(8)))
    assert len(set(paths)) == 1 and len(published(tmp_path)) == 1
    assert not list((tmp_path / 'bundles').glob('.pending-*'))
    store.load_bundle(paths[0])


@pytest.mark.parametrize('where', ['snapshot.json', 'objects', 'receipt.json', 'COMMITTED.json', 'rename'])
def test_failed_write_never_publishes_partial_bundle(tmp_path, result, monkeypatch, where):
    original = store._write_file
    def write(path, raw):
        if path.name == where or where == 'objects' and path.parent.name == 'objects':
            raise OSError('injected storage failure')
        original(path, raw)
    monkeypatch.setattr(store, '_write_file', write)
    if where == 'rename':
        monkeypatch.setattr(store, '_publish_directory', lambda *a: (_ for _ in ()).throw(OSError('injected rename failure')))
    with pytest.raises(OSError, match='injected'):
        store.save_bundle(result, tmp_path)
    assert not published(tmp_path)
    assert not list((tmp_path / 'bundles').glob('.pending-*'))


def test_corruption_before_publication_is_rejected(tmp_path, result, monkeypatch):
    original = store._write_file
    def write(path, raw):
        original(path, raw + b'x' if path.name == 'snapshot.json' else raw)
    monkeypatch.setattr(store, '_write_file', write)
    with pytest.raises(BundleError, match='size|checksum|changed|limit'):
        store.save_bundle(result, tmp_path)
    assert not published(tmp_path)


def test_failure_after_rename_remains_unknown_and_verifiable(tmp_path, result, monkeypatch):
    original = store._sync_directory
    def sync(path):
        if path.name == 'bundles':
            raise OSError('injected parent sync failure')
        original(path)
    monkeypatch.setattr(store, '_sync_directory', sync)
    with pytest.raises(BundleError, match='publication-unknown'):
        store.save_bundle(result, tmp_path)
    assert len(published(tmp_path)) == 1
    existing = store.load_bundle(published(tmp_path)[0])
    assert existing.recorded_result == result.to_dict()
    assert store.save_bundle(result, tmp_path).path == existing.path


@pytest.mark.parametrize('target', ['result.json', 'snapshot.json', 'manifest.json', 'object', 'receipt.json', 'COMMITTED.json'])
def test_tampering_and_missing_files_are_rejected(tmp_path, result, target):
    bundle = store.save_bundle(result, tmp_path)
    path = next((bundle.path / 'objects').iterdir()) if target == 'object' else bundle.path / target
    path.write_bytes(path.read_bytes() + b'X')
    with pytest.raises(BundleError):
        store.load_bundle(bundle.path)
    path.unlink()
    with pytest.raises(BundleError):
        store.load_bundle(bundle.path)


def test_corrupt_existing_bundle_is_never_overwritten(tmp_path, result):
    bundle = store.save_bundle(result, tmp_path)
    (bundle.path / 'result.json').write_bytes(b'corrupt')
    with pytest.raises(BundleError):
        store.save_bundle(result, tmp_path)
    assert (bundle.path / 'result.json').read_bytes() == b'corrupt'


@pytest.mark.parametrize('component', ['bundle', 'objects', 'snapshot.json', 'object'])
def test_symbolic_links_are_not_followed(tmp_path, result, component):
    bundle = store.save_bundle(result, tmp_path / 'store')
    path = {'bundle': bundle.path, 'objects': bundle.path / 'objects',
            'snapshot.json': bundle.path / 'snapshot.json',
            'object': next((bundle.path / 'objects').iterdir())}[component]
    outside = tmp_path / 'outside'
    path.rename(outside)
    try:
        path.symlink_to(outside, target_is_directory=outside.is_dir())
    except OSError:
        pytest.skip('symlink privilege unavailable')
    with pytest.raises(BundleError):
        store.load_bundle(bundle.path)


@pytest.mark.parametrize('field,value', [('max_total_bytes', 200), ('max_file_bytes', 100), ('max_files', 3)])
def test_writer_budget_refuses_before_storage(tmp_path, result, field, value):
    limits = replace(store.BundleLimits(), **{field: value})
    with pytest.raises(BundleError, match='limit'):
        store.save_bundle(result, tmp_path, limits=limits)
    assert not published(tmp_path)


def test_reader_enforces_its_limits_not_receipt_limits(tmp_path, result):
    bundle = store.save_bundle(result, tmp_path)
    with pytest.raises(BundleError, match='limit'):
        store.load_bundle(bundle.path, limits=store.BundleLimits(max_total_bytes=100))
    with pytest.raises(BundleError, match='limit'):
        store.load_bundle(bundle.path, limits=store.BundleLimits(max_files=3))


def test_large_payload_bound_allows_measured_pr_capture():
    limits = store.BundleLimits()
    # No giant allocation: enforce the serialized-size bound with a sized
    # sentinel, then separately exercise real PR I/O in the recorded probe.
    class Sized:
        def __len__(self):
            return 61_752_569
    store._check_files({'snapshot.json': Sized()}, limits, reserved_files=2)
    with pytest.raises(BundleError, match='individual'):
        store._check_files({'snapshot.json': Sized()}, replace(limits, max_file_bytes=8_000_000))


@pytest.mark.parametrize('mutation', ['path', 'negative-size', 'authentication', 'state', 'extra-file'])
def test_resealed_invalid_inventory_and_authority_are_rejected(tmp_path, result, mutation):
    bundle = store.save_bundle(result, tmp_path)
    def edit(receipt):
        if mutation == 'path':
            receipt['files']['../secret'] = receipt['files'].pop('snapshot.json')
        elif mutation == 'negative-size':
            receipt['files']['snapshot.json']['bytes'] = -1
        elif mutation == 'authentication':
            receipt['producer']['authenticated'] = True
        elif mutation == 'state':
            receipt['status'] = 'analyzing'
    path = reseal(bundle.path, receipt_edit=edit)
    if mutation == 'extra-file':
        (path / 'unlisted').write_bytes(b'X')
    with pytest.raises(BundleError):
        store.load_bundle(path)


def test_integrity_does_not_certify_self_consistent_false_result(tmp_path, result):
    bundle = store.save_bundle(result, tmp_path)
    original_digest = bundle.path.name
    forged = reseal(bundle.path, result_edit=fake_pass)
    # An unpinned, wholly rewritten local receipt is not a trust boundary.
    loaded = store.load_bundle(forged)
    assert loaded.receipt['semantic_truth_certified'] is False
    assert loaded.replay().execution['bundle_replay']['recorded_result_matches_current'] is False
    with pytest.raises(BundleError, match='pinned'):
        store.load_bundle(forged, expected_receipt_sha256=original_digest)


def test_verified_waivers_cannot_be_persisted_as_replay_authority(tmp_path):
    snapshot = capture(drift_ignores=[DriftIgnoreDirective('api', 'approved', approval_verified=True)])
    with pytest.raises(BundleError, match='approval authority'):
        store.save_bundle(inspect_snapshot(snapshot), tmp_path)
    assert not published(tmp_path)


def test_resealed_disk_waiver_cannot_assert_adapter_approval(tmp_path):
    original = inspect_snapshot(capture(drift_ignores=[DriftIgnoreDirective('api', 'reason')]))
    bundle = store.save_bundle(original, tmp_path)
    payload = json.loads((bundle.path / 'snapshot.json').read_bytes())
    payload['drift_ignores'][0]['approval_verified'] = True
    raw = canonical_bytes(payload)
    (bundle.path / 'snapshot.json').write_bytes(raw)
    def edit(receipt):
        receipt['files']['snapshot.json'] = {'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)}
    path = reseal(bundle.path, receipt_edit=edit)
    with pytest.raises(BundleError, match='approval authority'):
        store.load_bundle(path)


@pytest.mark.parametrize('field,value', [('scan_metrics', []), ('summary', None), ('violations', {}),
                                        ('execution', []), ('skip', 'false')])
def test_resealed_malformed_results_are_input_errors(tmp_path, result, field, value):
    bundle = store.save_bundle(result, tmp_path)
    path = reseal(bundle.path, result_edit=lambda data: data.update({field: value}))
    with pytest.raises(BundleError):
        store.load_bundle(path)


def test_changed_producer_is_reported_without_claiming_pinned_engine(tmp_path, result, monkeypatch):
    bundle = store.save_bundle(result, tmp_path)
    identity = store.producer_identity()
    identity['source_sha256'] = '0' * 64
    monkeypatch.setattr(store, 'producer_identity', lambda: identity)
    comparison = bundle.replay().execution['bundle_replay']
    assert comparison['recorded_result_matches_current'] is True
    assert comparison['observed_producer_matches'] is False
    assert comparison['producer_authenticated'] is False


def test_substituted_input_snapshot_is_rejected_before_storage(tmp_path, result):
    result.input_snapshot = capture(contract_proofs=False)
    with pytest.raises(BundleError, match='bind'):
        store.save_bundle(result, tmp_path)
    assert not published(tmp_path)


def test_absent_unavailable_and_empty_observations_roundtrip(tmp_path):
    from drift_gate.core.models.changed_file import ChangedFile
    inputs = [ChangedFile('empty.md', 'unchanged', after_source=''),
              ChangedFile('missing.md', 'unchanged', document_input_state='missing'),
              ChangedFile('unavailable.md', 'unchanged', document_input_state='unavailable')]
    result = inspect_snapshot(capture(changed_files=inputs))
    loaded = store.save_bundle(result, tmp_path)
    assert loaded.snapshot == result.input_snapshot
    states = {a.state for a in loaded.snapshot.manifest.artifacts}
    assert {ArtifactState.PRESENT, ArtifactState.ABSENT, ArtifactState.UNAVAILABLE} <= states


@pytest.mark.parametrize('after_rename', [False, True])
def test_real_process_kill_distinguishes_unpublished_and_published(tmp_path, after_rename):
    # Kill after all bytes are staged but before the single publication step.
    script = tmp_path / 'crash.py'
    ready = tmp_path / 'ready'
    root = tmp_path / 'store'
    script.write_text('''import sys, time
from pathlib import Path
from drift_gate.tests.test_input_snapshot import capture
from drift_gate.adapters.inspection import inspect_snapshot
from drift_gate.adapters import evidence_bundle as store
original = store._publish_directory
def stop(pending, target):
    if sys.argv[3] == 'after':
        original(pending, target)
    Path(sys.argv[2]).write_text(str(target if sys.argv[3] == 'after' else pending))
    time.sleep(60)
store._publish_directory = stop
store.save_bundle(inspect_snapshot(capture()), sys.argv[1])
''', encoding='utf-8')
    process = subprocess.Popen([sys.executable, str(script), str(root), str(ready), 'after' if after_rename else 'before'])
    try:
        import time
        deadline = time.monotonic() + 15
        while not ready.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail('crash fixture exited before staging')
            time.sleep(.025)
        assert ready.exists()
        process.kill()
        process.wait(timeout=10)
        directory = Path(ready.read_text())
        assert (directory / store.COMMIT).exists()
        if after_rename:
            assert published(root) == [directory]
            assert store.load_bundle(directory).replay().execution['bundle_replay']['recorded_result_matches_current']
        else:
            assert not published(root)
            with pytest.raises(BundleError, match='SHA-256'):
                store.load_bundle(directory)
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=10)


def test_separate_processes_publish_same_receipt_without_overwrite(tmp_path):
    script = tmp_path / 'writer.py'
    script.write_text('''import sys
from pathlib import Path
from drift_gate.tests.test_input_snapshot import capture
from drift_gate.adapters.inspection import inspect_snapshot
from drift_gate.adapters.evidence_bundle import save_bundle
result = inspect_snapshot(capture(), execution={'schema_version': 2, 'run_id': '1'*32, 'started_at': 'fixed-fixture'})
result.scan_metrics.runtime_seconds = 0
bundle = save_bundle(result, sys.argv[1])
Path(sys.argv[2]).write_text(str(bundle.path), encoding='utf-8')
''', encoding='utf-8')
    root = tmp_path / 'store'
    processes = [subprocess.Popen([sys.executable, str(script), str(root), str(tmp_path / f'writer-{i}')]) for i in range(4)]
    try:
        assert [p.wait(timeout=20) for p in processes] == [0, 0, 0, 0]
        paths = {Path((tmp_path / f'writer-{i}').read_text(encoding='utf-8')) for i in range(4)}
        assert len(paths) == 1 and len(published(root)) == 1
        store.load_bundle(paths.pop())
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill(); process.wait(timeout=10)


def test_cli_persist_verify_and_replay_without_repository(git_repository, tmp_path, monkeypatch, capsys):
    root, base, head = git_repository
    from drift_gate.desktop.package_git_check import POLICY
    monkeypatch.chdir(root)
    with pytest.raises(SystemExit) as exit:
        run_cli(['check', '--base', base, '--head', head, '--trusted-policy-ref', base,
                 '--trusted-policy-sha256', sha256(POLICY.encode()).hexdigest(),
                 '--evidence-store', str(tmp_path / 'evidence'), '--contract-proofs', '--json'])
    assert exit.value.code == 1
    report = json.loads(capsys.readouterr().out)
    path = report['execution']['evidence_bundle']['path']
    monkeypatch.chdir(tmp_path)
    for command, expected in [('verify', 0), ('replay', 1)]:
        with pytest.raises(SystemExit) as exit:
            run_cli(['bundle', command, path, '--json'])
        assert exit.value.code == expected
        data = json.loads(capsys.readouterr().out)
        if command == 'replay':
            assert data['execution']['bundle_replay']['recorded_result_matches_current']
        else:
            assert data['semantic_truth_certified'] is False


def test_cli_corruption_and_changed_replay_exit_two(tmp_path, result, capsys):
    bundle = store.save_bundle(result, tmp_path)
    forged = reseal(bundle.path, result_edit=fake_pass)
    with pytest.raises(SystemExit) as exit:
        run_cli(['bundle', 'replay', str(forged), '--json'])
    assert exit.value.code == 2
    assert json.loads(capsys.readouterr().out)['execution']['bundle_replay']['recorded_result_matches_current'] is False
    (forged / store.COMMIT).unlink()
    with pytest.raises(SystemExit) as exit:
        run_cli(['bundle', 'verify', str(forged), '--json'])
    assert exit.value.code == 2
    assert json.loads(capsys.readouterr().out)['error']['code'] == 'input_error'


def test_private_file_permissions_on_posix(tmp_path, result):
    if os.name == 'nt':
        pytest.skip('POSIX mode bits are not Windows ACLs')
    bundle = store.save_bundle(result, tmp_path / 'private-store')
    assert bundle.path.stat().st_mode & 0o077 == 0
    assert (bundle.path / 'snapshot.json').stat().st_mode & 0o077 == 0


def test_windows_junction_is_not_a_private_object_directory(tmp_path, result):
    if os.name != 'nt':
        pytest.skip('Windows junction control')
    bundle = store.save_bundle(result, tmp_path / 'store')
    objects = bundle.path / 'objects'
    outside = tmp_path / 'outside-objects'
    objects.rename(outside)
    subprocess.check_call(['cmd', '/c', 'mklink', '/J', str(objects), str(outside)])
    with pytest.raises(BundleError, match='real directory'):
        store.load_bundle(bundle.path)
