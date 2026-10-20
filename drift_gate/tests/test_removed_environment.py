"""Controlled removed-key examples; these do not measure real PR accuracy."""
import json
import subprocess
from dataclasses import replace

import pytest

from drift_gate.adapters.inspection import inspect_snapshot
from drift_gate.adapters.mcp.tools import _compact_result, drift_gate_check_local
from drift_gate.adapters.removed_key_usage import attach_local_usage, collect_usage
from drift_gate.core.engine import run
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.policy.guard import weakening_reasons
from drift_gate.core.policy.loader import PolicyLoadError, load_policy_from_dict
from drift_gate.desktop.service import scan_repository
from drift_gate.reporters.html import HtmlReporter
from drift_gate.reporters.markdown import MarkdownReporter

OLD = "import os\nvalue = os.getenv('LEGACY_TOKEN')\n"
NEW = "import os\nvalue = None\n"


def policy(**options):
    return load_policy_from_dict({'rules': [{'id': 'env', 'severity': 'blocker',
        'when': {'any_changed': ['src/**']}, 'require': {'groups': [
            {'name': 'Environment', 'any_changed': ['.env.example'], 'content': 'env-keys'}]}}], **options})


def files(state=None):
    usage = None if state is None else {'LEGACY_TOKEN': {'state': state, 'paths': ['runtime.sh'] if state in {'config', 'mention', 'code'} else []}}
    return [ChangedFile('src/settings.py', 'modified', patch="-value = os.getenv('LEGACY_TOKEN')\n+value = None\n",
                        before_source=OLD, after_source=NEW, env_key_usage=usage),
            ChangedFile('.env.example', 'unchanged', documented_env_keys=['LEGACY_TOKEN'], document_input_state='available')]


@pytest.mark.parametrize('state,result,action', [('absent', 'fail', 'block'), ('code', 'pass', 'allow'),
    ('config', 'warn', 'review'), ('mention', 'warn', 'review'), ('incomplete', 'warn', 'review'), (None, 'warn', 'review')])
def test_removed_key_truth_table(state, result, action):
    evaluated = run(files(state), policy=policy())
    assert evaluated.result == result
    assert evaluated.to_dict()['enforcement']['action'] == action
    assert bool(evaluated.advisories) == (result == 'warn')
    assert bool(evaluated.violations) == (result == 'fail')
    text = json.dumps(evaluated.to_dict(), ensure_ascii=False)
    if result != 'pass':
        assert 'exclude_removed_keys: [LEGACY_TOKEN]' in text and 'check_removed_keys: false' in text


def test_warn_never_hides_an_independent_added_key_failure():
    inputs = files('config')
    inputs[0] = replace(inputs[0], after_source=NEW+"other = os.getenv('NEW_TOKEN')\n", patch=inputs[0].patch+"+other = os.getenv('NEW_TOKEN')\n")
    evaluated = run(inputs, policy=policy())
    assert evaluated.result == 'fail' and evaluated.advisories


@pytest.mark.parametrize('options', [{'check_removed_keys': False}, {'exclude_removed_keys': ['LEGACY_TOKEN']}])
def test_options_disable_only_the_removed_key_duty_and_are_weakening(options):
    configured = policy(**options)
    assert run(files('absent'), policy=configured).result == 'pass'
    assert weakening_reasons(policy(), configured)
    assert not weakening_reasons(configured, policy())


@pytest.mark.parametrize('options', [{'check_removed_keys': 'false'}, {'exclude_removed_keys': 'TOKEN'},
    {'exclude_removed_keys': ['*']}, {'exclude_removed_keys': ['bad-key']}, {'check_removed_keys': 0}])
def test_policy_options_are_strict(options):
    with pytest.raises(PolicyLoadError):
        policy(**options)


def test_removed_docs_and_source_moves_have_no_stale_key_duty():
    inputs = files('absent')
    inputs[1] = replace(inputs[1], documented_env_keys=[], status='deleted')
    assert run(inputs, policy=policy()).result == 'pass'
    inputs = files('code')
    assert run(inputs, policy=policy()).result == 'pass'


