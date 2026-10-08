"""Approved engine artifacts, loaded-code attestation and pinned engine materialization.

An engine manifest names the exact package files of one Git commit. Approval is
an externally retained SHA-256 pin of the manifest bytes (the same model as the
trusted policy pin); the manifest itself is not a signature. Attestation hashes
the files that back modules actually imported in this process and the native
grammar libraries this process has loaded, and compares them with the manifest
and the reviewed parser pins. It does not attest the interpreter, bytecode
caches, third-party Python packages or code loaded after the attestation.
"""
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tempfile

from drift_gate.core.models.input_manifest import canonical_bytes

SCHEMA = 'engine-manifest-v1'
ATTESTATION = 'engine-attestation-v1'
# Producer identity scope used by evidence bundles (observed-producer-v1).
PRODUCER_SCOPE = ('core', 'adapters', 'utils')
_EXCLUDED = ('drift_gate/tests/', 'drift_gate/desktop/web/')
MAX_ENGINE_FILES = 2_000
MAX_ENGINE_BYTES = 64_000_000


class EngineArtifactError(ValueError):
    """Unpinned, inconsistent or unattestable engine artifact."""


def _package_relative(path):
    return path[len('drift_gate/'):]


def producer_digest(files):
    """Same digest as evidence_bundle.producer_identity over a file map."""
    scoped = {name: digest for name, digest in files.items()
              if name.endswith('.py') and name.split('/', 1)[0] in PRODUCER_SCOPE}
    return sha256(canonical_bytes(dict(sorted(scoped.items())))).hexdigest(), len(scoped)


def _git_files(root, ref):
    from drift_gate.adapters.git.immutable import _git, _resolve
    commit = _resolve(root, ref)
    listing = _git(root, ['ls-tree', '-r', '-z', '--full-tree', commit, '--', 'drift_gate'])
    files = {}
    for row in listing.split(b'\0'):
        if not row:
            continue
        meta, raw_path = row.split(b'\t', 1)
        mode, kind, oid = meta.decode('ascii').split()
        path = raw_path.decode('utf-8')
        if kind != 'blob' or any(path.startswith(prefix) for prefix in _EXCLUDED) or '__pycache__' in path:
            continue
        if mode not in {'100644', '100755'}:
            raise EngineArtifactError(f'engine file is not a regular blob: {path}')
        PurePosixPath(path)  # validated relative by Git
        files[path] = oid
        if len(files) > MAX_ENGINE_FILES:
            raise EngineArtifactError('engine exceeds file limit')
    if 'drift_gate/__init__.py' not in files:
        raise EngineArtifactError('ref does not contain a drift_gate package')
    return commit, files


def _blob(root, oid):
    from drift_gate.adapters.git.immutable import _git
    return _git(root, ['cat-file', 'blob', oid])


def build_manifest(root, ref):
    """Manifest of the engine package at an immutable commit, from Git objects only."""
    commit, entries = _git_files(root, ref)
    files, total = {}, 0
    for path, oid in sorted(entries.items()):
        raw = _blob(root, oid)
        total += len(raw)
        if total > MAX_ENGINE_BYTES:
            raise EngineArtifactError('engine exceeds byte limit')
        files[_package_relative(path)] = sha256(raw).hexdigest()
    producer, count = producer_digest(files)
    pins = files.get('adapters/parser_hashes.json')
    return {'schema': SCHEMA, 'commit': commit, 'package': 'drift_gate', 'files': files,
            'file_count': len(files), 'producer_source_sha256': producer, 'producer_source_files': count,
            'parser_pins_sha256': pins, 'excluded_prefixes': list(_EXCLUDED),
            'approval': 'external-sha256-pin', 'interpreter_attested': False}


def manifest_bytes(manifest):
    return canonical_bytes(manifest)


def load_manifest(path, expected_sha256):
    """Admit a manifest only through its externally retained SHA-256 pin."""
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise EngineArtifactError('an engine manifest requires an explicit SHA-256 pin')
    raw = Path(path).read_bytes()
    if sha256(raw).hexdigest() != expected_sha256:
        raise EngineArtifactError('engine manifest does not match its pin')
    manifest = json.loads(raw)
    if (not isinstance(manifest, dict) or manifest.get('schema') != SCHEMA
            or canonical_bytes(manifest) != raw or not isinstance(manifest.get('files'), dict)):
        raise EngineArtifactError('unsupported or noncanonical engine manifest')
    if producer_digest(manifest['files'])[0] != manifest['producer_source_sha256']:
        raise EngineArtifactError('engine manifest producer digest is inconsistent')
    return manifest


def materialize(root, manifest, destination):
    """Write the pinned engine from Git objects and verify every byte against the manifest."""
    commit, entries = _git_files(root, manifest['commit'])
    if commit != manifest['commit'] or {_package_relative(p) for p in entries} != set(manifest['files']):
        raise EngineArtifactError('engine commit does not reproduce the manifest file set')
    package = Path(destination) / 'drift_gate'
    for path, oid in entries.items():
        raw = _blob(root, oid)
        relative = _package_relative(path)
        if sha256(raw).hexdigest() != manifest['files'][relative]:
            raise EngineArtifactError(f'engine file differs from manifest: {relative}')
        target = package / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
    return package


def _loaded_engine_files(package_dir):
    package_dir = Path(package_dir).resolve()
    loaded = {}
    for name, module in list(sys.modules.items()):
        if name != 'drift_gate' and not name.startswith('drift_gate.'):
            continue
        origin = getattr(module, '__file__', None)
        if not origin:
            continue
        path = Path(origin).resolve()
        try:
            relative = path.relative_to(package_dir).as_posix()
        except ValueError:
            loaded[name] = {'path': str(path), 'outside_package': True, 'sha256': None}
            continue
        loaded[name] = {'path': relative, 'outside_package': False, 'sha256': sha256(path.read_bytes()).hexdigest()}
    return loaded


