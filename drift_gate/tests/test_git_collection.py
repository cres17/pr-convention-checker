"""Actual Git inputs, not pre-decoded path mocks."""
import os
import subprocess
import sys

import pytest
from drift_gate.adapters.git.client import GitAdapter, GitInputError, _parse_name_status
from drift_gate.core.engine import run
from drift_gate.core.models.policy import Policy


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)


def repository(tmp_path):
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.name', 'Fixture')
    git(tmp_path, 'config', 'user.email', 'fixture@example.invalid')
    (tmp_path / 'seed').write_text('first')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-qm', 'seed')
    return tmp_path


@pytest.mark.parametrize('name', ['결제.py', 'space name.py', ' trailing.py ', 'quote".py', 'tab\t.py', 'line\n.py', 'literal[1].py'])
def test_exact_path_and_patch_are_independent_of_quote_configuration(tmp_path, name):
    if os.name == 'nt' and any(c in name for c in '"\t\n') or (os.name == 'nt' and name.endswith(' ')):
        pytest.skip('Windows disallows this filename')
    root = repository(tmp_path)
    (root / 'src/routes').mkdir(parents=True)
    path = root / 'src/routes' / name
    path.write_text('value = 1\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'route')
    path.write_text('value = 2\n')
    policy = Policy.from_dict({'rules':[{'id':'docs', 'when':{'any_changed':['src/routes/**']},
      'require':{'groups':[{'name':'spec','any_changed':['docs/spec.md']}]}, 'severity':'blocker'}]})
    for quoted in ['true','false']:
        git(root, 'config', 'core.quotePath', quoted)
        files = GitAdapter(root).get_changed_files('HEAD')
        assert files[0].path == 'src/routes/' + name
        assert '+value = 2' in files[0].patch
        assert run(files, policy=policy).result == 'fail'


def test_unicode_rename_retains_both_names(tmp_path):
    root = repository(tmp_path)
    (root / '이전.py').write_text('value = 1\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'old')
    (root / '이전.py').rename(root / '새 이름.py')
    git(root, 'add', '-A')
    file = GitAdapter(root).get_changed_files('HEAD')[0]
    assert file.status == 'renamed' and file.previous_path == '이전.py' and file.path == '새 이름.py'
    assert 'rename' in file.patch


def test_bad_base_is_never_replaced_or_reported_as_empty(tmp_path):
    root = repository(tmp_path)
    (root / 'seed').write_text('changed')
    with pytest.raises(GitInputError): GitAdapter(root).get_changed_files('missing-ref')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'second')
    with pytest.raises(GitInputError): GitAdapter(root).get_changed_files('missing-ref')
    assert GitAdapter(root).get_changed_files('HEAD') == []


def test_cli_bad_base_exits_as_input_error(tmp_path):
    root = repository(tmp_path)
    result = subprocess.run([sys.executable, '-c', 'from drift_gate.adapters.cli.runner import run_cli; run_cli()',
      'check', '--base','missing-ref','--json'], cwd=root, text=True, capture_output=True)
    assert result.returncode == 2 and result.stdout == ''


@pytest.mark.parametrize('content', [b'M\0truncated', b'M\0\xff\0', b'R100\0one\0'])
def test_unsupported_or_partial_paths_are_input_errors(content):
    with pytest.raises(GitInputError): _parse_name_status(content)


def test_git_timeout_is_not_an_empty_diff(tmp_path, monkeypatch):
    def timeout(*args, **kwargs): raise subprocess.TimeoutExpired('git', 30)
    monkeypatch.setattr(subprocess, 'check_output', timeout)
    with pytest.raises(GitInputError): GitAdapter(tmp_path).get_changed_files()
