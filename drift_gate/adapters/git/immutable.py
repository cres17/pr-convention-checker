"""Collect exact immutable Git objects without working-tree or replacement refs."""
from datetime import datetime, timezone
from contextlib import contextmanager
from hashlib import sha256
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from drift_gate.adapters.docs.content import attach_env_documents
from drift_gate.adapters.git.client import GitInputError, _parse_name_status
from drift_gate.adapters.policy_loader import require_check_policy
from drift_gate.adapters.snapshot import capture_inspection
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.evaluation_context import EvaluationContext
from drift_gate.core.models.git_input import GitArtifact, GitInputEvidence, GitSubject, require_oid
from drift_gate.core.models.input_manifest import ArtifactState, canonical_bytes, relative_path
from drift_gate.core.policy.guard import weakening_reasons
from drift_gate.core.policy.loader import load_policy_from_text


MAX_OBJECT_BYTES = 1_000_000
MAX_TREE_ENTRIES = 20_000
MAX_PATCH_BYTES = 256_000


def _git_environment():
    # Git's caller environment can redirect repositories, attribute sources and
    # config. None of those are inputs to an immutable-object collection.
    return {**{key: value for key, value in os.environ.items() if not key.startswith('GIT_')},
            'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_SYSTEM': os.devnull,
            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_ATTR_NOSYSTEM': '1',
            'GIT_TERMINAL_PROMPT': '0', 'GIT_NO_LAZY_FETCH': '1', 'LC_ALL': 'C'}


