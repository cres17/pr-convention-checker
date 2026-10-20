"""Local checks compare a branch with the fork point of --base by default (C05 of the 2026-10-06 review).

With ``git diff <base>``, files the base branch gained after this branch forked appear as this
branch's deletions, so ``check --base main`` on a branch behind main reported a false BLOCKER.
"""
import json
import subprocess
from hashlib import sha256

import pytest

from drift_gate.adapters.cli.parser import build_parser as _build_parser
from drift_gate.adapters.cli.runner import run_cli
from drift_gate.adapters.git.client import GitAdapter

POLICY = '''rules:
  - id: api-contract-sync
    when:
      any_changed: ["src/routes/**"]
    require:
      groups:
        - name: api docs
          any_changed: ["docs/api.md"]
    severity: blocker
'''


def git(root, *args):
    return subprocess.check_output(['git', '-c', 'core.autocrlf=false', *args], cwd=root,
                                   stderr=subprocess.PIPE).decode().strip()


def commit(root, message):
    git(root, 'add', '-A')
    git(root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', message)
    return git(root, 'rev-parse', 'HEAD')


@pytest.fixture
def behind_main(tmp_path, monkeypatch):
    """A feature branch forked from main; main later adds a route the branch never touched."""
    git(tmp_path, 'init', '-q', '-b', 'main')
    (tmp_path / '.drift-gate.yml').write_text(POLICY, encoding='utf-8', newline='\n')
    (tmp_path / 'src/routes').mkdir(parents=True)
    (tmp_path / 'src/routes/users.py').write_text('X = 1\n', encoding='utf-8')
    (tmp_path / 'README.md').write_text('readme\n', encoding='utf-8')
    fork = commit(tmp_path, 'base')
    git(tmp_path, 'checkout', '-q', '-b', 'feature')
    (tmp_path / 'README.md').write_text('readme, edited on the branch\n', encoding='utf-8')
    commit(tmp_path, 'feature work')
    git(tmp_path, 'checkout', '-q', 'main')
    (tmp_path / 'src/routes/new.py').write_text('Y = 2\n', encoding='utf-8')
    commit(tmp_path, 'main moves ahead')
    git(tmp_path, 'checkout', '-q', 'feature')
    monkeypatch.chdir(tmp_path)
    return tmp_path, fork


def check(argv, capsys):
    with pytest.raises(SystemExit) as done:
        run_cli(['check', *argv, '--json'])
    return done.value.code, json.loads(capsys.readouterr().out)


def test_branch_behind_main_passes_by_default(behind_main, capsys):
    root, fork = behind_main
    code, result = check(['--base', 'main'], capsys)
    assert code == 0 and result['result'] == 'pass' and result['violations'] == []
    provenance = GitAdapter(root)
    assert [f.path for f in provenance.get_changed_files('main')] == ['README.md']
    assert provenance.provenance['comparison_mode'] == 'merge-base'
    assert provenance.provenance['resolved_base'] == fork


def test_commit_mode_keeps_the_literal_base(behind_main, capsys):
    code, result = check(['--base', 'main', '--comparison-mode', 'commit'], capsys)
    assert code == 1 and result['result'] == 'fail'
    assert result['violations'][0]['rule_id'] == 'api-contract-sync'
    assert [(f['path'], f['status']) for f in result['violations'][0]['trigger_files']] == [('src/routes/new.py', 'deleted')]


def test_explicit_merge_base_equals_the_default(behind_main, capsys):
    default = check(['--base', 'main'], capsys)
    explicit = check(['--base', 'main', '--comparison-mode', 'merge-base'], capsys)
    assert default[0] == explicit[0] and default[1]['result'] == explicit[1]['result']
    assert default[1]['violations'] == explicit[1]['violations']


def test_working_tree_check_against_head_is_unchanged(behind_main, capsys):
    root, _ = behind_main
    (root / 'src/routes/users.py').write_text('X = 3\n', encoding='utf-8')
    for mode in ([], ['--comparison-mode', 'commit']):
        code, result = check(['--base', 'HEAD', *mode], capsys)
        assert code == 1 and result['violations'][0]['rule_id'] == 'api-contract-sync'


def test_unrelated_history_is_an_input_error_not_a_silent_fallback(behind_main, capsys):
    root, _ = behind_main
    git(root, 'checkout', '-q', '--orphan', 'unrelated')
    commit(root, 'no shared history')
    code, error = check(['--base', 'main'], capsys)
    assert code == 2 and error['error']['code'] == 'input_error'
    assert '--comparison-mode commit' in error['error']['message']
    code, result = check(['--base', 'main', '--comparison-mode', 'commit'], capsys)
    assert code in (0, 1) and 'result' in result


def test_immutable_head_mode_keeps_commit_by_default(behind_main, capsys):
    root, fork = behind_main
    main = git(root, 'rev-parse', 'main')
    head = git(root, 'rev-parse', 'feature')
    pin = sha256(POLICY.encode()).hexdigest()
    code, result = check(['--base', main, '--head', head, '--trusted-policy-ref', fork,
                          '--trusted-policy-sha256', pin], capsys)
    subject = result['execution']['input_capture']['git_input']['subject']
    assert subject['comparison_mode'] == 'commit' and subject['base_oid'] == main
    code, result = check(['--base', main, '--head', head, '--trusted-policy-ref', fork,
                          '--trusted-policy-sha256', pin, '--comparison-mode', 'merge-base'], capsys)
    subject = result['execution']['input_capture']['git_input']['subject']
    assert subject['comparison_mode'] == 'merge-base' and subject['base_oid'] == fork


@pytest.mark.parametrize('command', ['review', 'self-audit'])
def test_other_local_commands_share_the_default_and_the_option(command):
    parser = _build_parser()
    assert parser.parse_args([command]).comparison_mode == 'merge-base'
    assert parser.parse_args([command, '--comparison-mode', 'commit']).comparison_mode == 'commit'


def test_trusted_check_keeps_an_explicit_commit_pair_by_default():
    args = _build_parser().parse_args(['trusted-check', '--base', 'a', '--head', 'b', '--trusted-policy-ref', 'c',
                                       '--trusted-policy-sha256', 'd', '--engine-manifest', 'e',
                                       '--engine-manifest-sha256', 'f'])
    assert args.comparison_mode == 'commit'
