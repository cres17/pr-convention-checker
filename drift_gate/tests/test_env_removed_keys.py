"""Removed environment keys that a sample document still lists (S2).

A key no changed file reads any more is a violation only when nothing else in the repository
uses it. A use in configuration, a bare mention, an unchecked repository or dynamic access is a
warning (gate warn, enforcement review); excluding a key or disabling the check is a policy
weakening.
"""
from hashlib import sha256
import json
import subprocess

import pytest

from drift_gate.adapters.cli.runner import run_cli
from drift_gate.core.engine import run
from drift_gate.core.evaluation.env_references import classify_reference
from drift_gate.core.evaluation.environment import environment_delta
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.policy import policy_identity_dict
from drift_gate.core.policy.guard import weakening_reasons
from drift_gate.core.policy.loader import PolicyLoadError, load_policy_from_dict, load_policy_from_text
from drift_gate.core.policy.validator import validate


def policy(**group_options):
    group = {'name': 'env sample', 'all_changed': ['.env.example'], 'content': 'env-keys', **group_options}
    return load_policy_from_dict({'rules': [{'id': 'env', 'when': {'any_changed': ['src/**']},
                                             'require': {'groups': [group]}, 'severity': 'blocker'}]})


BEFORE = 'import os\nA = os.getenv("LEGACY_TOKEN")\nB = os.getenv("DATABASE_URL")\n'
AFTER = 'import os\nB = os.getenv("DATABASE_URL")\n'
CODE = ChangedFile('src/settings.py', 'modified', patch='@@ -1,3 +1,2 @@\n import os\n-A = os.getenv("LEGACY_TOKEN")\n'
                   ' B = os.getenv("DATABASE_URL")\n', before_source=BEFORE, after_source=AFTER)


def sample(references=None, scan='complete', keys=('DATABASE_URL', 'LEGACY_TOKEN')):
    return ChangedFile('.env.example', 'unchanged', documented_env_keys=list(keys), document_input_state='available',
                       after_source=''.join(f'{k}=\n' for k in keys),
                       env_key_references=references if scan == 'complete' else None, env_reference_scan=scan)


def evaluate(document, rules=None, code=CODE):
    result = run([code, document], policy=rules or policy())
    return result, result.to_dict()


# --- core decision -----------------------------------------------------------------------------------------

def test_delta_reports_keys_no_changed_file_reads_any_more():
    facts = environment_delta([CODE])
    assert facts.removed == {'LEGACY_TOKEN'} and facts.keys == set()
    renamed = ChangedFile('src/settings.py', 'modified', patch='@@\n', before_source=BEFORE,
                          after_source=AFTER + 'C = os.getenv("NEW_TOKEN")\n')
    assert environment_delta([renamed]).removed == {'LEGACY_TOKEN'}
    assert environment_delta([renamed]).keys == {'NEW_TOKEN'}


def test_documented_key_with_no_other_use_is_a_violation():
    result, data = evaluate(sample({'LEGACY_TOKEN': {}}))
    assert result.result == 'fail' and data['enforcement']['action'] == 'block'
    evidence = result.violations[0].unsatisfied_groups[0].evidence
    assert 'removed environment keys still documented: LEGACY_TOKEN' in evidence
    assert 'exclude_removed_keys: [LEGACY_TOKEN]' in evidence and data['advisories'] == []


def test_key_still_read_by_other_code_is_fine():
    result, data = evaluate(sample({'LEGACY_TOKEN': {'code': ['src/worker.py']}}))
    assert result.result == 'pass' and data['advisories'] == [] and data['enforcement']['action'] == 'allow'


