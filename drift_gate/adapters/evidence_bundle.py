"""Bounded immutable local bundles, published by one same-filesystem rename.

The selected store is private local storage, not an authenticated evidence
service. No latest pointer, automatic pruning or external publication is used.
"""
from dataclasses import dataclass
from hashlib import sha256
from importlib import metadata
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile

from drift_gate.adapters.bundle_codec import (
    BundleError, decode_json, decode_snapshot, encode_snapshot, object_path, semantic_result,
)
from drift_gate.core.models.input_manifest import canonical_bytes
from drift_gate.core.models.result import EvaluationResult


RECEIPT = 'receipt.json'
COMMIT = 'COMMITTED.json'
SCHEMA = 'inspection-bundle-receipt-v1'


@dataclass(frozen=True)
class BundleLimits:
    # The repository's full PR capture measured 125 MB total / 62 MB payload.
    # Keep explicit bounds with headroom; this is not a process-memory budget.
    max_total_bytes: int = 256_000_000
    max_file_bytes: int = 64_000_000
    max_files: int = 4096

    def __post_init__(self):
        if any(type(v) is not int or v <= 0 for v in (
            self.max_total_bytes, self.max_file_bytes, self.max_files)):
            raise BundleError('Bundle limits must be positive integers')

    def to_dict(self):
        return dict(max_total_bytes=self.max_total_bytes, max_file_bytes=self.max_file_bytes,
                    max_files=self.max_files)


def producer_identity():
    """Observed sources/versions only; no signature or loaded-code attestation."""
    package = Path(__file__).resolve().parents[1]
    sources = {}
    for part in ('core', 'adapters', 'utils'):
        for path in sorted((package / part).rglob('*.py')):
            sources[path.relative_to(package).as_posix()] = sha256(path.read_bytes()).hexdigest()
    versions = {}
    for name in ('drift-gate', 'PyYAML', 'tree-sitter', 'tree-sitter-language-pack'):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return {'schema': 'observed-producer-v1', 'source_sha256': sha256(canonical_bytes(sources)).hexdigest(),
            'source_files': len(sources), 'source_scope': 'available-core-adapters-utils-python-files',
            'python': sys.version, 'packages': versions, 'authenticated': False,
            'loaded_code_attested': False, 'parser_binary_attested': False}


def _safe_directory(path):
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or getattr(info, 'st_file_attributes', 0)
            & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)):
        raise BundleError('Evidence directory must be a real directory')


def _read_file(path, maximum):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or getattr(info, 'st_file_attributes', 0)
            & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)):
        raise BundleError('Evidence must be a regular file, not a link')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            raise BundleError('Evidence file exceeds limit or is not regular')
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    signature = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    if len(raw) > maximum or len(raw) != before.st_size or signature(before) != signature(after):
        raise BundleError('Evidence file changed while reading or exceeds limit')
    return raw


def _write_file(path, raw):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _sync_directory(path):
    if os.name == 'nt':
        return  # Windows Python cannot portably fsync a directory handle.
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_directory(pending, target):
    os.rename(pending, target)


def _commit(receipt_raw):
    return {'schema': 'inspection-bundle-commit-v1', 'receipt_sha256': sha256(receipt_raw).hexdigest()}


def _check_files(files, limits, *, reserved_files=0):
    if len(files) + reserved_files > limits.max_files or sum(map(len, files.values())) > limits.max_total_bytes:
        raise BundleError('Bundle exceeds total bytes or file count limit')
    if any(len(raw) > limits.max_file_bytes for raw in files.values()):
        raise BundleError('Bundle exceeds individual file limit')


def _validate_result(data, snapshot):
    if not isinstance(data, dict) or not isinstance(data.get('execution'), dict):
        raise BundleError('Result must be an inspection object')
    execution = data.get('execution', {})
    lists = ('change_types', 'violations', 'rule_decisions', 'skipped_rules', 'rejected_ignores',
             'ignore_audit', 'temporal_warnings')
    if (any(not isinstance(data.get(key), list) for key in lists)
            or any(not isinstance(data.get(key), dict) for key in ('summary', 'scan_metrics', 'gate'))
            or any(type(data.get(key)) is not bool for key in ('skip', 'no_policy'))
            or data.get('verification') not in {'verified', 'unverified', 'partial', 'not-applicable'}):
        raise BundleError('Malformed inspection result fields')
    summary = data['summary']
    if (data['gate'] != decode_json(snapshot.payload)['policy']['gate']
            or summary.get('gate_decision') != data['result']
            or any(not isinstance(v, dict) or v.get('severity') not in {'BLOCKER', 'MAJOR', 'MINOR', 'NIT'}
                   for v in data['violations'])):
        raise BundleError('Result policy, summary or violation binding mismatch')
    for severity in ('blocker', 'major', 'minor', 'nit'):
        if (type(summary.get(severity)) is not int or summary[severity] !=
                sum(v['severity'] == severity.upper() for v in data['violations'])):
            raise BundleError('Result summary contradicts violation counts')
    if (data.get('schema_version') != 3 or data.get('result') not in {'pass', 'warn', 'fail'}
            or execution.get('status') != 'success' or execution.get('input_capture') != snapshot.to_dict()
            or not isinstance(execution.get('run_id'), str)
            or not re.fullmatch('[0-9a-f]{32}', execution['run_id'])):
        raise BundleError('Result does not bind to a successful captured inspection')


