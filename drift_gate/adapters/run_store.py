"""Local append-only run journals and target ledgers.

Each entry is created with a no-replace hard link from a fsynced private file,
so two writers can never both own one sequence number (local compare-and-set).
This is a single-host filesystem guarantee, not a distributed lock or a
provider-side compare-and-set. A deleted journal tail is not detectable
without an external anchor; gaps, reordering and edits in the middle are.
"""
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import re
import stat
import tempfile
import time

from drift_gate.adapters.bundle_codec import decode_json
from drift_gate.core.execution import latest as latest_core
from drift_gate.core.execution import lifecycle
from drift_gate.core.models.input_manifest import canonical_bytes

MAX_ENTRIES = 10_000
MAX_ENTRY_BYTES = 1_000_000
_NAME = re.compile('[0-9]{8}\\.json')
_ID = re.compile('[0-9a-f]{32}')


class RunStoreError(ValueError):
    """Unreadable, corrupt or contended run store."""


class Conflict(RunStoreError):
    """Another writer appended first; the caller must re-read and decide again."""


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _sync_directory(path):
    if os.name == 'nt':
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _real_directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(
            stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0):
        raise RunStoreError('Run store path must be a real directory')


def _ensure(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    _real_directory(path)
    return path


class Sequence:
    """Hash-chained append-only entries in one directory."""

    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        if not self.path.exists():
            return []
        _real_directory(self.path)
        names = sorted(n for n in os.listdir(self.path) if not n.startswith('.'))
        if len(names) > MAX_ENTRIES or any(not _NAME.fullmatch(n) for n in names):
            raise RunStoreError('Unexpected file or entry limit exceeded in run store')
        if names != [f'{i:08d}.json' for i in range(len(names))]:
            raise RunStoreError('Run store sequence has a gap')
        entries, previous = [], None
        for index, name in enumerate(names):
            target = self.path / name
            info = target.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_ENTRY_BYTES:
                raise RunStoreError('Run store entry must be a bounded regular file')
            raw = target.read_bytes()
            entry = decode_json(raw)
            if (not isinstance(entry, dict) or entry.get('sequence') != index
                    or entry.get('prev_sha256') != previous):
                raise RunStoreError('Run store hash chain or sequence mismatch')
            previous = sha256(raw).hexdigest()
            entries.append(entry)
        return entries

    def append(self, entry, *, expected_length):
        """Create entry ``expected_length`` only if no other writer did."""
        entries = self.read()
        if len(entries) != expected_length:
            raise Conflict('Run store changed since it was read')
        if expected_length >= MAX_ENTRIES:
            raise RunStoreError('Run store entry limit reached')
        previous = None
        if entries:
            previous = sha256((self.path / f'{expected_length - 1:08d}.json').read_bytes()).hexdigest()
        raw = canonical_bytes({**entry, 'sequence': expected_length, 'prev_sha256': previous})
        if len(raw) > MAX_ENTRY_BYTES:
            raise RunStoreError('Run store entry exceeds limit')
        _ensure(self.path)
        descriptor, temporary = tempfile.mkstemp(prefix='.entry-', dir=self.path)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, self.path / f'{expected_length:08d}.json')
            except FileExistsError as exc:
                raise Conflict('Another writer appended this sequence number') from exc
            _sync_directory(self.path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        return decode_json(raw)


class RunJournal:
    def __init__(self, root, run_id):
        if not isinstance(run_id, str) or not _ID.fullmatch(run_id):
            raise RunStoreError('Run ID must be 32 lowercase hex digits')
        self.root = Path(root).absolute()
        self.run_id = run_id
        self.path = self.root / 'runs' / run_id
        self.sequence = Sequence(self.path / 'journal')

    def events(self):
        return self.sequence.read()

    def view(self):
        events = self.events()
        if not events:
            return None
        try:
            view = lifecycle.fold(events)
        except lifecycle.LifecycleError as exc:
            raise RunStoreError(str(exc)) from exc
        if view.run_id != self.run_id:
            raise RunStoreError('Journal belongs to another run')
        return view

    def append(self, event, *, retries=3):
        """Append after re-deciding against the latest journal; returns Decision."""
        for _ in range(retries):
            events = self.events()
            try:
                view = lifecycle.fold(events) if events else None
            except lifecycle.LifecycleError as exc:
                raise RunStoreError(str(exc)) from exc
            full = {'run_id': self.run_id, 'recorded_at': utc_now(), **event}
            decision = lifecycle.decide(view, full)
            if not decision.accepted:
                return decision
            try:
                self.sequence.append(full, expected_length=len(events))
                return decision
            except Conflict:
                continue
        raise Conflict('Run journal remained contended')

    def heartbeat(self, owner):
        _ensure(self.path)
        raw = canonical_bytes({'owner': owner, 'at': time.time()})
        descriptor, temporary = tempfile.mkstemp(prefix='.heartbeat-', dir=self.path)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
        os.replace(temporary, self.path / 'heartbeat.json')

    def last_activity(self):
        times = []
        try:
            data = decode_json((self.path / 'heartbeat.json').read_bytes())
            if isinstance(data.get('at'), (int, float)):
                times.append(float(data['at']))
        except (OSError, ValueError):
            pass
        events = self.events()
        if events:
            times.append(datetime.fromisoformat(events[-1]['recorded_at']).timestamp())
        return max(times) if times else 0.0


def list_runs(root):
    runs = Path(root).absolute() / 'runs'
    if not runs.exists():
        return []
    _real_directory(runs)
    return sorted(n for n in os.listdir(runs) if _ID.fullmatch(n))


def recover(root, *, stale_after_seconds, now=None):
    """Close runs whose owner went silent; returns the transitions recorded."""
    if not isinstance(stale_after_seconds, (int, float)) or stale_after_seconds <= 0:
        raise RunStoreError('stale-after must be positive')
    now = time.time() if now is None else now
    recorded = []
    for run_id in list_runs(root):
        journal = RunJournal(root, run_id)
        view = journal.view()
        if view is None:
            continue
        event = lifecycle.recovery_event(view, now_seconds=now, last_activity_seconds=journal.last_activity(),
                                         stale_after_seconds=stale_after_seconds)
        if event is None:
            continue
        decision = journal.append(event)
        if decision.accepted:
            recorded.append({'run_id': run_id, 'from': view.state, 'to': decision.state})
    return recorded


class TargetLedger:
    """Latest pointer per target, fenced by generation and ticket."""

    def __init__(self, root, target):
        if not isinstance(target, str) or not target or len(target) > 256 or any(
                ord(c) < 32 for c in target):
            raise RunStoreError('Latest target must be 1-256 printable characters')
        self.target = target
        self.sequence = Sequence(Path(root).absolute() / 'targets' / sha256(target.encode('utf-8')).hexdigest()
                                 / 'ledger')

    def state(self):
        entries = self.sequence.read()
        if entries and any(e.get('target') != self.target for e in entries):
            raise RunStoreError('Ledger belongs to another target')
        try:
            return latest_core.fold(self.target, entries), len(entries)
        except latest_core.LedgerError as exc:
            raise RunStoreError(str(exc)) from exc

    def observe(self, *, head_oid, authority_sha256, run_id, retries=5):
        for _ in range(retries):
            state, length = self.state()
            entry, ticket, generation = latest_core.observe(state, head_oid=head_oid,
                                                            authority_sha256=authority_sha256)
            try:
                self.sequence.append({**entry, 'target': self.target, 'run_id': run_id,
                                      'recorded_at': utc_now()}, expected_length=length)
                return {'target': self.target, 'ticket': ticket, 'generation': generation,
                        'head_oid': head_oid, 'authority_sha256': authority_sha256}
            except Conflict:
                continue
        raise Conflict('Latest ledger remained contended')

    def publish(self, request, *, completed, retries=5):
        """Compare-and-set; re-decides on every conflict, never blind-writes."""
        for _ in range(retries):
            state, length = self.state()
            decision = latest_core.decide_publish(state, request, completed=completed)
            if not decision.accepted:
                return decision, state
            entry = latest_core.publish_entry(request)
            try:
                self.sequence.append({**entry, 'target': self.target, 'recorded_at': utc_now()},
                                     expected_length=length)
            except Conflict:
                continue
            return decision, self.state()[0]
        raise Conflict('Latest ledger remained contended')


def reconcile_latest(root, run_id):
    """Resolve publication-unknown for a local latest pointer by lookup only.

    Found -> published. Absent stays unknown: a recovered run's owner may still
    be alive, so absence is not proof that its write will never land.
    """
    journal = RunJournal(root, run_id)
    view = journal.view()
    if view is None:
        raise RunStoreError('unknown run')
    request = view.data.get('publication_request')
    if view.state != lifecycle.UNSETTLED_PUBLICATION or not isinstance(request, dict):
        return {'run_id': run_id, 'state': view.state, 'reason': 'not-an-unknown-local-publication'}
    try:
        state, _ = TargetLedger(root, request['target']).state()
    except (RunStoreError, OSError) as exc:
        return {'run_id': run_id, 'state': view.state, 'reason': f'lookup-failed: {exc}'}
    landed = (state.latest is not None and state.latest.run_id == run_id
              and state.latest.ticket == request.get('ticket'))
    if not landed:
        return {'run_id': run_id, 'state': view.state, 'reason': 'entry-not-found-kept-unknown'}
    decision = journal.append({'kind': 'state', 'state': 'published', 'controller': 'reconciler',
                               'data': {'publication': {'state': 'published', 'reason': 'ledger-entry-found'}}})
    if decision.accepted:
        journal.append({'kind': 'annotation', 'annotation': 'publication-reconciled',
                        'data': {'found': True}})
    return {'run_id': run_id, 'state': journal.view().state, 'reason': decision.reason}
