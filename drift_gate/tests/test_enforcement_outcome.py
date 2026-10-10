"""Design section 7: organisation action is a projection of the rule decisions, not a new verdict."""
import json
import subprocess

import pytest

from drift_gate.adapters.bundle_codec import semantic_result
from drift_gate.core.engine import run
from drift_gate.core.gating.enforcement import ACTIONS, enforcement_outcome, execution_outcome
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.result import DriftIgnoreDirective
from drift_gate.core.policy.loader import load_policy_from_dict


def policy(severity='blocker', content=None, on_unverified=None, allow_ignore=False):
    group = {'name': 'docs', 'any_changed': ['docs/api.md']}
    if content:
        group['content'] = content
    data = {'rules': [{'id': 'api', 'when': {'any_changed': ['src/**']}, 'require': {'groups': [group]},
                       'severity': severity, **({'allow_ignore': True} if allow_ignore else {})}]}
    if on_unverified:
        data['gate'] = {'on_unverified': on_unverified}
    return load_policy_from_dict(data)


ROUTE = 'from fastapi import FastAPI\napp = FastAPI()\n@app.get("{}")\ndef h():\n    return 1\n'
CODE = ChangedFile('src/api.py', 'modified', patch='@@\n-a\n+b\n', before_source=ROUTE.format('/old'),
                   after_source=ROUTE.format('/new'))


def doc(text):
    return ChangedFile('docs/api.md', 'modified', patch='@@\n+x\n', after_source=text)


@pytest.mark.parametrize('files, rules, action, field', [
    ([CODE, doc('GET /new\n')], policy(), 'allow', None),
    ([CODE], policy(), 'block', 'confirmed_violation_rule_ids'),
    ([CODE], policy('minor'), 'review', 'confirmed_violation_rule_ids'),     # gate warn: tolerated, not allowed
    ([ChangedFile('docs/x.md', 'modified', patch='@@\n+x\n')], policy(), 'allow', None),  # docs-only skip
])
def test_action_follows_gate_and_decisions(files, rules, action, field):
    result = run(files, policy=rules)
    outcome = enforcement_outcome(result)
    assert outcome['action'] == action and outcome['action'] in ACTIONS
    assert outcome['gate_result'] == result.result
    if field:
        assert outcome[field] == ['api']
    assert result.to_dict()['enforcement'] == outcome  # every JSON entrypoint carries the same projection


def test_unknown_that_the_gate_lets_through_is_review_not_allow():
    broken = ChangedFile('src/api.py', 'modified', patch='@@\n+x\n', before_source=ROUTE.format('/old'),
                         after_source='def (:\n')
    result = run([broken, doc('GET /old\n')], policy=policy(content='api-routes', on_unverified='warn'))
    outcome = enforcement_outcome(result)
    assert result.result != 'fail' and outcome['unresolved_rule_ids'] == ['api'] and outcome['action'] == 'review'


def test_waived_rules_are_listed_and_not_confirmed():
    ignore = DriftIgnoreDirective(rule_id='api', reason='tracked separately')
    result = run([CODE], policy=policy('minor', allow_ignore=True), drift_ignores=[ignore])
    outcome = enforcement_outcome(result)
    assert outcome['waived_rule_ids'] == ['api'] and outcome['confirmed_violation_rule_ids'] == []


def test_replay_comparison_ignores_the_derived_projection():
    result = run([CODE], policy=policy()).to_dict()
    recorded = {k: v for k, v in result.items() if k != 'enforcement'}  # written before the field existed
    assert semantic_result(recorded) == semantic_result(result)


@pytest.mark.parametrize('status, expected', [('success', 'completed'), ('input_error', 'rejected-input'),
                                              ('resource_limit', 'aborted'), ('cancelled', 'aborted'),
                                              ('result_validation_error', 'internal-error'),
                                              ('something-new', 'internal-error')])
def test_execution_outcome_statuses(status, expected):
    outcome = execution_outcome(status)
    assert outcome['status'] == expected and outcome['result_available'] == (status == 'success')


def test_cli_reports_execution_outcome_for_success_and_rejected_input(tmp_path, capsys):
    from drift_gate.adapters.cli.runner import run_cli
    git = lambda *a: subprocess.check_output(['git', '-c', 'core.autocrlf=false', *a], cwd=tmp_path)
    git('init', '-q')
    (tmp_path / '.drift-gate.yml').write_text(
        'rules:\n  - id: api\n    when: {any_changed: ["src/**"]}\n'
        '    require: {groups: [{name: docs, any_changed: ["docs/api.md"]}]}\n    severity: blocker\n',
        encoding='utf-8', newline='\n')
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src/a.py').write_text('x = 1\n')
    git('add', '-A'); git('-c', 'user.name=t', '-c', 'user.email=t@example.invalid', 'commit', '-qm', 'base')
    (tmp_path / 'src/a.py').write_text('x = 2\n')
    import os
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        with pytest.raises(SystemExit) as done:
            run_cli(['check', '--base', 'HEAD', '--json'])
        data = json.loads(capsys.readouterr().out)
        assert done.value.code == 1 and data['enforcement']['action'] == 'block'
        assert data['execution']['outcome']['status'] == 'completed'
        with pytest.raises(SystemExit) as failed:
            run_cli(['check', '--base', 'no-such-ref', '--json'])
        error = json.loads(capsys.readouterr().out)
        assert failed.value.code == 2 and error['execution']['outcome']['status'] == 'rejected-input'
        assert 'enforcement' not in error  # no result, no action, never allow
    finally:
        os.chdir(cwd)