def _names(path, maximum):
    names = set()
    with os.scandir(path) as entries:
        for entry in entries:
            names.add(entry.name)
            if len(names) > maximum:
                raise BundleError('Directory exceeds file count limit')
    return names


def _validate_producer(producer):
    expected = {'schema', 'source_sha256', 'source_files', 'source_scope', 'python', 'packages',
                'authenticated', 'loaded_code_attested', 'parser_binary_attested'}
    if (not isinstance(producer, dict) or set(producer) != expected
            or producer['schema'] != 'observed-producer-v1'
            or producer['source_scope'] != 'available-core-adapters-utils-python-files'
            or type(producer['source_files']) is not int or producer['source_files'] < 0
            or not isinstance(producer['python'], str) or not isinstance(producer['packages'], dict)
            or any(producer[k] is not False for k in (
                'authenticated', 'loaded_code_attested', 'parser_binary_attested'))):
        raise BundleError('Unsupported producer identity or authentication claim')
    object_path(producer['source_sha256'])


@dataclass(frozen=True)
class LoadedBundle:
    path: Path
    snapshot: object
    result_bytes: bytes
    receipt_bytes: bytes

    @property
    def receipt(self):
        return decode_json(self.receipt_bytes)

    @property
    def recorded_result(self):
        return decode_json(self.result_bytes)

    def to_dict(self):
        return {'schema': 'inspection-bundle-reference-v1', 'bundle_id': self.path.name,
                'path': str(self.path), 'receipt_sha256': sha256(self.receipt_bytes).hexdigest(),
                'integrity_verified': True, 'producer_authenticated': False,
                'retention': 'explicit-local-store-until-user-removal',
                'contains_raw_inputs': True, 'result_scope': 'base-inspection-before-history-and-enrichment'}

    def replay(self, *, execution=None):
        from drift_gate.adapters.inspection import inspect_snapshot
        current = inspect_snapshot(self.snapshot, execution=execution)
        comparison = {'schema': 'inspection-bundle-replay-v1',
            'receipt_sha256': sha256(self.receipt_bytes).hexdigest(),
            'recorded_result_matches_current': semantic_result(current.to_dict()) == semantic_result(self.recorded_result),
            'observed_producer_matches': producer_identity() == self.receipt['producer'],
            'replay_scope': 'captured-inputs-current-engine', 'producer_authenticated': False,
            'inspection_inputs_reread': False, 'producer_sources_observed': True,
            'current_policy_authorization_verified': False}
        current.execution['bundle_replay'] = comparison
        return current


def load_bundle(path, *, expected_receipt_sha256=None, limits=None):
    """Admit only a fully published bundle; no Git, policy or source rereads."""
    limits = limits or BundleLimits()
    path = Path(path).absolute()
    object_path(path.name)  # A pending directory is never a published identity.
    try:
        return _load_directory(path, path.name, expected_receipt_sha256=expected_receipt_sha256, limits=limits)
    except OSError as exc:
        raise BundleError('Incomplete or unreadable evidence bundle') from exc


def _load_directory(path, bundle_id, *, expected_receipt_sha256=None, limits):
    _safe_directory(path)
    _safe_directory(path / 'objects')
    marker = decode_json(_read_file(path / COMMIT, 1024))
    receipt_raw = _read_file(path / RECEIPT, min(limits.max_file_bytes, 1_000_000))
    actual_digest = sha256(receipt_raw).hexdigest()
    if (marker != _commit(receipt_raw) or actual_digest != bundle_id
            or expected_receipt_sha256 is not None and actual_digest != expected_receipt_sha256):
        raise BundleError('Bundle commit or externally pinned receipt mismatch')
    receipt = decode_json(receipt_raw)
    if not isinstance(receipt, dict) or receipt.get('schema') != SCHEMA or receipt.get('status') != 'completed':
        raise BundleError('Unsupported or incomplete receipt')
    entries = receipt.get('files')
    if not isinstance(entries, dict) or len(entries) + 2 > limits.max_files:
        raise BundleError('Invalid file inventory or file count limit')
    allowed = {'snapshot.json', 'manifest.json', 'git-input.json', 'result.json'}
    for name, entry in entries.items():
        if name not in allowed and not (name.startswith('objects/') and name == object_path(name[8:])):
            raise BundleError('Invalid evidence path')
        if (not isinstance(entry, dict) or set(entry) != {'sha256', 'bytes'}
                or type(entry['bytes']) is not int or not 0 <= entry['bytes'] <= limits.max_file_bytes):
            raise BundleError('Invalid evidence size declaration')
        object_path(entry['sha256'])
    total = sum(entry['bytes'] for entry in entries.values()) + len(receipt_raw) + len(canonical_bytes(marker))
    if total > limits.max_total_bytes:
        raise BundleError('Bundle exceeds total byte limit')
    expected_names = {name.split('/')[0] for name in entries} | {RECEIPT, COMMIT, 'objects'}
    if _names(path, limits.max_files) != expected_names:
        raise BundleError('Unexpected or missing bundle file')
    if _names(path / 'objects', limits.max_files) != {name[8:] for name in entries if name.startswith('objects/')}:
        raise BundleError('Unexpected or missing evidence object')
    files = {}
    for name, entry in entries.items():
        raw = _read_file(path / name, entry['bytes'])
        if len(raw) != entry['bytes'] or sha256(raw).hexdigest() != entry['sha256']:
            raise BundleError('Evidence size or checksum mismatch')
        files[name] = raw
    snapshot = decode_snapshot(files)
    try:
        data = decode_json(files['result.json'])
        _validate_result(data, snapshot)
        _validate_producer(receipt['producer'])
        if receipt != _receipt(snapshot, data, files, producer=receipt['producer'], limits=BundleLimits(**receipt['limits'])):
            raise BundleError('Receipt does not match admitted inputs and result')
    except (KeyError, TypeError) as exc:
        raise BundleError('Malformed result or receipt') from exc
    return LoadedBundle(path, snapshot, files['result.json'], receipt_raw)


