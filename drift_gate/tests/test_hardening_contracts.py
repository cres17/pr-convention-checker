"""Adversarial behavior regressions from the October hardening review."""
import json
import subprocess

import pytest

from drift_gate.adapters.ast.analyzer import enrich_semantic_signals
from drift_gate.adapters.cli.runner import run_cli
from drift_gate.adapters.git.client import GitAdapter
from drift_gate.core.engine import run
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.policy.loader import PolicyLoadError, load_policy_from_text

POLICY = '''rules:
  - id: contract
    when:
      any_changed: ['src/**']
      min_change_intensity: impl-only
    require:
      groups:
        - name: docs
          all_changed: ['spec.md']
    severity: major
gate:
  fail_on_major_count: 1
'''


@pytest.mark.parametrize('policy', ['', 'null', '[]', 'rules: null', 'rules: [null]',
    'rules: [{severity: true}]', 'rulse: []', 'rules: []\nrules: []',
    'gate: {fail_on_major_count: false}', 'gate: {fail_on_major_count: 0}',
    'gate: {fail_on_major_count: -3}', 'gate: {fail_on_major_count: 1.5}',
    'rules: [{id: x, when: {any_changed: src/**}}]',
    POLICY.replace('- name: docs', '- required: true\n          required: false\n          name: docs')])
def test_invalid_policy_never_becomes_an_empty_success(policy):
    with pytest.raises(PolicyLoadError):
        load_policy_from_text(policy)


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.PIPE).decode().strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init')
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src/a.py').write_text('def api(a,\n        b=1,\n):\n    return a\n')
    (tmp_path / '.drift-gate.yml').write_text(POLICY)
    git(tmp_path, 'add', '.')
    git(tmp_path, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'baseline')
    return tmp_path


@pytest.mark.parametrize('argument', ['*extra,', '**options,'])
def test_valid_signature_expansion_is_not_a_comment(repo, argument):
    p = repo / 'src/a.py'
    p.write_text(p.read_text().replace('):', '        ' + argument + '\n):'))
    compile(p.read_text(), '<valid fixture>', 'exec')
    result = run(enrich_semantic_signals(GitAdapter(repo).get_changed_files('HEAD')),
                 policy=load_policy_from_text(POLICY))
    assert result.result == 'fail'
    assert result.violations[0].rule_id == 'contract'


@pytest.mark.parametrize('target', ['docs/a.py', 'tests/a.py', 'elsewhere/a.py'])
def test_source_rename_preserves_protected_origin(repo, target):
    (repo / target).parent.mkdir(parents=True)
    git(repo, 'mv', 'src/a.py', target)
    policy = load_policy_from_text(POLICY + 'ignore_paths: [tests/**]\n')
    result = run(enrich_semantic_signals(GitAdapter(repo).get_changed_files('HEAD')), policy=policy)
    assert result.result == 'fail'


@pytest.mark.parametrize('path', ['docs/a.md', 'tests/a.py'])
def test_explicit_rules_override_docs_test_shortcut(path):
    policy = load_policy_from_text(POLICY.replace('src/**', path).replace('impl-only', 'any'))
    result = run([ChangedFile(path, 'modified', patch='-old\n+new')], policy=policy)
    assert result.result == 'fail' and not result.skip


def test_nested_cli_policy_root_and_fresh_error_artifact(repo, monkeypatch, capsys):
    (repo / 'src/a.py').write_text('VALUE=2\n')
    monkeypatch.chdir(repo / 'src')
    with pytest.raises(SystemExit) as exc:
        run_cli(['check', '--json'])
    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().out)['result'] == 'fail'
    out = repo / 'report.json'
    out.write_text('{"result":"pass"}')
    with pytest.raises(SystemExit) as exc:
        run_cli(['check', '--policy', 'typo.yml', '--out-json', str(out), '--json'])
    assert exc.value.code == 2
    error = json.loads(out.read_text())
    assert error['error']['code'] == 'input_error' and error['execution']['run_id']


def test_comment_context_and_runtime_literal_change(repo):
    from drift_gate.core.classification.intensity import classify_file_intensity
    p = repo / 'src/a.py'
    p.write_text('# real comment\nVALUE=1\n')
    git(repo, 'add', '.')
    git(repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'comment baseline')
    p.write_text('# changed comment\nVALUE=1\n')
    assert classify_file_intensity(GitAdapter(repo).get_changed_files('HEAD')[0]) == 'comment-only'
    file = ChangedFile('src/a.py', 'modified', patch='@@ -2 +2 @@\n-# old\n+# new',
        before_source='message="""\n# old\n"""', after_source='message="""\n# new\n"""')
    assert classify_file_intensity(file) == 'impl-only'
    assert 'before_source' not in file.to_dict()