def test_patch_only_and_missing_document_inputs_warn_even_with_default_unverified_fail():
    inputs = files('absent')
    inputs[0] = replace(inputs[0], before_source=None, after_source=None)
    assert run(inputs, policy=policy()).result == 'warn'
    inputs = files('absent')
    inputs[1] = replace(inputs[1], documented_env_keys=None, document_input_state='unavailable')
    assert run(inputs, policy=policy()).result == 'warn'


def test_removed_keys_bypass_the_added_key_intensity_threshold():
    configured = policy()
    configured.rules[0].when.min_change_intensity = 'config-key-added'
    assert run(files('absent'), policy=configured).result == 'fail'


@pytest.mark.parametrize('path,text', [
    ('docker-compose.yml', 'services:\n  web:\n    environment:\n      LEGACY_TOKEN: value\n'),
    ('docker-compose.prod.yml', 'services:\n  web:\n    environment:\n      - LEGACY_TOKEN=value\n'),
    ('docker-compose.yaml', 'services:\n  web:\n    image: "${LEGACY_TOKEN:-default}"\n'),
    ('Dockerfile', 'ARG LEGACY_TOKEN\n'), ('Dockerfile.dev', 'ENV LEGACY_TOKEN=value\n'),
    ('Dockerfile', 'RUN echo "$LEGACY_TOKEN"\n'),
    ('launch.sh', 'export LEGACY_TOKEN\n'), ('launch.bash', 'LEGACY_TOKEN=foo\n'), ('launch.zsh', 'echo "${LEGACY_TOKEN}"\n'),
    ('.github/workflows/ci.yml', 'env:\n  LEGACY_TOKEN: value\n'),
    ('.github/workflows/ci.yml', 'jobs:\n  build:\n    token: "${{ secrets.LEGACY_TOKEN }}"\n'),
    ('.github/workflows/ci.yml', 'jobs:\n  build:\n    token: "${{ env.LEGACY_TOKEN }}"\n'),
    ('k8s/deploy.yml', 'spec:\n  containers:\n    - env:\n        - name: LEGACY_TOKEN\n          value: something\n'),
    ('helm/deploy.yaml', 'env:\n  - name: OTHER\n    valueFrom:\n      secretKeyRef:\n        name: secret\n        key: LEGACY_TOKEN\n'),
    ('helm/template.yaml', '{{- if .Values.enabled }}\nenv:\n  - name: LEGACY_TOKEN\n{{- end }}\n'),
])
def test_z_configuration_patterns_are_advisories(path, text):
    usage = collect_usage({'LEGACY_TOKEN'}, policy(), [path], lambda _: text)
    assert usage['LEGACY_TOKEN']['state'] == 'config'
    inputs = files()
    inputs[0].env_key_usage = usage
    assert run(inputs, policy=policy()).result == 'warn'


@pytest.mark.parametrize('path,text', [
    ('docker-compose.yml', '# ${LEGACY_TOKEN}\nname: LEGACY_TOKEN\n'),
    ('k8s/deploy.yml', 'metadata:\n  name: LEGACY_TOKEN\n'),
    ('launch.sh', '# export LEGACY_TOKEN=x\n'),
    ('src/app.py', '# os.getenv("LEGACY_TOKEN")\n'),
    ('src/app.js', 'const example = "process.env.LEGACY_TOKEN";\n'),
    ('src/app.ts', 'function f(process) { return process.env.LEGACY_TOKEN; }\n'),
    ('main.go', 'os.Getenv("LEGACY_TOKEN")\n'),
    ('settings.yml', 'example: LEGACY_TOKEN\n'),
])
def test_names_and_comments_do_not_establish_code_or_config_use(path, text):
    assert collect_usage({'LEGACY_TOKEN'}, policy(), [path], lambda _: text)['LEGACY_TOKEN']['state'] == 'mention'


