"""Pure immutable observations. Digests bind inputs, never authenticate them."""
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
from pathlib import PurePosixPath


DIGEST_PROTOCOL = 'python-json-observation-v1'


def canonical_bytes(value) -> bytes:
    """Python producer protocol: no Unicode normalization, preserve array order.

    ASCII JSON escapes preserve code points, including supplementary characters.
    This is not a claim of RFC 8785 or cross-language canonical JSON conformance.
    """
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      allow_nan=False, separators=(',', ':')).encode('ascii')


def relative_path(path: str) -> str:
    if (not isinstance(path, str) or not path or '\x00' in path
        or path.startswith('/') or (len(path) > 1 and path[1] == ':')
        or '\\' in path or any(0xD800 <= ord(c) <= 0xDFFF for c in path)
        or '..' in PurePosixPath(path).parts or str(PurePosixPath(path)) != path):
        raise ValueError('snapshot requires an exact UTF-8 relative repository path')
    return path


class ArtifactState(str, Enum):
    PRESENT = 'present'
    ABSENT = 'absent'
    UNAVAILABLE = 'unavailable'
    NOT_COLLECTED = 'not-collected'
    LIMITED = 'limited'
    UNSUPPORTED = 'unsupported'


@dataclass(frozen=True)
class SourceArtifact:
    path: str
    role: str
    state: ArtifactState
    reason: str = ''
    # Bytes encode the supplied text, not necessarily the original disk/blob.
    content: bytes | None = field(default=None, repr=False)

    def __post_init__(self):
        relative_path(self.path)
        if self.role not in {'patch', 'before-source', 'after-source',
                             'document-json', 'policy-source', 'policy-semantics'}:
            raise ValueError('unknown artifact role')
        if not isinstance(self.state, ArtifactState) or not isinstance(self.reason, str):
            raise ValueError('invalid artifact state or reason')
        if self.state == ArtifactState.PRESENT:
            if type(self.content) is not bytes or self.reason:
                raise ValueError('present requires immutable bytes and no absence reason')
        elif self.content is not None or not self.reason:
            raise ValueError('non-present requires a reason and no content')

    @property
    def identity(self):
        return self.path, self.role

    def to_dict(self):
        return {'path': self.path, 'role': self.role, 'state': self.state.value,
                'reason': self.reason,
                'observed_text_sha256': sha256(self.content).hexdigest() if self.content is not None else None,
                'observed_text_bytes': len(self.content) if self.content is not None else None,
                'encoding': 'utf-8-observed-text' if self.content is not None else None}


@dataclass(frozen=True)
class InputManifest:
    artifacts: tuple[SourceArtifact, ...]
    input_sha256: str
    collection_mode: str

    def __post_init__(self):
        if type(self.artifacts) is not tuple or any(not isinstance(a, SourceArtifact) for a in self.artifacts):
            raise ValueError('manifest requires immutable artifacts')
        identities = tuple(a.identity for a in self.artifacts)
        if identities != tuple(sorted(set(identities))):
            raise ValueError('manifest entries must be unique and sorted')
        if (not isinstance(self.input_sha256, str) or len(self.input_sha256) != 64
            or any(c not in '0123456789abcdef' for c in self.input_sha256)):
            raise ValueError('invalid input digest')
        if self.collection_mode not in {'captured-working-tree', 'captured-adapter-input'}:
            raise ValueError('unknown collection mode')

    def to_dict(self):
        return {'schema': 'input-manifest-v1', 'digest_protocol': DIGEST_PROTOCOL,
                'input_sha256': self.input_sha256,
                'collection_mode': self.collection_mode,
                'atomicity': 'per-artifact-observation',
                'original_bytes_certified': False, 'revision_certified': False,
                'policy_authority': 'unverified-caller-input',
                'selection_complete': False,
                'artifacts': [a.to_dict() for a in self.artifacts]}

    @property
    def digest(self):
        return sha256(canonical_bytes(self.to_dict())).hexdigest()
