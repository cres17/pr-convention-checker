"""W09: trusted verifier vs candidate, approval envelopes, pinned-engine attestation and replay."""
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from drift_gate.adapters import engine_artifact as engines
from drift_gate.adapters import approval_signing
from drift_gate.adapters.bundle_codec import BundleError, require_replayable
from drift_gate.adapters.trusted_validation import certified_replay, trusted_check
from drift_gate.core.trust.validation import EngineRun, decide
from drift_gate.desktop.package_git_check import POLICY, source

PACKAGE = Path(__file__).resolve().parents[1]


def git(root, *args):
    return subprocess.check_output(['git', '-c', 'core.autocrlf=false', *args], cwd=root, stderr=subprocess.PIPE)


def commit(root, message):
    git(root, 'add', '-A')
    git(root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-q', '-m', message)
    return git(root, 'rev-parse', 'HEAD').decode().strip()


def copy_engine(target):
    def ignore(directory, names):
        rel = Path(directory).relative_to(PACKAGE).as_posix()
        skipped = {'__pycache__', 'tests'} if rel == '.' else {'__pycache__'}
        if rel == 'desktop':
            skipped.add('web')
        return [n for n in names if n in skipped or n.endswith('.pyc')]
    shutil.copytree(PACKAGE, target / 'drift_gate', ignore=ignore)


@pytest.fixture(scope='module')
def engine_repo(tmp_path_factory):
    """A repository whose base commit carries this engine, a policy and an API module."""
    root = tmp_path_factory.mktemp('trusted-repo')
    git(root, 'init', '-q')
    copy_engine(root)
    (root / 'src').mkdir(); (root / 'docs').mkdir()
    (root / '.drift-gate.yml').write_bytes(POLICY.encode())
    (root / 'src/api.py').write_bytes(source('/old').encode())
    (root / 'docs/api.md').write_bytes(b'GET /old\n')
    base = commit(root, 'base with engine')
    (root / 'src/api.py').write_bytes(source('/new').encode())
    stale = commit(root, 'route changed, docs stale')
    (root / 'docs/api.md').write_bytes(b'GET /new\n')
    fixed = commit(root, 'docs updated')
    (root / 'drift_gate/core/gating/gate.py').write_text('# weakened checker\n', encoding='utf-8')
    tampered = commit(root, 'candidate edits the checker')
    manifest = engines.build_manifest(root, base)
    return {'root': root, 'base': base, 'stale': stale, 'fixed': fixed, 'tampered': tampered, 'manifest': manifest}


POLICY_SHA = sha256(POLICY.encode()).hexdigest()


# -- pure decision -----------------------------------------------------------
def run(role, result, *, attested=True, error=''):
    return EngineRun(role, result, 'ref', attested, error or ('' if result else 'failed'))


@pytest.mark.parametrize('trusted, candidate, paths, action, reason', [
    (run('trusted', 'pass'), run('candidate', 'pass'), ['src/api.py'], 'allow', None),
    (run('trusted', 'fail'), run('candidate', 'pass'), ['src/api.py'], 'block', 'candidate-engine-weaker'),
    (run('trusted', 'pass'), run('candidate', 'fail'), ['src/api.py'], 'review', 'candidate-engine-stricter'),
    (run('trusted', 'pass'), run('candidate', 'pass'), ['drift_gate/core/gating/gate.py'], 'review',
     'candidate-changes-checker-policy-or-workflow'),
    (run('trusted', 'pass'), run('candidate', 'pass'), ['.github/workflows/ci.yml'], 'review',
     'candidate-changes-checker-policy-or-workflow'),
    (run('trusted', None), run('candidate', 'pass'), ['src/api.py'], 'review', 'trusted-engine-unavailable'),
    (run('trusted', 'pass', attested=False), run('candidate', 'pass'), ['src/api.py'], 'review',
     'trusted-engine-unattested'),
])
def test_candidate_pass_is_never_the_merge_basis(trusted, candidate, paths, action, reason):
    decision = decide(trusted, candidate, paths)
    assert decision.action == action
    if reason:
        assert reason in decision.reasons
    if trusted.gate_result is None or not trusted.attested:
        assert decision.merge_basis == 'none'


# -- engine manifest and attestation -----------------------------------------
def test_manifest_pin_and_materialization_reject_substitution(engine_repo, tmp_path):
    manifest = engine_repo['manifest']
    raw = engines.manifest_bytes(manifest)
    path = tmp_path / 'engine.json'
    path.write_bytes(raw)
    assert engines.load_manifest(path, sha256(raw).hexdigest()) == manifest
    with pytest.raises(engines.EngineArtifactError, match='pin'):
        engines.load_manifest(path, '0' * 64)
    forged = dict(manifest, files={**manifest['files'], 'core/engine.py': '0' * 64})
    with pytest.raises(engines.EngineArtifactError):
        engines.materialize(engine_repo['root'], forged, tmp_path / 'stage')
    # The candidate commit's checker edit is a different engine, not the approved one.
    candidate = engines.build_manifest(engine_repo['root'], engine_repo['tampered'])
    assert candidate['producer_source_sha256'] != manifest['producer_source_sha256']


def test_attestation_compares_imported_modules_and_loaded_parsers(engine_repo):
    from drift_gate.adapters.grammar_resources import get_parser
    get_parser('python')
    manifest = engine_repo['manifest']
    report = engines.attest(manifest)
    # pytest imports test modules, which the engine manifest deliberately excludes:
    # attestation must report them rather than treat loaded code as approved.
    assert report['module_mismatches'] and all(name.startswith('drift_gate.tests') for name in report['module_mismatches'])
    assert not report['loaded_code_matches_manifest']
    assert report['parsers']['libraries'] and report['parsers']['matched']
    assert report['interpreter_attested'] is False
    altered = dict(manifest, files={**manifest['files'], 'core/engine.py': '0' * 64})
    assert 'drift_gate.core.engine' in engines.attest(altered)['module_mismatches']


def test_isolated_environment_drops_credentials(monkeypatch):
    for name in ('GITHUB_TOKEN', 'ANTHROPIC_API_KEY', 'DRIFT_GATE_APPROVAL_SIGNING_KEY', 'PYTHONPATH'):
        monkeypatch.setenv(name, 'secret')
    env = engines.isolated_environment()
    assert not {'GITHUB_TOKEN', 'ANTHROPIC_API_KEY', 'DRIFT_GATE_APPROVAL_SIGNING_KEY', 'PYTHONPATH'} & set(env)


# -- trusted check end to end ---------------------------------------------------
def check(engine_repo, head):
    r = engine_repo
    return trusted_check(root=r['root'], base=r['base'], head=r[head], policy='.drift-gate.yml',
                         trusted_policy_ref=r['base'], trusted_policy_sha256=POLICY_SHA, manifest=r['manifest'])


def test_trusted_engine_runs_in_a_separate_interpreter_and_decides(engine_repo):
    stale = check(engine_repo, 'stale')
    assert stale['trusted']['gate_result'] == 'fail' and stale['decision']['action'] == 'block'
    assert stale['trusted']['attestation']['loaded_code_matches_manifest']
    assert stale['trusted']['input_sha256'] == stale['candidate']['input_sha256']
    fixed = check(engine_repo, 'fixed')
    assert fixed['trusted']['gate_result'] == 'pass' and fixed['decision']['action'] == 'allow'


def test_weakened_candidate_engine_cannot_turn_a_trusted_fail_into_a_pass(engine_repo, monkeypatch):
    from drift_gate.adapters import inspection

    class Weakened:
        result = 'pass'

    monkeypatch.setattr(inspection, 'inspect_snapshot', lambda *a, **k: Weakened())
    stale = check(engine_repo, 'stale')
    assert stale['candidate']['gate_result'] == 'pass'
    assert (stale['trusted']['gate_result'], stale['decision']['action']) == ('fail', 'block')
    assert 'candidate-engine-weaker' in stale['decision']['reasons']


def test_candidate_that_edits_the_checker_needs_review_even_when_it_passes(engine_repo):
    data = check(engine_repo, 'tampered')
    assert data['decision']['action'] == 'review'
    assert 'drift_gate/core/gating/gate.py' in data['decision']['trust_sensitive_paths']


def test_cli_trusted_check_exit_codes(engine_repo, tmp_path, monkeypatch, capsys):
    from drift_gate.adapters.cli.runner import run_cli
    raw = engines.manifest_bytes(engine_repo['manifest'])
    (tmp_path / 'engine.json').write_bytes(raw)
    monkeypatch.chdir(engine_repo['root'])
    with pytest.raises(SystemExit) as exit:
        run_cli(['trusted-check', '--base', engine_repo['base'], '--head', engine_repo['stale'],
                 '--trusted-policy-ref', engine_repo['base'], '--trusted-policy-sha256', POLICY_SHA,
                 '--engine-manifest', str(tmp_path / 'engine.json'), '--engine-manifest-sha256',
                 sha256(raw).hexdigest(), '--json'])
    assert exit.value.code == 1
    assert json.loads(capsys.readouterr().out)['decision']['merge_basis'] == 'trusted-engine'


# -- certified replay -----------------------------------------------------------
def test_certified_replay_uses_the_producing_engine(engine_repo, tmp_path, monkeypatch):
    from drift_gate.adapters.evidence_bundle import save_bundle
    from drift_gate.adapters.git.immutable import collect_git_snapshot
    from drift_gate.adapters.inspection import inspect_snapshot
    r = engine_repo
    snapshot = collect_git_snapshot(root=r['root'], base=r['base'], head=r['stale'], trusted_policy_ref=r['base'],
                                    trusted_policy_sha256=POLICY_SHA, policy_path='.drift-gate.yml')
    bundle = save_bundle(inspect_snapshot(snapshot), tmp_path / 'evidence')
    data = certified_replay(bundle.path, root=r['root'], manifest=r['manifest'])
    assert data['certified'] and data['recorded_result_matches_pinned_engine']
    other = engines.build_manifest(r['root'], r['tampered'])
    refused = certified_replay(bundle.path, root=r['root'], manifest=other)
    assert (refused['certified'], refused['reason']) == (False, 'bundle-producer-differs-from-pinned-engine')


# -- signed approval envelopes ------------------------------------------------------
def test_stored_waiver_is_admitted_only_with_a_verifiable_signature(monkeypatch):
    import base64
    from drift_gate.adapters.snapshot import capture_inspection
    from drift_gate.core.models.evaluation_context import EvaluationContext
    from drift_gate.core.models.result import DriftIgnoreDirective
    from drift_gate.core.policy.loader import load_policy_from_text
    from datetime import date
    key = base64.b64encode(b'k' * 32).decode()
    envelope = {'schema': 'approval-envelope-v1', 'rule_id': 'r', 'scope_paths': ['src/api.py'],
                'subject_head_oid': 'a' * 40, 'policy_sha256': POLICY_SHA, 'reason': 'x', 'valid_from': '2026-01-01',
                'expires': None, 'approvers': ['o'], 'authority': {'kind': 'github-codeowners-review',
                'codeowners_sha256': 'c' * 64, 'reviews': [{'commit_id': 'a' * 40, 'state': 'APPROVED'}]}}
    signature = approval_signing.sign(envelope, 'org-1', b'k' * 32)
    directive = DriftIgnoreDirective('r', 'x', approval_verified=True, approval_commit='a' * 40,
                                     approval_envelope=envelope, approval_signature=signature)
    policy = load_policy_from_text(POLICY)
    snapshot = capture_inspection(changed_files=[], policy=policy, drift_ignores=[directive],
                                  context=EvaluationContext(date(2026, 1, 2), 'a' * 40, POLICY_SHA),
                                  policy_source=POLICY)
    require_replayable(snapshot, keys={'org-1': b'k' * 32})
    with pytest.raises(BundleError, match='keyring'):
        require_replayable(snapshot, keys={})
    with pytest.raises(BundleError, match='does not match'):
        require_replayable(snapshot, keys={'org-1': b'z' * 32})
    monkeypatch.setenv(approval_signing.KEYRING_ENV, json.dumps({'org-1': key}))
    require_replayable(snapshot)
    unsigned = DriftIgnoreDirective('r', 'x', approval_verified=True, approval_commit='a' * 40,
                                    approval_envelope=envelope)
    plain = capture_inspection(changed_files=[], policy=policy, drift_ignores=[unsigned],
                               context=EvaluationContext(date(2026, 1, 2)), policy_source=POLICY)
    with pytest.raises(BundleError, match='signed'):
        require_replayable(plain, keys={'org-1': b'k' * 32})