@pytest.mark.parametrize('path,text', [('src/reader.py', OLD),
    ('src/reader.py', "from os import getenv as read\nvalue = read('LEGACY_TOKEN')\n"),
    ('src/reader.js', 'const token = process.env.LEGACY_TOKEN;'),
    ('src/reader.ts', 'const token = process.env["LEGACY_TOKEN"];')])
def test_live_static_code_use_passes(path, text):
    usage = collect_usage({'LEGACY_TOKEN'}, policy(), [path], lambda _: text)
    assert usage['LEGACY_TOKEN']['state'] == 'code'


def test_search_limits_failures_and_document_exclusion():
    keys = {'LEGACY_TOKEN'}
    assert collect_usage(keys, policy(), ['src/x'], lambda _: '', max_files=0)['LEGACY_TOKEN']['state'] == 'incomplete'
    assert collect_usage(keys, policy(), ['src/x'], lambda _: 'large', max_bytes=1)['LEGACY_TOKEN']['state'] == 'incomplete'
    assert collect_usage(keys, policy(), ['docs/x.md', '.env.example'], lambda _: OLD)['LEGACY_TOKEN']['state'] == 'absent'
    def fail(_):
        raise OSError('unavailable')
    assert collect_usage(keys, policy(), ['src/x'], fail)['LEGACY_TOKEN']['state'] == 'incomplete'


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE)


