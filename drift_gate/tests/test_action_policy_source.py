"""The Action judges a pull request by the base policy, not by the policy the PR can edit."""
import pytest

from drift_gate.adapters.github_action import runner as action
from drift_gate.adapters.github_action.policy_source import select_policy
from drift_gate.core.policy.loader import PolicyLoadError

STRICT = """rules:
  - id: api-sync
    when: {any_changed: ["src/api/**"]}
    require: {groups: [{name: docs, any_changed: ["docs/api.md"]}]}
    severity: blocker
    message: api changed
gate: {fail_on_blocker: true, fail_on_major_count: 2}
"""
WEAK = """rules:
  - id: other
    when: {any_changed: ["src/other/**"]}
    require: {groups: [{name: docs, any_changed: ["docs/other.md"]}]}
    severity: minor
    message: other
gate: {fail_on_blocker: true, fail_on_major_count: 2}
"""


class FakeGitHub:
    def __init__(self, files):
        self.files, self.calls = files, []

    def get_file_text(self, path, ref):
        self.calls.append((path, ref))
        return self.files.get(path)


def workspace(tmp_path, text):
    if text is not None:
        (tmp_path / '.drift-gate.yml').write_text(text)
    return str(tmp_path)


def test_base_policy_is_used_even_when_the_pr_removes_the_rule(tmp_path):
    gh = FakeGitHub({'.drift-gate.yml': STRICT})
    selected = select_policy(gh, '.drift-gate.yml', workspace(tmp_path, WEAK), 'base', 'b' * 40)
    assert [r.id for r in selected.policy.rules] == ['api-sync']
    assert selected.source == STRICT and selected.origin == 'base'
    assert any('removed trusted rule' in reason for reason in selected.weakening)
    assert gh.calls == [('.drift-gate.yml', 'b' * 40)]


def test_unchanged_policy_has_no_notes(tmp_path):
    selected = select_policy(FakeGitHub({'.drift-gate.yml': STRICT}), '.drift-gate.yml', workspace(tmp_path, STRICT), 'base', 'b' * 40)
    assert selected.origin == 'base' and selected.notes == [] and selected.weakening == []


def test_policy_deleted_by_the_pr_is_reported_and_base_policy_still_applies(tmp_path):
    selected = select_policy(FakeGitHub({'.drift-gate.yml': STRICT}), '.drift-gate.yml', workspace(tmp_path, None), 'base', 'b' * 40)
    assert [r.id for r in selected.policy.rules] == ['api-sync']
    assert selected.weakening == ['policy file removed by this pull request']


def test_first_policy_in_a_pr_falls_back_to_the_pr_policy_and_says_so(tmp_path):
    selected = select_policy(FakeGitHub({}), '.drift-gate.yml', workspace(tmp_path, STRICT), 'base', 'b' * 40)
    assert selected.origin == 'workspace-no-base-policy'
    assert any('cannot protect' in note for note in selected.notes)


def test_workspace_mode_never_calls_the_api_and_warns(tmp_path):
    gh = FakeGitHub({'.drift-gate.yml': STRICT})
    selected = select_policy(gh, '.drift-gate.yml', workspace(tmp_path, WEAK), 'workspace', 'b' * 40)
    assert [r.id for r in selected.policy.rules] == ['other'] and gh.calls == [] and selected.notes


def test_invalid_base_policy_fails_closed(tmp_path):
    with pytest.raises(PolicyLoadError):
        select_policy(FakeGitHub({'.drift-gate.yml': 'rules: [oops'}), '.drift-gate.yml', workspace(tmp_path, STRICT), 'base', 'b' * 40)


def test_policy_outside_the_workspace_and_unknown_modes_are_rejected(tmp_path):
    outside = tmp_path / 'ws'
    outside.mkdir()
    (tmp_path / 'p.yml').write_text(STRICT)
    with pytest.raises(ValueError, match='inside the workspace'):
        select_policy(FakeGitHub({}), str(tmp_path / 'p.yml'), str(outside), 'base', 'b' * 40)
    with pytest.raises(ValueError, match='POLICY_SOURCE'):
        select_policy(FakeGitHub({}), '.drift-gate.yml', workspace(tmp_path, STRICT), 'head', 'b' * 40)


def test_missing_base_commit_is_an_error(tmp_path):
    with pytest.raises(RuntimeError, match='base commit'):
        select_policy(FakeGitHub({}), '.drift-gate.yml', workspace(tmp_path, STRICT), 'base', None)


def test_output_values_with_line_breaks_cannot_set_other_outputs(tmp_path, monkeypatch):
    out = tmp_path / 'out'
    monkeypatch.setenv('GITHUB_OUTPUT', str(out))
    action._write_github_output({'policy_error': "bad rule\nresult=pass", 'run_id': 'r1'})
    lines = out.read_text().splitlines()
    assert lines[0].startswith('policy_error<<ghadelim_') and lines[-1] == 'run_id=r1'
    delimiter = lines[0].split('<<', 1)[1]
    # The injected line stays inside the delimited value; it is the closing delimiter, not a newline, that ends it.
    assert lines[1:3] == ['bad rule', 'result=pass'] and lines[3] == delimiter
    assert [line for line in lines if '=' in line and '<<' not in line and line != 'result=pass'] == ['run_id=r1']
