"""Independent counterexamples and controls from the multi-party review."""
from copy import deepcopy
from itertools import product
import subprocess

import pytest

from drift_gate.adapters.ast.analyzer import enrich_semantic_signals
from drift_gate.adapters.git import client
from drift_gate.core.classification.intensity import classify_file_intensity
from drift_gate.core.engine import run
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.patch_lines import changed_lines
from drift_gate.core.policy.guard import weakening_reasons
from drift_gate.core.policy.loader import load_policy_from_dict


def policy_data():
    return {'rules': [{'id': 'contract', 'when': {'any_changed': ['src/**'],
                       'min_change_intensity': 'impl-only'},
                      'require': {'groups': [{'name': 'API', 'all_changed': ['docs/api.md']}]},
                      'severity': 'major'}],
            'gate': {'fail_on_blocker': True, 'fail_on_major_count': 1}}


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.PIPE)


def commit(root):
    git(root, 'add', '.')
    git(root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
        'commit', '-m', 'fixture')


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init')
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src/a.py').write_text('def record():\n    return 1\n\n# before\n', encoding='utf-8')
    commit(tmp_path)
    return tmp_path


@pytest.mark.parametrize('expression', ['++record()', '--record()'])
@pytest.mark.parametrize('operation', ['add', 'delete'])
def test_header_like_expressions_in_real_git_still_trigger_rule(repo, expression, operation):
    source = repo / 'src/a.py'
    baseline = source.read_text(encoding='utf-8')
    if operation == 'delete':
        source.write_text(baseline + expression + '\n', encoding='utf-8')
        commit(repo)
    source.write_text(baseline.replace('# before', '# after') +
                      (expression + '\n' if operation == 'add' else ''), encoding='utf-8')
    compile(source.read_text(encoding='utf-8'), '<valid Python>', 'exec')
    files = client.GitAdapter(repo).get_changed_files('HEAD')
    assert ('+' if operation == 'add' else '-', expression) in changed_lines(files[0], code_only=True)
    assert run(enrich_semantic_signals(files), policy=load_policy_from_dict(policy_data())).result == 'fail'


def test_headers_are_skipped_but_multiple_hunk_code_is_preserved():
    file = ChangedFile('src/a.py', 'modified', patch=(
        'diff --git a/src/a.py b/src/a.py\nindex 111..222 100644\n'
        '--- a/src/a.py\n+++ b/src/a.py\n'
        '@@ -1 +1 @@\n---record()\n+++record()\n'
        '@@ -10 +10 @@\n---other()\n+++other()\n'))
    assert changed_lines(file) == [('-', '--record()'), ('+', '++record()'),
                                   ('-', '--other()'), ('+', '++other()')]


def test_actual_comment_changes_remain_comment_only(repo):
    source = repo / 'src/a.py'
    source.write_text(source.read_text(encoding='utf-8').replace('# before', '# after'), encoding='utf-8')
    file = client.GitAdapter(repo).get_changed_files('HEAD')[0]
    assert classify_file_intensity(file) == 'comment-only'
    assert run([file], policy=load_policy_from_dict(policy_data())).result == 'pass'


@pytest.mark.parametrize('mutation', ['tracked', 'untracked', 'head'])
def test_collection_rejects_changes_after_name_list(repo, monkeypatch, mutation):
    original = client._git
    mutated = False

    def racing_git(args, cwd):
        nonlocal mutated
        value = original(args, cwd)
        if '--name-status' in args and not mutated:
            mutated = True
            if mutation == 'tracked':
                source = repo / 'src/a.py'
                source.write_text(source.read_text(encoding='utf-8') + 'record()\n', encoding='utf-8')
            elif mutation == 'untracked':
                (repo / 'src/new.py').write_text('VALUE = 1\n', encoding='utf-8')
            else:
                git(repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                    'commit', '--allow-empty', '-m', 'concurrent commit')
        return value

    monkeypatch.setattr(client, '_git', racing_git)
    with pytest.raises(client.GitInputError, match='changed during collection'):
        client.GitAdapter(repo).get_changed_files('HEAD')
    monkeypatch.setattr(client, '_git', original)
    adapter = client.GitAdapter(repo)
    files = adapter.get_changed_files('HEAD')
    if mutation == 'tracked':
        assert run(enrich_semantic_signals(files), policy=load_policy_from_dict(policy_data())).result == 'fail'
    elif mutation == 'untracked':
        assert files == [] and adapter.provenance['untracked_skipped'] == ['src/new.py']
    else:
        assert files == [] and adapter.provenance['head'] == git(repo, 'rev-parse', 'HEAD').decode().strip()