@pytest.mark.parametrize('references, scan, phrase', [
    ({'LEGACY_TOKEN': {'config': ['docker-compose.yml']}}, 'complete', 'used in configuration: docker-compose.yml'),
    ({'LEGACY_TOKEN': {'mention': ['notes.txt']}}, 'complete', 'named without a recognised use: notes.txt'),
    (None, 'unavailable: PR API mode does not search the repository tree', 'could not be checked'),
])
def test_unconfirmed_cases_are_warnings_not_failures(references, scan, phrase):
    result, data = evaluate(sample(references, scan))
    assert result.violations == [] and result.result == 'warn'  # the rule is a blocker, yet this never blocks
    assert data['enforcement']['action'] == 'review' and data['enforcement']['advisory_rule_ids'] == ['env']
    [advisory] = data['advisories']
    assert advisory['rule_id'] == 'env' and phrase in advisory['message']
    assert 'Stop checking LEGACY_TOKEN? Add exclude_removed_keys: [LEGACY_TOKEN]' in advisory['message']


def test_dynamic_access_in_the_change_downgrades_absence_to_a_warning():
    dynamic = ChangedFile('src/settings.py', 'modified', patch='@@\n', before_source=BEFORE,
                          after_source=AFTER + 'name = "X"\nC = os.getenv(name)\n')
    result, data = evaluate(sample({'LEGACY_TOKEN': {}}), code=dynamic)
    assert result.violations == [] and 'dynamic environment access' in data['advisories'][0]['message']


def test_excluded_key_and_disabled_check_report_nothing():
    for rules in (policy(exclude_removed_keys=['LEGACY_TOKEN']), policy(check_removed_keys=False)):
        result, data = evaluate(sample({'LEGACY_TOKEN': {}}), rules)
        assert result.result == 'pass' and data['advisories'] == []


def test_key_not_in_the_sample_keeps_the_previous_result():
    result, data = evaluate(sample(keys=('DATABASE_URL',)))
    assert result.result == 'pass' and data['advisories'] == []
    group = data['rule_decisions'][0]['satisfied_groups'][0]
    assert group['verification'] == 'not-applicable' and 'advisories' not in group


def test_new_key_check_still_applies_alongside_removed_keys():
    renamed = ChangedFile('src/settings.py', 'modified', patch='@@\n', before_source=BEFORE,
                          after_source=AFTER + 'C = os.getenv("NEW_TOKEN")\n')
    result, _ = evaluate(sample({'LEGACY_TOKEN': {'code': ['src/worker.py']}}), code=renamed)
    assert result.result == 'fail' and 'missing environment keys: NEW_TOKEN' in result.violations[0].unsatisfied_groups[0].evidence


# --- reference classification (pure) ------------------------------------------------------------------------

@pytest.mark.parametrize('path, text, kind', [
    ('src/worker.py', 'import os\nX = os.environ["LEGACY_TOKEN"]\n', 'code'),
    ('src/worker.py', '# LEGACY_TOKEN was removed\n', 'mention'),
    ('web/app.ts', 'const t = process.env.LEGACY_TOKEN\n', 'code'),
    ('web/app.ts', 'const t = import.meta.env.LEGACY_TOKEN\n', 'code'),
    ('web/app.ts', '// LEGACY_TOKEN\n', 'mention'),
    ('docker-compose.yml', 'services:\n  api:\n    environment:\n      - LEGACY_TOKEN=abc\n', 'config'),
    ('compose.yaml', 'services:\n  api:\n    environment:\n      LEGACY_TOKEN: abc\n', 'config'),
    ('docker-compose.yml', 'services:\n  api:\n    image: x:${LEGACY_TOKEN:-1}\n', 'config'),
    ('docker-compose.yml', '# LEGACY_TOKEN: old\nservices: {}\n', 'mention'),
    ('Dockerfile', 'FROM python\nENV LEGACY_TOKEN=1\n', 'config'),
    ('deploy/run.sh', 'export LEGACY_TOKEN\n', 'config'),
    ('deploy/run.sh', 'echo "$LEGACY_TOKEN"\n', 'config'),
    ('.github/workflows/ci.yml', 'env:\n  T: ${{ secrets.LEGACY_TOKEN }}\n', 'config'),
    ('k8s/deploy.yaml', 'env:\n  - name: LEGACY_TOKEN\n    valueFrom: {}\n', 'config'),
    ('.env.production', 'LEGACY_TOKEN=x\n', 'config'),
    ('README.md', 'Set LEGACY_TOKEN before running.\n', 'mention'),
    ('main.go', 'os.Getenv("LEGACY_TOKEN")\n', 'mention'),
    ('src/worker.py', 'import os\nX = os.environ["OTHER_LEGACY_TOKEN"]\n', None),
])
def test_reference_kinds(path, text, kind):
    assert classify_reference(path, text, 'LEGACY_TOKEN') == kind