def _mapped_libraries():
    """Shared objects mapped into this process (Linux only; other OS use the cache directory)."""
    try:
        text = Path('/proc/self/maps').read_text()
    except OSError:
        return None
    return sorted({line.split()[-1] for line in text.splitlines()
                   if 'tree_sitter_' in line.rsplit('/', 1)[-1] and line.split()[-1].startswith('/')})


def _parser_libraries():
    from drift_gate.adapters.grammar_resources import expected_hashes, platform_key
    try:
        from tree_sitter_language_pack import __version__, cache_dir
    except ImportError:
        return {'basis': 'unavailable', 'libraries': [], 'matched': False}
    try:
        pins = expected_hashes(__version__)
    except RuntimeError as exc:
        return {'basis': 'no-reviewed-pins', 'detail': str(exc), 'libraries': [], 'matched': False}
    mapped = _mapped_libraries()
    if mapped is not None:
        basis = 'process-memory-map'
        paths = [Path(p) for p in mapped if Path(p).name in pins]
    else:
        basis = 'cache-directory-files-not-proven-loaded'
        directory = Path(cache_dir())
        paths = [directory / name for name in sorted(pins) if (directory / name).is_file()]
    rows = []
    for path in paths:
        digest = sha256(path.read_bytes()).hexdigest()
        rows.append({'name': path.name, 'sha256': digest, 'pinned': pins.get(path.name),
                     'matches_pin': digest == pins.get(path.name)})
    return {'basis': basis, 'platform': platform_key(), 'version': __version__, 'libraries': rows,
            'matched': bool(rows) and all(row['matches_pin'] for row in rows)}


def attest(manifest, *, package_dir=None):
    """Compare actually imported engine modules and loaded parsers with an approved manifest."""
    package_dir = Path(package_dir or Path(__file__).resolve().parents[1])
    loaded = _loaded_engine_files(package_dir)
    mismatches = sorted(name for name, row in loaded.items()
                        if row['outside_package'] or manifest['files'].get(row['path']) != row['sha256'])
    parsers = _parser_libraries()
    return {'schema': ATTESTATION, 'manifest_commit': manifest['commit'],
            'manifest_producer_source_sha256': manifest['producer_source_sha256'],
            'loaded_modules': len(loaded), 'module_mismatches': mismatches,
            'loaded_code_matches_manifest': bool(loaded) and not mismatches,
            'parsers': parsers, 'interpreter_attested': False,
            'scope': 'imported drift_gate modules and loaded grammar libraries at attestation time'}


def stage_engine(root, manifest):
    """Context-free helper returning a private directory containing the pinned engine."""
    directory = tempfile.mkdtemp(prefix='driftgate-engine-')
    try:
        materialize(root, manifest, directory)
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return directory


def remove_stage(directory):
    def writable(function, path, _):
        os.chmod(path, stat.S_IRWXU)
        function(path)
    shutil.rmtree(directory, onerror=writable)


def isolated_environment(extra=None):
    """Child environment without credentials or Python path injection."""
    secret_parts = {'TOKEN', 'SECRET', 'SECRETS', 'PASSWORD', 'PASSWD', 'KEY', 'KEYS', 'CREDENTIAL',
                    'CREDENTIALS', 'AUTH', 'COOKIE', 'SESSION', 'PAT'}
    env = {key: value for key, value in os.environ.items()
           if not secret_parts & set(key.upper().split('_'))
           and key.upper() not in {'PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONUSERBASE'}}
    env.update(extra or {})
    return env


BOOTSTRAP = r'''
import json, sys
engine = sys.argv[1]
sys.path.insert(0, engine)
sys.path.insert(1, sys.argv[5])  # attestation helper from the verifying engine, outside drift_gate
mode = sys.argv[2]
args = json.loads(sys.argv[3])
manifest = json.loads(open(sys.argv[4], encoding='utf-8').read())
import io, contextlib
out = io.StringIO()
code = 0
with contextlib.redirect_stdout(out):
    try:
        if mode == 'check':
            from drift_gate.adapters.cli.runner import run_cli
            run_cli(args)
        elif mode == 'replay':
            from drift_gate.adapters.evidence_bundle import load_bundle
            bundle = load_bundle(args['path'], expected_receipt_sha256=args.get('receipt'))
            print(json.dumps(bundle.replay().to_dict()))
        else:
            raise SystemExit(64)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
from engine_attest import attest
sys.stdout.write(json.dumps({'exit_code': code, 'stdout': out.getvalue(),
                             'attestation': attest(manifest, package_dir=engine + '/drift_gate')}))
'''


def run_pinned(root, manifest, mode, args, *, cwd, timeout=600):
    """Run the pinned engine in a child interpreter (-I: no user site, no PYTHONPATH)."""
    import subprocess
    directory = stage_engine(root, manifest)
    try:
        manifest_file = Path(directory) / 'manifest.json'
        manifest_file.write_bytes(manifest_bytes(manifest))
        helper = Path(directory) / '_attest'
        helper.mkdir()
        shutil.copyfile(__file__, helper / 'engine_attest.py')
        completed = subprocess.run([sys.executable, '-I', '-c', BOOTSTRAP, directory, mode, json.dumps(args),
                                    str(manifest_file), str(helper)], cwd=cwd, env=isolated_environment(),
                                   capture_output=True, timeout=timeout, text=True)
    finally:
        remove_stage(directory)
    try:
        envelope = json.loads(completed.stdout)
    except ValueError as exc:
        raise EngineArtifactError(f'pinned engine produced no attestation (exit {completed.returncode}): '
                                  f'{completed.stderr[-2000:]}') from exc
    return envelope