def test_conditional_group_obligations_cannot_be_replaced_by_code_paths():
    raw = policy_data()
    rule = raw['rules'][0]
    rule['require']['groups'][0]['required'] = False
    rule['require']['cross_file'] = [{'name': 'api-sync', 'when_any_changed': ['src/**'],
                                     'require_groups': ['API']}]
    trusted = load_policy_from_dict(raw)
    assert weakening_reasons(trusted, deepcopy(trusted)) == []
    candidate = deepcopy(trusted)
    candidate.rules[0].require.groups[0].all_changed = ['src/**']
    files = [ChangedFile('src/a.py', 'modified', patch='@@ -1 +1 @@\n-a=1\n+a=2')]
    assert run(files, policy=trusted).result == 'fail'
    assert run(files, policy=candidate).result == 'pass'
    assert any('weakened group API' in reason for reason in weakening_reasons(trusted, candidate))
    strengthened = deepcopy(trusted)
    strengthened.rules[0].require.groups[0].required = True
    assert weakening_reasons(trusted, strengthened) == []


def test_unreferenced_optional_groups_do_not_become_required_by_guard():
    raw = policy_data()
    raw['rules'][0]['require']['groups'][0]['required'] = False
    trusted = load_policy_from_dict(raw)
    candidate = deepcopy(trusted)
    candidate.rules[0].require.groups[0].all_changed = ['src/**']
    assert weakening_reasons(trusted, candidate) == []


def test_accepted_severity_and_gate_changes_preserve_decision_for_violation_subsets():
    """Check major aggregation as well as isolated severity promotion."""
    rank = {'pass': 0, 'warn': 1, 'fail': 2}
    for old_severity, new_severity, old_blocker, new_blocker, old_count, new_count in product(
        ['nit', 'minor', 'major', 'blocker'], ['nit', 'minor', 'major', 'blocker'],
        [False, True], [False, True], [1, 2], [1, 2]
    ):
        raw = policy_data()
        raw['rules'][0]['severity'] = old_severity
        raw['rules'][0]['when']['any_changed'] = ['src/a.py']
        second = deepcopy(raw['rules'][0])
        second['id'] = 'second'
        second['when']['any_changed'] = ['src/b.py']
        second['severity'] = 'major'
        raw['rules'].append(second)
        raw['gate'] = {'fail_on_blocker': old_blocker, 'fail_on_major_count': old_count}
        trusted = load_policy_from_dict(raw)
        candidate = deepcopy(trusted)
        candidate.rules[0].severity = new_severity
        candidate.gate.fail_on_blocker = new_blocker
        candidate.gate.fail_on_major_count = new_count
        if weakening_reasons(trusted, candidate):
            continue
        for paths in [('a',), ('b',), ('a', 'b')]:
            files = [ChangedFile(f'src/{name}.py', 'modified', patch='@@ -1 +1 @@\n-a=1\n+a=2')
                     for name in paths]
            before, after = run(files, policy=trusted), run(files, policy=candidate)
            assert rank[after.result] >= rank[before.result], (old_severity, new_severity,
                old_blocker, new_blocker, old_count, new_count, paths)


@pytest.mark.parametrize('severity', ['major', 'minor'])
def test_disabled_blocker_cannot_replace_a_warn_or_fail(severity):
    raw = policy_data()
    raw['rules'][0]['severity'] = severity
    raw['gate']['fail_on_blocker'] = False
    trusted = load_policy_from_dict(raw)
    candidate = deepcopy(trusted)
    candidate.rules[0].severity = 'blocker'
    assert any('disabled' in reason for reason in weakening_reasons(trusted, candidate))
    candidate.gate.fail_on_blocker = True
    assert weakening_reasons(trusted, candidate) == []