# --- policy options -----------------------------------------------------------------------------------------

def test_options_validate_and_keep_identity_of_existing_policies():
    assert 'check_removed_keys' not in json.dumps(policy_identity_dict(policy()))
    assert validate(policy(exclude_removed_keys=['LEGACY_TOKEN'])).errors == []
    with pytest.raises(PolicyLoadError, match='apply only to env-keys'):
        load_policy_from_dict({'rules': [{'id': 'r', 'when': {'any_changed': ['src/**']}, 'require': {'groups': [
            {'name': 'docs', 'any_changed': ['docs/a.md'], 'check_removed_keys': False}]}}]})
    with pytest.raises(PolicyLoadError, match='environment key names'):
        policy(exclude_removed_keys=['lower'])


def test_turning_the_check_off_is_a_policy_weakening():
    trusted = policy()
    assert weakening_reasons(trusted, policy(check_removed_keys=False)) == [
        'env: disabled removed-key check in group env sample']
    assert weakening_reasons(trusted, policy(exclude_removed_keys=['LEGACY_TOKEN'])) == [
        'env: excluded removed keys in group env sample']
    assert weakening_reasons(policy(exclude_removed_keys=['LEGACY_TOKEN']), trusted) == []


# --- local and immutable collection -------------------------------------------------------------------------