def test_merge_base_does_not_invent_main_only_deletion(repo):
    initial = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'checkout', '-b', 'ahead')
    (repo / 'src/main_only.py').write_text('VALUE=1')
    git(repo, 'add', '.')
    git(repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'ahead')
    git(repo, 'checkout', '--detach', initial)
    assert any(f.status == 'deleted' for f in GitAdapter(repo).get_changed_files('ahead'))
    assert GitAdapter(repo).get_changed_files('ahead', comparison_mode='merge-base') == []


def test_mcp_strict_result_notification_and_root_boundary(tmp_path, monkeypatch):
    from drift_gate.adapters.mcp import server
    monkeypatch.setitem(server.TOOL_MAP, 'bad', lambda: {'value': float('nan')})
    response = server.handle_request({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'bad'}})
    assert 'error' in response
    assert server.handle_request({'jsonrpc': '2.0', 'method': 'tools/list'}) == {}
    monkeypatch.setattr(server, 'ALLOWED_ROOT', tmp_path)
    response = server.handle_request({'tool': 'drift_gate_history', 'args': {'path': str(tmp_path.parent / 'outside.jsonl')}})
    assert response['ok'] is False and 'outside' in response['error']


def test_review_reads_repository_relative_paths_from_subdirectory(repo, monkeypatch, capsys):
    monkeypatch.chdir(repo / 'src')
    (repo / 'src/a.py').write_text('def api(a):\n    return a\n')
    with pytest.raises(SystemExit) as exc:
        run_cli(['review', '--base', 'HEAD', '--format', 'json'])
    assert exc.value.code in (0, 1)
    assert 'input_error' not in capsys.readouterr().out


@pytest.mark.parametrize('mutation', ['remove', 'severity', 'threshold', 'ignore', 'optional', 'trigger', 'intensity', 'empty'])
def test_trusted_obligations_reject_each_policy_weakening(mutation):
    from copy import deepcopy
    from drift_gate.core.policy.guard import weakening_reasons
    trusted = load_policy_from_text(POLICY)
    candidate = deepcopy(trusted)
    if mutation in ('remove', 'empty'):
        candidate.rules.clear()
    elif mutation == 'severity':
        candidate.rules[0].severity = 'nit'
    elif mutation == 'threshold':
        candidate.gate.fail_on_major_count = 999
    elif mutation == 'ignore':
        candidate.ignore_paths.append('src/**')
    elif mutation == 'optional':
        candidate.rules[0].require.groups[0].required = False
    elif mutation == 'trigger':
        candidate.rules[0].when.any_changed = ['never/**']
    elif mutation == 'intensity':
        candidate.rules[0].when.min_change_intensity = 'signature-change'
    assert weakening_reasons(trusted, candidate)


def test_policy_expansion_and_new_rule_can_preserve_old_obligations():
    from copy import deepcopy
    from drift_gate.core.policy.guard import weakening_reasons
    trusted = load_policy_from_text(POLICY)
    candidate = deepcopy(trusted)
    candidate.rules[0].when.any_changed.append('new-runtime/**')
    added = deepcopy(candidate.rules[0])
    added.id = 'new-rule'
    candidate.rules.append(added)
    assert weakening_reasons(trusted, candidate) == []


def test_remote_cli_does_not_require_a_local_git_checkout(tmp_path, monkeypatch, capsys):
    from drift_gate.adapters.cli import runner
    monkeypatch.chdir(tmp_path)
    (tmp_path / '.drift-gate.yml').write_text(POLICY)
    monkeypatch.setenv('GITHUB_TOKEN', 'fixture-token')
    class Remote:
        def __init__(self, **kwargs):
            pass
        def get_pr_files_and_body(self, number):
            return [ChangedFile('src/a.py', 'modified', patch='-a=1\n+a=2')], ''
        def attach_env_documents(self, number, files, policy):
            return files
    monkeypatch.setattr(runner, 'GitHubAdapter', Remote)
    with pytest.raises(SystemExit) as exc:
        run_cli(['check', '--pr', '1', '--repo', 'fixture/repo', '--json'])
    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().out)['result'] == 'fail'


def test_self_audit_related_files_never_verify_claim_truth():
    from drift_gate.adapters.docs.checklist import parse_checklist_text
    from drift_gate.core.self_audit.matcher import DiffEvidence, match_checklist
    items = parse_checklist_text('- [x] `python_syntax.py` prevents all serialization failures\n')
    data = match_checklist(items, DiffEvidence(changed_files=['drift_gate/core/python_syntax.py',
        'drift_gate/adapters/other.py'])).to_dict()['self_audit']['checklist_items'][0]
    assert data['evidence'] == ['drift_gate/core/python_syntax.py']
    assert data['status'] == 'related-evidence-found'
    assert data['behavior_verified'] is False
