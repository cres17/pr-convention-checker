"""Real Git object, policy-anchor and frozen-verifier counterexamples."""
from copy import deepcopy
from dataclasses import replace
from datetime import date
from hashlib import sha256
import json
import subprocess

import pytest

from drift_gate.adapters.git import immutable
from drift_gate.adapters.inspection import inspect_snapshot
from drift_gate.adapters.mcp import tools
from drift_gate.adapters.cli.runner import run_cli
from drift_gate.core.models.evaluation_context import EvaluationContext
from drift_gate.core.models.input_manifest import ArtifactState
from drift_gate.desktop.package_git_check import POLICY, source, run_git_controls, validate_git_controls


def git(root, *args):
    return subprocess.check_output(['git', '-c', 'core.autocrlf=false', *args], cwd=root, stderr=subprocess.PIPE)


def commit(root, name):
    git(root, 'add', '.'); git(root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', name)
    return git(root, 'rev-parse', 'HEAD').decode().strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init'); (tmp_path / 'src').mkdir(); (tmp_path / 'docs').mkdir()
    (tmp_path / '.drift-gate.yml').write_bytes(POLICY.encode())
    (tmp_path / 'src/api.py').write_bytes(source('/old').encode())
    (tmp_path / 'docs/api.md').write_bytes(b'GET /old\n')
    base = commit(tmp_path, 'base')
    (tmp_path / 'src/api.py').write_bytes(source('/new').encode())
    head = commit(tmp_path, 'head')
    return tmp_path, base, head


def capture(repo, **kwargs):
    root, base, head = repo
    return immutable.collect_git_snapshot(**{'root': root, 'base': base, 'head': head,
        'trusted_policy_ref': base, 'trusted_policy_sha256': sha256(POLICY.encode()).hexdigest(),
        'context': EvaluationContext(date(2026, 10, 7)), **kwargs})


def test_exact_crlf_bytes_and_git_oid_survive_working_tree_changes(repo):
    root, base, head = repo
    first = capture(repo)
    blob = first.git_evidence.get(head, 'src/api.py')
    assert blob.content == source('/new').encode()
    assert blob.object_id == git(root, 'rev-parse', head + ':src/api.py').decode().strip()
    (root / 'src/api.py').write_bytes(b'broken working tree')
    (root / '.drift-gate.yml').unlink()
    again = capture(repo)
    assert first.payload == again.payload and first.git_evidence == again.git_evidence
    assert inspect_snapshot(first).result == inspect_snapshot(again).result == 'fail'


@pytest.mark.parametrize('location', ['working', 'index', 'info', 'global', 'local-config'])
def test_diff_inputs_ignore_unpinned_attributes_and_configuration(repo, location):
    root, _, _ = repo
    expected = capture(repo)
    if location in {'working', 'index'}:
        (root / '.gitattributes').write_bytes(b'src/api.py binary\n')
        if location == 'index':
            git(root, 'add', '.gitattributes')
            (root / '.gitattributes').unlink()  # Exercise Git's index fallback.
    elif location == 'info':
        (root / '.git/info/attributes').write_bytes(b'src/api.py binary\n')
    elif location == 'global':
        path = root / 'user-attributes'
        path.write_bytes(b'src/api.py binary\n')
        git(root, 'config', 'core.attributesFile', str(path))
    else:
        git(root, 'config', 'diff.noprefix', 'true')
        git(root, 'config', 'diff.context', '100')
        git(root, 'config', 'diff.algorithm', 'histogram')
    index = (root / '.git/index').read_bytes()
    config = (root / '.git/config').read_bytes()
    actual = capture(repo)
    assert actual.payload == expected.payload and actual.git_evidence == expected.git_evidence
    assert (root / '.git/index').read_bytes() == index
    assert (root / '.git/config').read_bytes() == config
    assert inspect_snapshot(actual).verification == inspect_snapshot(expected).verification == 'verified'


@pytest.mark.parametrize('key,value', [('GIT_DIR', '/not-the-selected-repository'),
    ('GIT_ATTR_SOURCE', 'missing-tree'), ('GIT_DIFF_OPTS', '--unified=100')])
def test_caller_git_environment_cannot_redirect_immutable_inputs(repo, monkeypatch, key, value):
    expected = capture(repo)
    monkeypatch.setenv(key, value)
    actual = capture(repo)
    assert actual.payload == expected.payload and actual.git_evidence == expected.git_evidence


def test_replacement_refs_cannot_change_pinned_commit_or_blob(repo):
    root, base, head = repo
    expected = capture(repo)
    git(root, 'replace', base, head)
    assert capture(repo).git_evidence == expected.git_evidence
    old_blob = expected.git_evidence.get(base, 'src/api.py').object_id
    new_blob = expected.git_evidence.get(head, 'src/api.py').object_id
    git(root, 'replace', old_blob, new_blob)
    assert capture(repo).git_evidence == expected.git_evidence


def test_branch_moves_during_collection_do_not_change_resolved_subject(repo, monkeypatch):
    root, base, head = repo
    git(root, 'branch', 'target', head)
    real = immutable.GitObjectReader.catalog; moved = False
    def move(reader, oid):
        nonlocal moved
        if not moved:
            moved = True; git(root, 'update-ref', 'refs/heads/target', base)
        return real(reader, oid)
    monkeypatch.setattr(immutable.GitObjectReader, 'catalog', move)
    captured = capture(repo, head='target')
    assert captured.git_evidence.subject.head_oid == head
    assert git(root, 'rev-parse', 'target').decode().strip() == base
    assert inspect_snapshot(captured).result == 'fail'


@pytest.mark.parametrize('pin', ['0' * 64, 'bad', None])
def test_wrong_or_missing_pin_cannot_produce_success(repo, pin):
    with pytest.raises(ValueError, match='SHA-256'): capture(repo, trusted_policy_sha256=pin)


@pytest.mark.parametrize('replacement', [POLICY.replace('severity: blocker', 'severity: minor'),
                                      'rules: []\n', POLICY.replace('src/**', 'other/**')])
def test_weakened_candidate_is_rejected(repo, replacement):
    root, base, _ = repo
    (root / '.drift-gate.yml').write_bytes(replacement.encode())
    head = commit(root, 'weaken')
    with pytest.raises(Exception, match='weakened|at least one'): capture(repo, head=head)


def test_candidate_strengthening_does_not_silently_replace_selected_trusted_policy(repo):
    root, _, _ = repo
    (root / '.drift-gate.yml').write_bytes(POLICY.replace('any_changed: [src/**]', 'any_changed: [src/**, extra/**]').encode())
    head = commit(root, 'stronger candidate')
    snapshot = capture(repo, head=head)
    assert snapshot.materialize()['policy_source'] == POLICY
    assert snapshot.git_evidence.to_dict()['policy_anchor']['evaluation_policy'] == 'pinned-policy'
    assert not snapshot.git_evidence.to_dict()['policy_anchor']['organization_approval_verified']


def test_rename_deletion_and_absence_are_bound_to_versioned_trees(repo):
    root, base, _ = repo
    git(root, 'mv', 'src/api.py', 'src/renamed.py')
    (root / 'docs/api.md').unlink()
    head = commit(root, 'rename and delete')
    snapshot = capture(repo, head=head)
    evidence = snapshot.git_evidence
    assert evidence.get(base, 'src/api.py').content == source('/old').encode()
    assert evidence.get(head, 'src/renamed.py').content == source('/new').encode()
    assert evidence.get(head, 'docs/api.md').state == ArtifactState.ABSENT
    assert inspect_snapshot(snapshot).result == 'fail'


def test_symlink_bytes_are_captured_without_following_target(repo):
    root, _, _ = repo
    try: (root / 'src/link.py').symlink_to('/not-readable-outside-repository')
    except OSError: pytest.skip('symlink creation unavailable')
    head = commit(root, 'link')
    snapshot = capture(repo, head=head)
    item = snapshot.git_evidence.get(head, 'src/link.py')
    assert item.mode == '120000' and item.content == b'/not-readable-outside-repository'
    file = next(f for f in snapshot.materialize()['changed_files'] if f.path == 'src/link.py')
    assert file.after_source is None


@pytest.mark.parametrize('content', [b'\xff\x00', b'x' * 1_000_001], ids=['binary', 'oversized'])
def test_unsupported_or_oversized_text_is_never_reported_as_verified(repo, content):
    root, _, _ = repo
    (root / 'src/api.py').write_bytes(content); head = commit(root, 'unreadable')
    if len(content) > 1_000_000:
        with pytest.raises(ValueError, match='limit'): capture(repo, head=head)
    else:
        result = inspect_snapshot(capture(repo, head=head))
        assert result.verification != 'verified'


def test_manifest_and_original_bytes_cannot_be_substituted(repo):
    snapshot = capture(repo)
    artifact = snapshot.git_evidence.get(snapshot.git_evidence.subject.head_oid, 'src/api.py')
    with pytest.raises(ValueError, match='identity mismatch'): replace(artifact, content=b'forged')
    with pytest.raises(ValueError, match='missing'): replace(snapshot, git_evidence=None)
    with pytest.raises(ValueError, match='caller pin'): replace(snapshot.git_evidence, expected_policy_sha256='0' * 64)


def test_merge_base_mode_ignores_changes_only_on_ahead_base(repo):
    root, base, head = repo
    git(root, 'checkout', '-b', 'ahead', base)
    (root / 'base-only').write_bytes(b'base')
    tip = commit(root, 'ahead base')
    snapshot = capture(repo, base=tip, head=head, comparison_mode='merge-base')
    assert snapshot.git_evidence.subject.base_oid == base
    assert 'base-only' not in [f.path for f in snapshot.materialize()['changed_files']]


def test_sha256_git_object_format_supported(tmp_path):
    result = subprocess.run(['git', 'init', '--object-format=sha256', str(tmp_path)], capture_output=True)
    if result.returncode: pytest.skip('Git SHA256 repositories unavailable')
    (tmp_path / '.drift-gate.yml').write_bytes(POLICY.encode())
    base = commit(tmp_path, 'base')
    snapshot = capture((tmp_path, base, base))
    assert len(snapshot.git_evidence.subject.head_oid) == 64
    assert inspect_snapshot(snapshot).result == 'pass'


def test_cli_and_mcp_use_same_git_policy_evidence(repo, monkeypatch, capsys):
    root, base, head = repo; monkeypatch.chdir(root)
    pin = sha256(POLICY.encode()).hexdigest()
    with pytest.raises(SystemExit) as done:
        run_cli(['check', '--base', base, '--head', head, '--trusted-policy-ref', base,
                 '--trusted-policy-sha256', pin, '--json'])
    assert done.value.code == 1
    cli = json.loads(capsys.readouterr().out)
    mcp = tools.drift_gate_check_git(base=base, head=head, trusted_policy_ref=base, trusted_policy_sha256=pin, mode='full')
    assert cli['execution']['input_capture'] == mcp['execution']['input_capture']
    compact = tools.drift_gate_check_git(base=base, head=head, trusted_policy_ref=base, trusted_policy_sha256=pin, mode='compact')
    git_capture = compact['execution']['input_capture']['git_input']
    assert git_capture['manifest_entries_omitted'] and 'artifacts' not in git_capture
    assert git_capture['manifest_sha256'] == mcp['execution']['input_capture']['git_input']['manifest_sha256']


def test_mcp_git_tool_does_not_inspect_working_tree_policy_for_path_checks(repo, monkeypatch):
    from drift_gate.adapters.mcp import server
    root, base, head = repo; monkeypatch.chdir(root)
    (root / '.drift-gate.yml').write_bytes(b'x' * 2_000_000)
    monkeypatch.setattr(server, 'ALLOWED_ROOT', root)
    result = server.handle_request({'tool': 'drift_gate_check_git', 'args': {
        'base': base, 'head': head, 'trusted_policy_ref': base,
        'trusted_policy_sha256': sha256(POLICY.encode()).hexdigest(), 'mode': 'full'}})
    assert result['ok'] and result['result']['result'] == 'fail'


@pytest.mark.parametrize('arguments', [['--head', 'HEAD'], ['--trusted-policy-ref', 'HEAD'],
                                     ['--head', 'HEAD', '--trusted-policy-ref', 'HEAD', '--trusted-policy-sha256', '0' * 64]])
def test_invalid_cli_immutable_input_is_exit_two_without_normal_result(repo, monkeypatch, capsys, arguments):
    monkeypatch.chdir(repo[0])
    with pytest.raises(SystemExit) as done: run_cli(['check', '--json', *arguments])
    assert done.value.code == 2
    output = json.loads(capsys.readouterr().out)
    assert output['error']['code'] == 'input_error' and 'result' not in output


@pytest.fixture(scope='module')
def package_controls():
    return run_git_controls()


def test_packaged_git_control_protocol_accepts_real_controls(package_controls):
    validate_git_controls(package_controls)


@pytest.mark.parametrize('damage', ['missing', 'wrong-pin', 'wrong-subject', 'claimed-approval',
                                  'wrong-decision', 'wrong-raw-hash', 'wrong-blob-oid', 'old-protocol'])
def test_packaged_git_control_protocol_rejects_false_success(package_controls, damage):
    data = deepcopy(package_controls)
    if damage == 'missing': data['checks'] = {}
    elif damage == 'old-protocol': data['schema'] = 'packaged-git-controls-v1'
    elif damage == 'wrong-pin': data['policy_pin'] = '0' * 64
    elif damage == 'wrong-subject': data['subject']['base'] = 'a' * 40
    elif damage == 'claimed-approval':
        data['cases']['stale']['execution']['input_capture']['git_input']['policy_anchor']['organization_approval_verified'] = True
    elif damage in {'wrong-raw-hash', 'wrong-blob-oid'}:
        evidence = data['cases']['stale']['execution']['input_capture']['git_input']
        entry = next(a for a in evidence['artifacts'] if a['path'] == 'src/api.py'
                     and a['revision'] == evidence['subject']['head_oid'])
        key = 'raw_sha256' if damage == 'wrong-raw-hash' else 'object_id'
        entry[key] = '0' * len(entry[key])
    else: data['cases']['stale']['result'] = 'pass'
    with pytest.raises(RuntimeError): validate_git_controls(data)