def repository(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    git(root, 'init', '-q')
    (root / 'src').mkdir()
    (root / 'src/settings.py').write_text(OLD)
    (root / '.env.example').write_text('LEGACY_TOKEN=not-a-secret\n')
    (root / '.drift-gate.yml').write_text('''rules:
  - id: env
    severity: blocker
    when:
      any_changed: [src/**]
    require:
      groups:
        - name: Environment
          any_changed: [.env.example]
          content: env-keys
''')
    git(root, 'add', '.')
    git(root, '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-qm', 'base')
    (root / 'src/settings.py').write_text(NEW)
    return root


def test_local_desktop_mcp_and_captured_replay(tmp_path, monkeypatch):
    root = repository(tmp_path)
    result = scan_repository(root).result
    assert result.result == 'fail'
    monkeypatch.chdir(root)
    assert drift_gate_check_local(mode='full')['result'] == 'fail'
    (root / 'src/settings.py').write_text(OLD)
    assert inspect_snapshot(result.input_snapshot).result == 'fail'
    assert scan_repository(root).result.result == 'pass'
    text = json.dumps(result.to_dict())
    assert 'not-a-secret' not in text


def test_git_search_failure_is_warning(tmp_path, monkeypatch):
    root = repository(tmp_path)
    def fail(*args, **kwargs):
        raise OSError('git grep failed')
    from drift_gate.adapters import removed_key_usage
    inputs = files()
    monkeypatch.setattr(removed_key_usage.subprocess, 'run', fail)
    result = run(attach_local_usage(inputs, policy(), root), policy=policy())
    assert result.result == 'warn' and result.advisories[0].kind == 'incomplete'


def test_reports_and_compact_mcp_show_advisories_without_violations():
    result = run(files('config'), policy=policy())
    assert not result.violations
    assert 'LEGACY_TOKEN' in MarkdownReporter().render(result)
    assert 'LEGACY_TOKEN' in HtmlReporter().render(result)
    assert _compact_result(result, files('config'), token_budget=1200)['advisories'][0]['key'] == 'LEGACY_TOKEN'


def test_immutable_commit_search_and_bundle_replay(tmp_path):
    from hashlib import sha256

    from drift_gate.adapters.evidence_bundle import load_bundle, save_bundle
    from drift_gate.adapters.git.immutable import collect_git_snapshot
    root = repository(tmp_path)
    base = git(root, 'rev-parse', 'HEAD').decode().strip()
    git(root, 'add', '.')
    git(root, '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-qm', 'remove')
    source = (root / '.drift-gate.yml').read_text()
    snapshot = collect_git_snapshot(root=root, base=base, head='HEAD', trusted_policy_ref=base,
                                    trusted_policy_sha256=sha256(source.encode()).hexdigest())
    result = inspect_snapshot(snapshot)
    assert result.result == 'fail'
    saved = save_bundle(result, tmp_path / 'bundles')
    loaded = load_bundle(saved.path)
    assert loaded.replay().execution['bundle_replay']['recorded_result_matches_current']


@pytest.mark.parametrize('option', ['check_removed_keys: false\n', 'exclude_removed_keys: [LEGACY_TOKEN]\n'])
def test_trusted_policy_weakening_requires_review(tmp_path, monkeypatch, option):
    from hashlib import sha256

    from drift_gate.adapters import trusted_validation
    root = repository(tmp_path)
    base = git(root, 'rev-parse', 'HEAD').decode().strip()
    source = (root / '.drift-gate.yml').read_text()
    (root / '.drift-gate.yml').write_text(source+option)
    git(root, 'add', '.')
    git(root, '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-qm', 'weaken policy')
    monkeypatch.setattr(trusted_validation.engines, 'run_pinned', lambda *a, **kw: {
        'attestation': {'loaded_code_matches_manifest': True, 'parsers': {'basis': 'test', 'matched': True}},
        'stdout': json.dumps({'result': 'pass'}), 'exit_code': 0})
    monkeypatch.setattr(trusted_validation.engines, 'manifest_bytes', lambda _: b'manifest')
    result = trusted_validation.trusted_check(root=root, base=base, head='HEAD', policy='.drift-gate.yml',
        trusted_policy_ref=base, trusted_policy_sha256=sha256(source.encode()).hexdigest(), manifest={'commit': base})
    assert result['decision']['action'] == 'review'
    assert result['decision']['merge_basis'] == 'none'
    assert 'candidate-policy-weakened' in result['decision']['reasons']


@pytest.mark.parametrize('source', ['const example = /process.env.LEGACY_TOKEN/;',
                                  'const example = <p>process.env.LEGACY_TOKEN</p>;'])
def test_javascript_non_code_mentions_cannot_create_a_removed_key_violation(tmp_path, source):
    from drift_gate.adapters.removed_key_usage import attach_javascript_removals
    inputs = files('absent')
    inputs[0] = ChangedFile('src/main.tsx', 'modified', before_source=source, after_source='const value = null;',
                            patch='-'+source+'\n+const value = null;\n')
    enriched = attach_javascript_removals(inputs)
    assert enriched[0].removed_env_key_candidates == []


def test_javascript_removal_is_verified_through_local_ast(tmp_path):
    root = repository(tmp_path)
    (root / 'src/settings.py').write_text('value = None\n')
    (root / 'src/main.js').write_text('const token = process.env.LEGACY_TOKEN;\n')
    git(root, 'add', '.')
    git(root, '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-qm', 'js reader')
    (root / 'src/main.js').write_text('const token = null;\n')
    result = scan_repository(root).result
    assert result.result == 'fail' and result.violations


def test_untracked_consumer_prevents_a_false_stale_document_failure(tmp_path):
    root = repository(tmp_path)
    (root / 'src/consumer.py').write_text(OLD)
    assert scan_repository(root).result.result == 'pass'


@pytest.mark.parametrize('source', ['const {process} = other; const value = process.env.LEGACY_TOKEN;',
                                  'process.env.LEGACY_TOKEN = "value";'])
def test_javascript_shadowing_and_writes_do_not_certify_live_reads(source):
    row = collect_usage({'LEGACY_TOKEN'}, policy(), ['src/main.js'], lambda _: source)
    assert row['LEGACY_TOKEN']['state'] == 'mention'


def test_added_key_check_stays_active_when_removal_is_disabled():
    inputs = files('absent')
    inputs[0] = replace(inputs[0], after_source=NEW+"other = os.getenv('NEW_TOKEN')\n")
    assert run(inputs, policy=policy(check_removed_keys=False)).result == 'fail'


def test_old_empty_advisory_results_remain_semantically_equivalent():
    from drift_gate.adapters.bundle_codec import semantic_result
    current = run(files('code'), policy=policy()).to_dict()
    previous = {k: v for k, v in current.items() if k != 'advisories'}
    assert semantic_result(current) == semantic_result(previous)
