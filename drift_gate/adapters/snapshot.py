"""Seal supplied observations before analysis; replay never rereads the checkout.

This first S2 stage captures decoded adapter inputs in memory. It cannot attest
original Git/disk bytes, simultaneous collection, trusted policy, or freshness.
"""
from dataclasses import asdict, dataclass, field
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import stat

from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.evaluation_context import EvaluationContext
from drift_gate.core.models.input_manifest import (
    ArtifactState, InputManifest, SourceArtifact, canonical_bytes, relative_path,
)
from drift_gate.core.models.policy import Policy
from drift_gate.core.models.result import DriftIgnoreDirective
from drift_gate.core.models.git_input import GitInputEvidence
from drift_gate.core.policy.loader import load_policy_from_text


def read_bounded_text(path, *, max_bytes=1_000_000):
    """One bounded regular-file read, preserving newlines; observed-race guard.

    fstat comparison detects observed replacement/growth/in-place edits, not all
    ABA changes or atomicity across multiple files. Repository containment is
    checked by the caller; policy paths may intentionally be outside it.
    """
    path = Path(path)
    if type(max_bytes) is not int or max_bytes < 0:
        raise ValueError('byte limit must be a nonnegative integer')
    if path.is_symlink():
        raise ValueError('symlink inputs are unsupported')
    # O_NONBLOCK avoids waiting on an accidentally selected FIFO on POSIX.
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('input must be a regular file')
        content = stream.read(max_bytes + 1)
        after = os.fstat(stream.fileno())
    if len(content) > max_bytes:
        raise ValueError('input exceeds byte limit')
    current = path.stat()
    signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if signature(before) != signature(after) or signature(after) != signature(current):
        raise ValueError('snapshot_unstable: input changed during capture')
    return content.decode('utf-8')


def _validate_policy_binding(policy_data, source):
    if source is not None:
        parsed = asdict(load_policy_from_text(source))
        if {k: v for k, v in parsed.items() if k != 'load_warnings'} != {
            k: v for k, v in policy_data.items() if k != 'load_warnings'
        }:
            raise ValueError('policy source does not match evaluated policy')


def _artifacts(data):
    entries = []
    paths = set()
    for file in data['files']:
        path = relative_path(file['path'])
        if path in paths:
            raise ValueError('duplicate snapshot path')
        paths.add(path)
        status = file['status']
        if status not in {'added', 'modified', 'deleted', 'renamed', 'copied', 'unchanged'}:
            raise ValueError('unknown snapshot file status')
        previous = file['previous_path']
        if previous is not None:
            relative_path(previous)
        for role, key in [('patch', 'patch'), ('before-source', 'before_source'),
                          ('after-source', 'after_source'), ('document-json', 'document_json')]:
            text = file[key]
            observed_path = (previous or path) if role == 'before-source' else path
            state, reason = ArtifactState.NOT_COLLECTED, 'not_collected'
            if role == 'before-source' and status == 'added':
                state, reason = ArtifactState.ABSENT, 'adapter_declared_added'
            elif role == 'after-source' and status == 'deleted':
                state, reason = ArtifactState.ABSENT, 'adapter_declared_deleted'
            elif role == 'after-source' and file['document_input_state'] in {'missing', 'unavailable'}:
                state = ArtifactState.ABSENT if file['document_input_state'] == 'missing' else ArtifactState.UNAVAILABLE
                reason = 'adapter_declared_document_' + file['document_input_state']
            elif role == 'document-json' and file['document_input_state'] == 'unavailable':
                state, reason = ArtifactState.UNAVAILABLE, 'document_analysis_unavailable'
            elif role in {'patch', 'before-source', 'after-source'} and file['patch'].startswith('[large file skipped]'):
                state, reason = ArtifactState.LIMITED, 'patch_size_limit'
            elif role in {'patch', 'before-source', 'after-source'} and file['patch'].startswith('[binary file skipped]'):
                state, reason = ArtifactState.UNSUPPORTED, 'binary_not_analyzed'
            if text is not None:
                if not isinstance(text, str):
                    raise ValueError('snapshot text must be a string or None')
                # Legacy adapters use '' for the nonexistent added/deleted side.
                # The status supplies its meaning; it is not a present empty file.
                if text == '' and state == ArtifactState.ABSENT and (
                    (role == 'before-source' and status == 'added')
                    or (role == 'after-source' and status == 'deleted')
                ):
                    text = None
                if role != 'patch' and state == ArtifactState.ABSENT:
                    if text is not None:
                        raise ValueError('source contradicts declared absence/unavailability')
                # Raw text may have been read before YAML normalization failed.
                # Retain it as observed bytes; document semantics remain unavailable.
                # A skipped patch marker is a limit observation, not source text.
                if text is not None and (role != 'patch' or state not in {ArtifactState.LIMITED, ArtifactState.UNSUPPORTED}):
                    state, reason = ArtifactState.PRESENT, ''
            content = text.encode('utf-8') if state == ArtifactState.PRESENT else None
            entries.append(SourceArtifact(observed_path, role, state, reason, content))
    for role, value in [('policy-source', data['policy_source']),
                        ('policy-semantics', canonical_bytes(data['policy']).decode('ascii'))]:
        entries.append(SourceArtifact('@policy', role,
            ArtifactState.PRESENT if value is not None else ArtifactState.NOT_COLLECTED,
            '' if value is not None else 'not_collected',
            value.encode('utf-8') if value is not None else None))
    return tuple(sorted(entries, key=lambda a: a.identity))