def _receipt(snapshot, result, files, *, producer, limits):
    return {'schema': SCHEMA, 'status': 'completed', 'run_id': result['execution']['run_id'],
            'input_sha256': snapshot.manifest.input_sha256, 'manifest_sha256': snapshot.manifest.digest,
            'git_evidence_sha256': snapshot.git_evidence.digest if snapshot.git_evidence else None,
            'result_sha256': sha256(files['result.json']).hexdigest(),
            'files': {name: {'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)}
                      for name, raw in sorted(files.items())},
            'producer': producer, 'limits': limits.to_dict(),
            'authority': 'unsigned-local-receipt', 'producer_authenticated': False,
            'snapshot_binding_verified': True, 'semantic_truth_certified': False,
            'publication': 'same-filesystem-directory-rename',
            'durability': 'file-fsync-directory-fsync-on-posix',
            'replay_scope': 'captured-inputs-current-engine',
            'current_policy_authorization_verified': False}


def save_bundle(result, root, *, limits=None):
    """Persist one base inspection; duplicate content never replaces a bundle."""
    limits = limits or BundleLimits()
    if not isinstance(result, EvaluationResult) or result.input_snapshot is None:
        raise BundleError('A captured inspection result is required')
    snapshot = result.input_snapshot
    files = encode_snapshot(snapshot)
    # Projection validates retained IR; freeze a private copy before any I/O.
    data = decode_json(canonical_bytes(result.to_dict()))
    _validate_result(data, snapshot)
    if data['temporal_warnings'] or data.get('enrichment_metrics') is not None or 'evidence_bundle' in data['execution']:
        raise BundleError('Persist the base inspection before history, enrichment or receipt attachment')
    files['result.json'] = canonical_bytes(data)
    _check_files(files, limits, reserved_files=2)
    receipt_raw = canonical_bytes(_receipt(snapshot, data, files, producer=producer_identity(), limits=limits))
    marker_raw = canonical_bytes(_commit(receipt_raw))
    if len(receipt_raw) > min(limits.max_file_bytes, 1_000_000):
        raise BundleError('Receipt exceeds limit')
    _check_files({**files, RECEIPT: receipt_raw, COMMIT: marker_raw}, limits)
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    _safe_directory(root)
    parent = root / 'bundles'
    parent.mkdir(exist_ok=True, mode=0o700)
    _safe_directory(parent)
    target = parent / sha256(receipt_raw).hexdigest()
    if target.exists() or target.is_symlink():
        return load_bundle(target, expected_receipt_sha256=target.name, limits=limits)
    pending = Path(tempfile.mkdtemp(prefix='.pending-', dir=parent))
    try:
        (pending / 'objects').mkdir(mode=0o700)
        for name, raw in files.items():
            _write_file(pending / name, raw)
        _write_file(pending / RECEIPT, receipt_raw)
        _sync_directory(pending / 'objects')
        _write_file(pending / COMMIT, marker_raw)
        _sync_directory(pending)
        # Validate all persisted bytes before publication, without trusting
        # producer flags from disk. The final directory is still invisible.
        _load_directory(pending, target.name, expected_receipt_sha256=target.name, limits=limits)
        try:
            _publish_directory(pending, target)
        except OSError:
            if not target.exists():
                raise
            # Another process may have published this exact same receipt.
            load_bundle(target, expected_receipt_sha256=target.name, limits=limits)
        try:
            _sync_directory(parent)
            _sync_directory(root)
        except OSError as exc:
            raise BundleError(f'publication-unknown: bundle may exist at {target}; verify before retry') from exc
        return load_bundle(target, expected_receipt_sha256=target.name, limits=limits)
    finally:
        if pending.exists():
            # Cleanup failure must not turn a published result into a failure,
            # or mask the primary write error. Hidden staging remains private.
            shutil.rmtree(pending, ignore_errors=True)
