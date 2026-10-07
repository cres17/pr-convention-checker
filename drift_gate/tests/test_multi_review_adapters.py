"""Cross-adapter inspection contracts from the independent multi-review."""
import hashlib
import json
import subprocess
import sys

import pytest

from drift_gate.adapters.mcp import tools
from drift_gate.adapters.policy_loader import load_policy, require_check_policy
from drift_gate.core.policy.loader import PolicyLoadError


POLICY = """rules:
  - id: docs-required
    when:
      any_changed: [src/**]
    require:
      groups:
        - name: docs
          any_changed: [docs/**]
    severity: blocker
"""


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def repository(tmp_path):
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.email', 'test@example.invalid')
    git(tmp_path, 'config', 'user.name', 'Test')
    (tmp_path / '.drift-gate.yml').write_text(POLICY, encoding='utf-8')
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src/old.py').write_text('value = 1\n', encoding='utf-8')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-qm', 'baseline')
    return tmp_path


@pytest.mark.parametrize('name,extra', [
    ('drift_gate_check_local', {}),
    ('drift_gate_get_evidence', {}),
    ('drift_gate_prepare_fix_plan', {}),
    ('drift_gate_check_pr', {'pr_number': 1, 'repo': 'owner/repo', 'token': 'secret'}),
])
def test_empty_policy_rejected_before_any_inspection(name, extra, monkeypatch, tmp_path):
    path = tmp_path / '.drift-gate.yml'
    path.write_text('rules: []\n', encoding='utf-8')
    monkeypatch.setattr(tools.GitAdapter, 'get_changed_files',
                        lambda *a, **k: pytest.fail('empty policy must not inspect Git'))
    monkeypatch.setattr(tools.GitHubAdapter, 'get_pr_files_and_body',
                        lambda *a, **k: pytest.fail('empty policy must not call GitHub'))
    with pytest.raises(PolicyLoadError, match='at least one configured rule'):
        getattr(tools, name)(policy_path=str(path), **extra)
    assert tools.drift_gate_list_rules(str(path)) == []
    assert load_policy(path).rules == []


def test_action_rejects_empty_policy_without_success_report(monkeypatch, tmp_path):
    from drift_gate.adapters.github_action import runner
    path = tmp_path / '.drift-gate.yml'
    path.write_text('rules: []\n', encoding='utf-8')
    for name, value in {'GITHUB_TOKEN': 'test', 'REPO': 'owner/repo', 'PR_NUMBER': '1',
                        'POLICY_FILE': str(path), 'RUNNER_TEMP': str(tmp_path),
                        'POST_COMMENT': 'false', 'GITHUB_OUTPUT': str(tmp_path / 'outputs')}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(runner.GitHubAdapter, 'get_pr_files_and_body', lambda *a: ([], ''))
    monkeypatch.setattr(runner, 'run', lambda **k: pytest.fail('engine must not run'))
    with pytest.raises(PolicyLoadError, match='at least one configured rule'):
        runner.main()
    output = (tmp_path / 'outputs').read_text(encoding='utf-8')
    assert 'result=pass' not in output
    assert 'policy_error=' in output
    assert not (tmp_path / 'drift_gate_report.json').exists()


def test_configuration_load_and_check_validation_have_distinct_contracts(tmp_path):
    path = tmp_path / '.drift-gate.yml'
    path.write_text(POLICY, encoding='utf-8')
    policy = load_policy(path)
    assert require_check_policy(policy) is policy


@pytest.mark.parametrize('mode,budget', [('full', 1200), ('compact', 1200), ('compact', 1)])
def test_real_stdio_mcp_preserves_untracked_warning_and_provenance(tmp_path, mode, budget):
    root = repository(tmp_path)
    untracked = [f'src/new{i:02}.py' for i in range(30)]
    for path in untracked:
        (root / path).write_text('new = 1\n', encoding='utf-8')
    request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
        'name': 'drift_gate_check_local', 'arguments': {'mode': mode, 'token_budget': budget}}}
    process = subprocess.run([sys.executable, '-m', 'drift_gate.adapters.mcp.server',
                              '--repo', str(root)], input=json.dumps(request) + '\n',
                             capture_output=True, text=True, timeout=30)
    assert process.returncode == 0, process.stderr
    response = json.loads(process.stdout)
    result = json.loads(response['result']['content'][0]['text'])
    assert result['result'] == 'pass'  # Untracked input is intentionally excluded.
    execution = result['execution']
    assert execution['untracked_skipped_count'] == len(untracked)
    assert execution['untracked_skipped']
    if mode == 'full' or budget >= 1200:
        assert execution['untracked_skipped'] == untracked
    else:
        assert execution['untracked_skipped'] == untracked[:5]
        assert execution['untracked_skipped_truncated'] is True
    assert execution['head'] == git(root, 'rev-parse', 'HEAD')
    assert execution['requested_base'] == 'HEAD'
    assert execution['resolved_base'] == execution['head']
    assert execution['snapshot_sha256'] == hashlib.sha256(b'').hexdigest()
    assert execution['policy_sha256'] == hashlib.sha256(POLICY.encode()).hexdigest()
    assert len(execution['run_id']) == 32
    assert execution['status'] == 'success'


@pytest.mark.parametrize('mode', ['compact', 'full'])
def test_real_stdio_mcp_empty_policy_is_tool_error(tmp_path, mode):
    root = repository(tmp_path)
    (root / '.drift-gate.yml').write_text('rules: []\n', encoding='utf-8')
    request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
        'name': 'drift_gate_check_local', 'arguments': {'mode': mode}}}
    process = subprocess.run([sys.executable, '-m', 'drift_gate.adapters.mcp.server',
                              '--repo', str(root)], input=json.dumps(request) + '\n',
                             capture_output=True, text=True, timeout=30)
    assert process.returncode == 0, process.stderr
    response = json.loads(process.stdout)
    assert 'result' not in response
    assert 'at least one configured rule' in response['error']['message']
