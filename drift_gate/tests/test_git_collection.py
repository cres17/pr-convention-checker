"""Actual Git inputs, not pre-decoded path mocks."""
import os
import json
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


@pytest.mark.parametrize('command', ['check', 'review', 'self-audit'])
@pytest.mark.parametrize('in_repository', [True, False])
def test_cli_bad_base_exits_as_input_error(tmp_path, command, in_repository):
    root = repository(tmp_path) if in_repository else tmp_path
    (root / 'checklist.md').write_text('# Empty checklist\n', encoding='utf-8')
    flags = ['--format', 'json', '--fail-on', 'low'] if command == 'review' else ['--json']
    if command == 'self-audit': flags += ['--checklist', 'checklist.md']
    result = subprocess.run([sys.executable, '-c', 'from drift_gate.adapters.cli.runner import run_cli; run_cli()',
      command, '--base', 'missing-ref', *flags], cwd=root, text=True, encoding='utf-8', capture_output=True, timeout=20)
    assert result.returncode == 2
    assert json.loads(result.stdout)['error']['code'] == 'input_error'


@pytest.mark.parametrize('command', ['review', 'self-audit'])
def test_cli_timeout_is_an_error_and_empty_input_is_structured(tmp_path, monkeypatch, capsys, command):
    from drift_gate.adapters.cli.runner import run_cli
    root = repository(tmp_path)
    monkeypatch.chdir(root)
    (root / 'checklist.md').write_text('# Empty checklist\n', encoding='utf-8')
    flags = ['--format', 'json'] if command == 'review' else ['--json', '--checklist', 'checklist.md']
    with pytest.raises(SystemExit) as done:
        run_cli([command, '--base', 'HEAD', *flags])
    assert done.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert 'error' not in payload
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('git', 30)
    monkeypatch.setattr(subprocess, 'check_output', timeout)
    with pytest.raises(SystemExit) as failed:
        run_cli([command, '--base', 'HEAD', *flags])
    assert failed.value.code == 2
    assert json.loads(capsys.readouterr().out)['error']['code'] == 'input_error'


def test_review_uses_collected_patches_and_rejects_unreadable_source(tmp_path, monkeypatch, capsys):
    from pathlib import Path
    from drift_gate.adapters.cli.runner import run_cli
    root = repository(tmp_path)
    source = root / 'code.py'
    source.write_text('def example():\n    return 1\n', encoding='utf-8')
    git(root, 'add', '.')
    monkeypatch.chdir(root)
    original = subprocess.check_output
    def bounded_git(args, **kwargs):
        assert args[:2] == ['git', '--literal-pathspecs']
        assert kwargs['timeout'] == 30
        return original(args, **kwargs)
    monkeypatch.setattr(subprocess, 'check_output', bounded_git)
    with pytest.raises(SystemExit) as done:
        run_cli(['review', '--base', 'HEAD', '--format', 'json'])
    assert done.value.code == 0
    assert json.loads(capsys.readouterr().out)['review']['files_reviewed'] == ['code.py']
    original_read = Path.read_text
    def unreadable(path, *args, **kwargs):
        if path.name == 'code.py': raise PermissionError('fixture')
        return original_read(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', unreadable)
    with pytest.raises(SystemExit) as failed:
        run_cli(['review', '--base', 'HEAD', '--format', 'json'])
    assert failed.value.code == 2
    assert json.loads(capsys.readouterr().out)['error']['code'] == 'input_error'


@pytest.mark.parametrize('content', [b'M\0truncated', b'M\0\xff\0', b'R100\0one\0'])
def test_unsupported_or_partial_paths_are_input_errors(content):
    with pytest.raises(GitInputError): _parse_name_status(content)


def test_git_timeout_is_not_an_empty_diff(tmp_path, monkeypatch):
    def timeout(*args, **kwargs): raise subprocess.TimeoutExpired('git', 30)
    monkeypatch.setattr(subprocess, 'check_output', timeout)
    with pytest.raises(GitInputError): GitAdapter(tmp_path).get_changed_files()
