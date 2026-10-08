"""Persistent analysis cache (design W15 follow-up, 8.3).

The key binds every input that can change an analysis result: the artifact's
raw digest, the analyzer operation and profile version, the producing engine's
source digest, the reviewed parser pins, the approval context and the resource
limits. Only complete results and deterministic "unsupported" refusals are
stored. Timeouts, crashes, resource limits and other transient failures are
never cached, so a passing retry is never shadowed by an old failure. Entries
are content-addressed, written once with a no-replace link, and re-verified on
read (the stored key inputs must hash to the entry name). A tampered or
truncated entry is a miss, not a hit.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile

from drift_gate.core.models.input_manifest import canonical_bytes

SCHEMA = 'analysis-cache-entry-v1'
STORABLE = ('complete', 'unsupported')


class CacheError(ValueError):
    """Unusable cache configuration (never raised for a bad entry: that is a miss)."""


def engine_digest():
    from drift_gate.adapters.evidence_bundle import producer_identity
    return producer_identity()['source_sha256']


def parser_pins_digest():
    path = Path(__file__).with_name('parser_hashes.json')
    return sha256(path.read_bytes()).hexdigest()


def key_inputs(*, artifact_sha256, op, profile, engine_sha256, parser_sha256, approvals_sha256='none',
               limits=None, scope_context='module'):
    for name, value in (('artifact_sha256', artifact_sha256), ('engine_sha256', engine_sha256),
                        ('parser_sha256', parser_sha256)):
        if not isinstance(value, str) or len(value) != 64:
            raise CacheError(f'{name} must be a SHA-256 digest')
    return {'schema': 'analysis-cache-key-v1', 'artifact_sha256': artifact_sha256, 'op': op,
            'profile': list(profile), 'engine_sha256': engine_sha256, 'parser_sha256': parser_sha256,
            'approvals_sha256': approvals_sha256, 'limits': limits or {}, 'scope_context': scope_context}


def cache_key(inputs):
    return sha256(canonical_bytes(inputs)).hexdigest()


class AnalysisCache:
    def __init__(self, root):
        self.root = Path(root).absolute()
        self.hits = self.misses = self.rejected = self.stored = self.skipped = 0

    def _path(self, key):
        return self.root / 'entries' / key[:2] / f'{key}.json'

    @staticmethod
    def _valid(path, inputs, key):
        try:
            raw = path.read_bytes()
            entry = json.loads(raw)
        except (OSError, ValueError):
            return False
        return (isinstance(entry, dict) and entry.get('schema') == SCHEMA and canonical_bytes(entry) == raw
                and entry.get('key_inputs') == inputs and cache_key(entry['key_inputs']) == key
                and entry.get('status') in STORABLE)

    def get(self, inputs):
        key = cache_key(inputs)
        path = self._path(key)
        try:
            raw = path.read_bytes()
            entry = json.loads(raw)
            valid = (isinstance(entry, dict) and entry.get('schema') == SCHEMA and canonical_bytes(entry) == raw
                     and entry.get('key_inputs') == inputs and cache_key(entry['key_inputs']) == key
                     and entry.get('status') in STORABLE)
        except (OSError, ValueError):
            valid = False if path.exists() else None
        if valid is None:
            self.misses += 1
            return None
        if not valid:
            self.rejected += 1  # tampered/truncated/foreign entry: recompute, never trust
            return None
        self.hits += 1
        return entry

    def put(self, inputs, *, status, value):
        """Store a complete or deterministic-unsupported result; return False when not storable."""
        if status not in STORABLE:
            self.skipped += 1
            return False
        key = cache_key(inputs)
        entry = {'schema': SCHEMA, 'key_inputs': inputs, 'status': status, 'value': value}
        raw = canonical_bytes(entry)
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(prefix='.entry-', dir=target.parent)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
                self.stored += 1
            except FileExistsError:
                if not self._valid(target, inputs, key):
                    os.replace(temporary, target)  # repair a tampered/truncated entry atomically
                    self.stored += 1
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        return True

    def stats(self):
        return {'hits': self.hits, 'misses': self.misses, 'rejected_entries': self.rejected,
                'stored': self.stored, 'not_stored_transient_or_incomplete': self.skipped,
                'root': str(self.root)}