@dataclass(frozen=True)
class InspectionSnapshot:
    manifest: InputManifest
    payload: bytes = field(repr=False)
    git_evidence: GitInputEvidence | None = field(default=None, repr=False)

    def __post_init__(self):
        if type(self.payload) is not bytes or not isinstance(self.manifest, InputManifest):
            raise ValueError('snapshot requires immutable payload and typed manifest')
        data = json.loads(self.payload)
        if canonical_bytes(data) != self.payload or data['schema'] != 'inspection-snapshot-v1':
            raise ValueError('noncanonical or unsupported snapshot')
        _validate_policy_binding(data['policy'], data['policy_source'])
        if self.git_evidence is not None:
            if not isinstance(self.git_evidence, GitInputEvidence) or data.get('git_evidence_sha256') != self.git_evidence.digest:
                raise ValueError('Git evidence/capsule mismatch')
            self.git_evidence.bind_observations(data)
        elif 'git_evidence_sha256' in data:
            raise ValueError('Git evidence is missing')
        if (sha256(self.payload).hexdigest() != self.manifest.input_sha256
            or _artifacts(data) != self.manifest.artifacts
            or data['collection_mode'] != self.manifest.collection_mode):
            raise ValueError('snapshot manifest/payload mismatch')

    def materialize(self):
        """Private copies for one attempt. No mutable object escapes the capsule."""
        data = json.loads(self.payload)
        policy = Policy.from_dict(data['policy'])
        policy.load_warnings = data['policy']['load_warnings']
        files = []
        for file in data['files']:
            for key in ('before_routes', 'after_routes'):
                if file[key] is not None:
                    file[key] = [tuple(route) for route in file[key]]
            files.append(ChangedFile(**file))
        return {
            'changed_files': files,
            'policy': policy,
            'drift_ignores': [DriftIgnoreDirective(**d) for d in data['drift_ignores']],
            'context': EvaluationContext(date.fromisoformat(data['context']['evaluated_on'])),
            'policy_source': data['policy_source'], 'policy_path': data['policy_path'],
            'provenance': data['provenance'], 'contract_proofs': data['contract_proofs'],
        }

    def to_dict(self):
        """Public hashes/states only; raw text and ignore reasons remain private."""
        return {**self.manifest.to_dict(), 'manifest_sha256': self.manifest.digest,
                'retention': 'process-memory-only', 'replay_scope': 'captured-inputs-current-engine',
                **({'git_input': {**self.git_evidence.to_dict(), 'manifest_sha256': self.git_evidence.digest}}
                   if self.git_evidence is not None else {})}


def capture_inspection(*, changed_files, policy, context, drift_ignores=None,
                       policy_source=None, policy_path=None, provenance=None,
                       contract_proofs=False, git_evidence=None):
    if type(contract_proofs) is not bool:
        raise ValueError('contract_proofs must be a boolean')
    policy_data = asdict(policy)
    # A caller cannot bind policy A's source hash to policy B's semantics.
    _validate_policy_binding(policy_data, policy_source)
    provenance = provenance or {}
    mode = 'captured-working-tree' if provenance.get('source') == 'local-git' else 'captured-adapter-input'
    payload = canonical_bytes({
        'schema': 'inspection-snapshot-v1', 'collection_mode': mode,
        'files': [asdict(file) for file in changed_files], 'policy': policy_data,
        'drift_ignores': [asdict(d) for d in drift_ignores or []],
        'context': context.to_dict(), 'policy_source': policy_source,
        'policy_path': str(Path(policy_path).resolve()) if policy_path is not None else None,
        'provenance': provenance, 'contract_proofs': contract_proofs,
        **({'git_evidence_sha256': git_evidence.digest} if git_evidence is not None else {}),
    })
    data = json.loads(payload)
    manifest = InputManifest(_artifacts(data), sha256(payload).hexdigest(), mode)
    return InspectionSnapshot(manifest, payload, git_evidence)