POLICY = '''rules:
  - id: env
    when:
      any_changed: ["src/**"]
    require:
      groups:
        - name: env sample
          all_changed: [".env.example"]
          content: env-keys
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
def repo(tmp_path, monkeypatch):
    git(tmp_path, 'init', '-q', '-b', 'main')
    (tmp_path / '.drift-gate.yml').write_text(POLICY, encoding='utf-8', newline='\n')
    (tmp_path / '.env.example').write_text('DATABASE_URL=\nLEGACY_TOKEN=\n', encoding='utf-8', newline='\n')
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src/settings.py').write_text(BEFORE, encoding='utf-8', newline='\n')
    (tmp_path / 'src/worker.py').write_text('import os\nT = os.getenv("LEGACY_TOKEN")\n', encoding='utf-8', newline='\n')
    commit(tmp_path, 'base')
    monkeypatch.chdir(tmp_path)
    return tmp_path


def check(argv, capsys):
    with pytest.raises(SystemExit) as done:
        run_cli(['check', *argv, '--json'])
    return done.value.code, json.loads(capsys.readouterr().out)


def test_local_check_follows_the_repository(repo, capsys):
    (repo / 'src/settings.py').write_text(AFTER, encoding='utf-8', newline='\n')
    code, result = check(['--base', 'HEAD'], capsys)
    assert code == 0 and result['result'] == 'pass'  # src/worker.py still reads it
    (repo / 'src/worker.py').write_text('import os\n', encoding='utf-8', newline='\n')
    code, result = check(['--base', 'HEAD'], capsys)
    assert code == 1 and 'LEGACY_TOKEN' in result['violations'][0]['unsatisfied_groups'][0]['evidence']
    (repo / 'docker-compose.yml').write_text('services:\n  api:\n    environment:\n      - LEGACY_TOKEN=x\n',
                                             encoding='utf-8', newline='\n')  # untracked files are searched too
    code, result = check(['--base', 'HEAD'], capsys)
    assert code == 0 and result['result'] == 'warn' and result['enforcement']['action'] == 'review'
    assert 'docker-compose.yml' in result['advisories'][0]['message']


def test_immutable_check_searches_the_head_tree(repo, capsys):
    base = git(repo, 'rev-parse', 'HEAD')
    (repo / 'src/settings.py').write_text(AFTER, encoding='utf-8', newline='\n')
    (repo / 'src/worker.py').write_text('import os\n', encoding='utf-8', newline='\n')
    head = commit(repo, 'drop the token')
    (repo / 'src/worker.py').write_text(BEFORE, encoding='utf-8', newline='\n')  # working tree is not the subject
    pin = sha256(POLICY.encode()).hexdigest()
    code, result = check(['--base', base, '--head', head, '--trusted-policy-ref', base,
                          '--trusted-policy-sha256', pin], capsys)
    assert code == 1 and result['violations'][0]['rule_id'] == 'env'
    assert 'removed environment keys still documented: LEGACY_TOKEN' in json.dumps(result['violations'])


def test_unchanged_capture_identity_without_a_reference_scan():
    from datetime import date
    from drift_gate.adapters.snapshot import capture_inspection
    from drift_gate.core.models.evaluation_context import EvaluationContext
    rules = load_policy_from_text(POLICY)
    snapshot = capture_inspection(changed_files=[CODE], policy=rules, context=EvaluationContext(date(2026, 10, 18)))
    assert b'env_reference_scan' not in snapshot.payload and b'env_key_references' not in snapshot.payload


# --- rule activation for a removal-only change --------------------------------------------------------------

def _activation_policy(when):
    return load_policy_from_dict({'rules': [{'id': 'env', 'when': {'any_changed': ['src/**'], **when},
        'require': {'groups': [{'name': 'env sample', 'all_changed': ['.env.example'], 'content': 'env-keys'}]},
        'severity': 'blocker'}]})


@pytest.mark.parametrize('when', [
    {'min_change_intensity': 'config-key-added'},
    {'trigger': {'family': 'env-key', 'predicate': 'key-removed', 'scope': 'selected-modules', 'on_unknown': 'review'}},
    {'trigger': {'family': 'env-key', 'predicate': 'key-changed', 'scope': 'selected-modules', 'on_unknown': 'review'}},
])
def test_removal_only_change_activates_the_rule(when):
    result, _ = evaluate(sample({'LEGACY_TOKEN': {}}), _activation_policy(when))
    assert result.result == 'fail' and result.violations[0].rule_id == 'env'


def test_key_added_trigger_still_ignores_a_removal_only_change():
    when = {'trigger': {'family': 'env-key', 'predicate': 'key-added', 'scope': 'selected-modules', 'on_unknown': 'review'}}
    result, data = evaluate(sample({'LEGACY_TOKEN': {}}), _activation_policy(when))
    assert result.result == 'pass' and data['rule_decisions'][0]['status'] == 'unmatched'


def test_disabled_check_keeps_a_removal_below_the_legacy_threshold():
    rules = load_policy_from_dict({'rules': [{'id': 'env', 'when': {'any_changed': ['src/**'],
        'min_change_intensity': 'config-key-added'}, 'require': {'groups': [{'name': 'env sample',
        'all_changed': ['.env.example'], 'content': 'env-keys', 'check_removed_keys': False}]}, 'severity': 'blocker'}]})
    result, data = evaluate(sample({'LEGACY_TOKEN': {}}), rules)
    assert result.result == 'pass' and data['rule_decisions'][0]['status'] == 'unmatched'


def test_focused_preset_detects_a_removed_key():
    from drift_gate.adapters.cli.presets import POLICY_PRESETS
    rules = load_policy_from_text(POLICY_PRESETS['focused-python'])
    code = ChangedFile('src/config/settings.py', 'modified', patch=CODE.patch, before_source=BEFORE, after_source=AFTER)
    result = run([code, sample({'LEGACY_TOKEN': {}})], policy=rules)
    assert [v.rule_id for v in result.violations] == ['env-sample-content']
