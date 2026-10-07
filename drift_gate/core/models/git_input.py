"""Git object integrity and caller-selected policy anchors; no I/O or approval claims."""
from dataclasses import dataclass, field
from hashlib import sha1, sha256

from .input_manifest import ArtifactState, canonical_bytes, relative_path


def require_oid(value):
    if not isinstance(value, str) or len(value) not in {40, 64} or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('expected a full Git object ID')
    return value


def object_oid(kind, content, length):
    body = f'{kind} {len(content)}\0'.encode('ascii') + content
    return (sha1(body) if length == 40 else sha256(body)).hexdigest()


@dataclass(frozen=True)
class GitArtifact:
    revision: str
    path: str
    object_id: str | None
    kind: str
    mode: str
    state: ArtifactState
    reason: str = ''
    content: bytes | None = field(default=None, repr=False)

    def __post_init__(self):
        require_oid(self.revision)
        relative_path(self.path)
        if self.object_id is not None:
            require_oid(self.object_id)
        if not isinstance(self.state, ArtifactState):
            raise ValueError('invalid Git artifact state')
        if self.state == ArtifactState.PRESENT:
            if (type(self.content) is not bytes or self.kind not in {'blob', 'tree'}
                or self.object_id is None or self.reason
                or object_oid(self.kind, self.content, len(self.object_id)) != self.object_id):
                raise ValueError('Git object content/identity mismatch')
        elif self.content is not None or not self.reason:
            raise ValueError('non-present Git artifact requires a reason and no bytes')
        if self.state == ArtifactState.ABSENT and self.object_id is not None:
            raise ValueError('absent Git path cannot have an object ID')

    @property
    def identity(self):
        return self.revision, self.path

    def to_dict(self):
        return {'revision': self.revision, 'path': self.path, 'object_id': self.object_id,
                'kind': self.kind, 'mode': self.mode, 'state': self.state.value, 'reason': self.reason,
                'raw_sha256': sha256(self.content).hexdigest() if self.content is not None else None,
                'raw_bytes': len(self.content) if self.content is not None else None}


@dataclass(frozen=True)
class GitSubject:
    base_oid: str
    head_oid: str
    base_tree: str
    head_tree: str
    comparison_mode: str

    def __post_init__(self):
        for value in (self.base_oid, self.head_oid, self.base_tree, self.head_tree):
            require_oid(value)
        if self.comparison_mode not in {'commit', 'merge-base'}:
            raise ValueError('unsupported Git comparison mode')

    def to_dict(self):
        return {'base_oid': self.base_oid, 'head_oid': self.head_oid,
                'base_tree': self.base_tree, 'head_tree': self.head_tree,
                'comparison_mode': self.comparison_mode, 'collection_mode': 'immutable-git',
                'working_tree_ignored': True, 'unsaved_buffers_included': False,
                'untracked_included': False}


@dataclass(frozen=True)
class GitInputEvidence:
    subject: GitSubject
    artifacts: tuple[GitArtifact, ...]
    trusted_revision: str
    policy_path: str
    expected_policy_sha256: str
    catalog_sha256: str

    def __post_init__(self):
        if not isinstance(self.subject, GitSubject) or type(self.artifacts) is not tuple:
            raise ValueError('typed immutable Git subject/artifacts required')
        require_oid(self.trusted_revision)
        relative_path(self.policy_path)
        if any(not isinstance(a, GitArtifact) for a in self.artifacts):
            raise ValueError('invalid Git artifact')
        identities = tuple(a.identity for a in self.artifacts)
        if identities != tuple(sorted(set(identities))):
            raise ValueError('Git artifacts must be unique and sorted')
        for value in (self.expected_policy_sha256, self.catalog_sha256):
            if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                raise ValueError('expected a SHA-256 digest')
        anchor = self.get(self.trusted_revision, self.policy_path)
        if (anchor.state != ArtifactState.PRESENT or anchor.mode not in {'100644', '100755'}
            or sha256(anchor.content).hexdigest() != self.expected_policy_sha256):
            raise ValueError('trusted policy does not match caller pin')
        for revision, tree in ((self.subject.base_oid, self.subject.base_tree),
                               (self.subject.head_oid, self.subject.head_tree)):
            witness = self.get(revision, '@tree/' + tree)
            if witness.state != ArtifactState.PRESENT or witness.kind != 'tree' or witness.object_id != tree:
                raise ValueError('missing subject tree witness')

    def get(self, revision, path):
        for artifact in self.artifacts:
            if artifact.identity == (revision, path):
                return artifact
        raise ValueError('artifact not captured for this revision/path')

    def bind_observations(self, data):
        """Tie source text and evaluated policy to the retained original bytes."""
        anchor = self.get(self.trusted_revision, self.policy_path)
        if data['policy_source'].encode('utf-8') != anchor.content:
            raise ValueError('evaluated policy is not the pinned Git policy')
        for file in data['files']:
            for key, revision, path in (
                ('before_source', self.subject.base_oid, file['previous_path'] or file['path']),
                ('after_source', self.subject.head_oid, file['path']),
            ):
                text = file[key]
                if text is not None:
                    raw = self.get(revision, path)
                    if raw.mode not in {'100644', '100755'} or text.encode('utf-8') != raw.content:
                        raise ValueError('observed source is not the captured Git blob')

    def to_dict(self):
        return {'schema': 'git-input-evidence-v1', 'subject': self.subject.to_dict(),
                'catalog_sha256': self.catalog_sha256,
                'policy_anchor': {'revision': self.trusted_revision, 'path': self.policy_path,
                    'sha256': self.expected_policy_sha256, 'integrity_verified': True,
                    'authority': 'explicit-caller-pin', 'organization_approval_verified': False,
                    'evaluation_policy': 'pinned-policy', 'candidate_weakening': 'rejected'},
                'checker_authority': 'current-engine-not-attested',
                'selection_scope': 'changed-paths-and-configured-document-observations',
                'artifacts': [a.to_dict() for a in self.artifacts]}

    @property
    def digest(self):
        return sha256(canonical_bytes(self.to_dict())).hexdigest()