def _git(root, args, *, env=None):
    try:
        return subprocess.check_output(['git', '--no-replace-objects', '--literal-pathspecs', *args],
            cwd=root, env=_git_environment() if env is None else env,
            stderr=subprocess.PIPE, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitInputError('Could not read immutable Git objects') from exc


@contextmanager
def _raw_diff(root, object_format):
    """Read objects through a private bare repository with no caller attributes.

    Even a commit-to-commit diff consults working/index/info attributes. Sharing
    only the object directory avoids those inputs and local diff-driver config.
    The source repository's index, config and object store are never written.
    """
    objects = Path(_git(root, ['rev-parse', '--git-path', 'objects']).decode('utf-8').strip())
    if not objects.is_absolute():
        objects = Path(root) / objects
    with TemporaryDirectory(prefix='driftgate-raw-diff-') as directory:
        env = _git_environment()
        _git(directory, ['init', '--bare', '--template=', '--object-format=' + object_format], env=env)
        env['GIT_OBJECT_DIRECTORY'] = str(objects.resolve())
        yield lambda arguments: _git(directory,
            ['diff', '--no-ext-diff', '--no-textconv', '--find-renames', *arguments], env=env)


def _resolve(root, ref):
    if not isinstance(ref, str) or not ref or ref.startswith('-'):
        raise GitInputError('Invalid Git ref')
    return require_oid(_git(root, ['rev-parse', '--verify', '--end-of-options', ref + '^{commit}']).decode('ascii').strip())


class GitObjectReader:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.catalogs, self.records, self.tree_ids = {}, {}, {}

    def catalog(self, revision):
        if revision in self.catalogs:
            return self.catalogs[revision]
        tree = require_oid(_git(self.root, ['rev-parse', revision + '^{tree}']).decode('ascii').strip())
        self.tree_ids[revision] = tree
        raw = _git(self.root, ['ls-tree', '-r', '-t', '-z', '--full-tree', tree])
        if len(raw) > 5_000_000:
            raise GitInputError('Git catalog exceeds resource limit')
        fields = raw.split(b'\0')
        if fields.pop() != b'' or len(fields) > MAX_TREE_ENTRIES:
            raise GitInputError('Git catalog is incomplete or exceeds entry limit')
        catalog, trees = {}, {tree}
        for field in fields:
            try:
                metadata, path_bytes = field.split(b'\t', 1)
                mode, kind, oid = metadata.decode('ascii').split(' ')
                path = relative_path(path_bytes.decode('utf-8', errors='strict'))
                if path.startswith('@tree/'):
                    raise ValueError('reserved tree witness namespace')
                require_oid(oid)
                if path in catalog:
                    raise ValueError('duplicate tree path')
            except (ValueError, UnicodeError) as exc:
                raise GitInputError('Unsupported Git path/catalog encoding') from exc
            if kind == 'tree':
                trees.add(oid)
            else:
                catalog[path] = (mode, kind, oid)
        # Verify root and visited subtree bytes, not just the requested ref name.
        for oid in sorted(trees):
            content = self._object('tree', oid)
            self.records[revision, '@tree/' + oid] = GitArtifact(revision, '@tree/' + oid,
                oid, 'tree', '040000', ArtifactState.PRESENT, content=content)
        self.catalogs[revision] = catalog
        return catalog

    def _object(self, kind, oid):
        size = int(_git(self.root, ['cat-file', '-s', oid]))
        if size > MAX_OBJECT_BYTES:
            raise GitInputError('Git object exceeds 1 MB capture limit')
        content = _git(self.root, ['cat-file', kind, oid])
        if len(content) != size:
            raise GitInputError('Incomplete Git object read')
        return content

    def read(self, revision, path):
        relative_path(path)
        if (revision, path) not in self.records:
            entry = self.catalog(revision).get(path)
            if entry is None:
                item = GitArtifact(revision, path, None, 'absent', '', ArtifactState.ABSENT,
                                   'absent_in_pinned_tree')
            else:
                mode, kind, oid = entry
                if kind != 'blob':
                    item = GitArtifact(revision, path, oid, kind, mode, ArtifactState.UNSUPPORTED,
                                       'gitlink_not_followed')
                else:
                    item = GitArtifact(revision, path, oid, kind, mode, ArtifactState.PRESENT,
                                       content=self._object(kind, oid))
            self.records[revision, path] = item
        return self.records[revision, path]

    def text(self, revision, path):
        item = self.read(revision, path)
        if item.state == ArtifactState.ABSENT:
            return None
        if item.mode not in {'100644', '100755'} or item.state != ArtifactState.PRESENT:
            raise ValueError('symlink/submodule text inputs are unsupported')
        return item.content.decode('utf-8', errors='strict')


def collect_git_snapshot(*, root, base, head, trusted_policy_ref, trusted_policy_sha256,
                         policy_path='.drift-gate.yml', comparison_mode='commit',
                         context=None, contract_proofs=False):
    relative_path(policy_path)
    reader = GitObjectReader(root)
    base_oid, head_oid, trusted_oid = (_resolve(reader.root, ref) for ref in (base, head, trusted_policy_ref))
    if comparison_mode == 'merge-base':
        candidates = _git(reader.root, ['merge-base', '--all', base_oid, head_oid]).decode('ascii').split()
        if len(candidates) != 1:
            raise GitInputError('Merge-base is ambiguous; choose an explicit base OID')
        base_oid = require_oid(candidates[0])
    elif comparison_mode != 'commit':
        raise GitInputError('Unknown comparison mode')
    for revision in (base_oid, head_oid, trusted_oid):
        reader.catalog(revision)
    trusted_source = reader.text(trusted_oid, policy_path)
    candidate_source = reader.text(head_oid, policy_path)
    if trusted_source is None or candidate_source is None:
        raise GitInputError('Pinned or candidate policy is absent')
    if sha256(trusted_source.encode('utf-8')).hexdigest() != trusted_policy_sha256:
        raise GitInputError('Trusted policy SHA-256 does not match explicit caller pin')
    trusted, candidate = load_policy_from_text(trusted_source), load_policy_from_text(candidate_source)
    require_check_policy(trusted); require_check_policy(candidate)
    reasons = weakening_reasons(trusted, candidate)
    if reasons:
        raise GitInputError('Candidate weakened pinned policy: ' + '; '.join(reasons))
    files = []
    with _raw_diff(reader.root, 'sha1' if len(head_oid) == 40 else 'sha256') as diff:
        changed = _parse_name_status(diff(['--name-status', '-z', base_oid, head_oid, '--']))
        for file in changed:
            old_path = file.previous_path or file.path
            before = reader.read(base_oid, old_path)
            after = reader.read(head_oid, file.path)
            paths = [old_path, file.path] if old_path != file.path else [file.path]
            patch_bytes = diff([base_oid, head_oid, '--', *paths])
            patch = patch_bytes.decode('utf-8', errors='strict') if len(patch_bytes) <= MAX_PATCH_BYTES else '[large file skipped]'
            binary_diff = any(line.startswith(b'Binary files ') and line.endswith(b' differ')
                              for line in patch_bytes.splitlines())
            if binary_diff or any(item.mode not in {'', '100644', '100755'} for item in (before, after)):
                patch = '[binary file skipped]'
                before_text = after_text = None
            else:
                before_text = reader.text(base_oid, old_path)
                after_text = reader.text(head_oid, file.path)
            files.append(ChangedFile(file.path, file.status, previous_path=file.previous_path,
                patch=patch, before_source=before_text, after_source=after_text))
    files = attach_env_documents(files, trusted, lambda path: reader.text(head_oid, path))
    # Document-only unchanged observations need a before record for replay binding.
    for file in files:
        if file.before_source is not None:
            reader.read(base_oid, file.previous_path or file.path)
    subject = GitSubject(base_oid, head_oid, reader.tree_ids[base_oid], reader.tree_ids[head_oid], comparison_mode)
    catalog_digest = sha256(canonical_bytes({oid: reader.catalogs[oid] for oid in sorted(reader.catalogs)})).hexdigest()
    evidence = GitInputEvidence(subject, tuple(sorted(reader.records.values(), key=lambda a: a.identity)),
        trusted_oid, policy_path, trusted_policy_sha256, catalog_digest)
    return capture_inspection(changed_files=files, policy=trusted, policy_source=trusted_source,
        context=context or EvaluationContext(datetime.now(timezone.utc).date()),
        provenance={'source': 'immutable-git', 'head': head_oid, 'resolved_base': base_oid,
                    'comparison_mode': comparison_mode, 'policy_revision': trusted_oid,
                    'diff_mode': 'isolated-raw-git'},
        contract_proofs=contract_proofs, git_evidence=evidence)
