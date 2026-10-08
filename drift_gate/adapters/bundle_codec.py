"""Versioned evidence encoding; integrity is not producer authentication."""
from copy import deepcopy
from hashlib import sha256
import json

from drift_gate.adapters.snapshot import InspectionSnapshot
from drift_gate.core.models.git_input import GitArtifact, GitInputEvidence, GitSubject
from drift_gate.core.models.input_manifest import ArtifactState, canonical_bytes
from drift_gate.core.policy.loader import PolicyLoadError


class BundleError(ValueError):
    """Incomplete, unsupported or inconsistent persisted evidence."""


def decode_json(raw):
    try:
        data = json.loads(raw)
        if canonical_bytes(data) != raw:
            raise ValueError('noncanonical JSON')
        return data
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        raise BundleError('Invalid or noncanonical evidence JSON') from exc


def object_path(raw_digest):
    if (not isinstance(raw_digest, str) or len(raw_digest) != 64
            or any(c not in '0123456789abcdef' for c in raw_digest)):
        raise BundleError('Invalid evidence SHA-256')
    return 'objects/' + raw_digest


def encode_snapshot(snapshot):
    InspectionSnapshot(snapshot.manifest, snapshot.payload, snapshot.git_evidence)
    require_replayable(snapshot)
    files = {'snapshot.json': snapshot.payload,
             'manifest.json': canonical_bytes(snapshot.manifest.to_dict())}
    artifacts = list(snapshot.manifest.artifacts)
    if snapshot.git_evidence is not None:
        files['git-input.json'] = canonical_bytes(snapshot.git_evidence.to_dict())
        artifacts.extend(snapshot.git_evidence.artifacts)
    for artifact in artifacts:
        if artifact.content is not None:
            files[object_path(sha256(artifact.content).hexdigest())] = artifact.content
    return files


def require_replayable(snapshot):
    # An unsigned disk file must never resurrect an adapter-verified waiver.
    # Approval envelopes/authority revalidation are a separate future protocol.
    data = decode_json(snapshot.payload)
    if any(d.get('approval_verified') for d in data['drift_ignores']):
        raise BundleError('Persisted approval authority is unsupported; verified waivers require revalidation')


def decode_snapshot(files):
    try:
        evidence = None
        if 'git-input.json' in files:
            meta = decode_json(files['git-input.json'])
            subject = meta['subject']
            anchor = meta['policy_anchor']
            artifacts = []
            for entry in meta['artifacts']:
                content = None
                if entry['state'] == ArtifactState.PRESENT.value:
                    content = files[object_path(entry['raw_sha256'])]
                artifacts.append(GitArtifact(entry['revision'], entry['path'], entry['object_id'],
                    entry['kind'], entry['mode'], ArtifactState(entry['state']), entry['reason'], content))
            evidence = GitInputEvidence(GitSubject(subject['base_oid'], subject['head_oid'],
                subject['base_tree'], subject['head_tree'], subject['comparison_mode']), tuple(artifacts),
                anchor['revision'], anchor['path'], anchor['sha256'], meta['catalog_sha256'])
            if evidence.to_dict() != meta:
                raise BundleError('Git evidence metadata differs from reconstructed objects')
        snapshot = InspectionSnapshot.from_payload(files['snapshot.json'], git_evidence=evidence)
        require_replayable(snapshot)
        # Re-encoding checks every observation, raw object and declared state,
        # including extra/missing objects and altered absence/authority fields.
        if encode_snapshot(snapshot) != {k: v for k, v in files.items() if k != 'result.json'}:
            raise BundleError('Stored observations or objects differ from snapshot')
        snapshot.materialize()  # Validate types before admitting a replay input.
        return snapshot
    except (KeyError, TypeError, ValueError, RecursionError, PolicyLoadError) as exc:
        if isinstance(exc, BundleError):
            raise
        raise BundleError('Malformed or inconsistent inspection snapshot') from exc


def semantic_result(data):
    """Compare full policy/proof output, excluding attempt identity and timing."""
    value = deepcopy(data)
    value.pop('execution', None)
    value.get('scan_metrics', {}).pop('runtime_seconds', None)
    return value
