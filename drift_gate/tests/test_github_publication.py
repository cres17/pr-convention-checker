"""PR comment freshness checks and lost-response recovery against a fake provider."""
from copy import deepcopy
import json

import pytest

from drift_gate.adapters.cli.runner import run_cli
from drift_gate.adapters.github import publication as pub
from drift_gate.adapters.run_coordinator import RunController

HEAD, OTHER = 'a' * 40, 'b' * 40
BODY = pub.MARKER + '\n## Drift Gate Report\nresult\n'


def ident(run_number=5, run_attempt=1, workflow='o/r/.github/workflows/ci.yml@refs/pull/1/merge', head=HEAD):
    return pub.identity(repo='o/r', pr_number=1, head_oid=head, workflow_ref=workflow, run_id='99',
                        run_number=run_number, run_attempt=run_attempt, result_sha256='c' * 64)


class FakeApi:
    """In-memory provider. ``lose`` makes the next write apply (or not) but lose its response."""

    def __init__(self, heads=(HEAD,), comments=None):
        self.heads, self.list_failures = list(heads), 0
        self.store = deepcopy(comments or [])
        self.writes, self.lose, self.refuse = [], [], None
        self.footer = ''  # models an intermediary that appends to every written body

    def pr_head(self, pr):
        return self.heads.pop(0) if len(self.heads) > 1 else self.heads[0]

    def comments(self, pr):
        if self.list_failures:
            self.list_failures -= 1
            raise pub.LostResponse('listing timed out')
        return deepcopy(self.store)

    def _write(self, kind, apply):
        self.writes.append(kind)
        if self.refuse:
            raise pub.ProviderError('refused', self.refuse)
        lost = self.lose.pop(0) if self.lose else None
        if lost != 'not-applied':
            comment = apply()
        if lost:
            raise pub.LostResponse('response lost')
        return {**comment, 'html_url': f'https://example.invalid/{comment["id"]}'}

    def create(self, pr, body):
        def apply():
            comment = {'id': 100 + len(self.store), 'body': body + self.footer}
            self.store.append(comment)
            return comment
        return self._write('create', apply)

    def update(self, comment_id, body):
        def apply():
            comment = next(c for c in self.store if c['id'] == comment_id)
            comment['body'] = body + self.footer
            return comment
        return self._write('update', apply)


def existing(run_number, *, workflow=None, head=HEAD):
    body, _ = pub.render(BODY.replace('result', f'old {run_number}'),
                         ident(run_number, workflow=workflow or 'o/r/.github/workflows/ci.yml@refs/pull/1/merge',
                               head=head))
    return {'id': 7, 'body': body}


def test_render_parse_roundtrip_and_tamper_detection():
    full, digest = pub.render(BODY, ident())
    meta = pub.parse(full)
    assert meta['key'] == ident()['key'] and meta['body_sha256'] == digest and meta['body_intact']
    assert pub.parse(full.replace('result', 'forged'))['body_intact'] is False
    assert pub.parse(pub.MARKER + '\nlegacy')['legacy'] is True
    assert pub.parse('unrelated') is None
    with pytest.raises(ValueError):
        pub.identity(repo='o/r', pr_number=1, head_oid='', workflow_ref='w', run_id='1', run_number=1,
                     run_attempt=1, result_sha256='c' * 64)


def test_create_then_idempotent_repeat_without_second_write():
    api = FakeApi()
    record = pub.publish(api, pr_number=1, body=BODY, ident=ident())
    assert (record['state'], record['operation'], api.writes) == ('published', 'create', ['create'])
    assert record['body_match'] == 'exact' and record['content_verified'] is True
    again = pub.publish(api, pr_number=1, body=BODY, ident=ident())
    assert again['reason'] == 'already-published-by-this-attempt' and api.writes == ['create']


def test_head_change_before_or_during_write_marks_stale():
    api = FakeApi(heads=(OTHER,))
    record = pub.publish(api, pr_number=1, body=BODY, ident=ident())
    assert (record['state'], record['reason'], api.writes) == ('publication-stale', 'head-changed-before-write', [])
    api = FakeApi(heads=(HEAD, OTHER))
    record = pub.publish(api, pr_number=1, body=BODY, ident=ident())
    assert (record['state'], record['reason'], record['published']) == (
        'publication-stale', 'head-changed-during-write', True)


def test_later_run_and_foreign_workflow_are_never_overwritten():
    api = FakeApi(comments=[existing(6)])
    record = pub.publish(api, pr_number=1, body=BODY, ident=ident(5))
    assert (record['state'], record['reason'], api.writes) == ('publication-stale', 'later-run-already-published', [])
    api = FakeApi(comments=[existing(5)])
    assert pub.publish(api, pr_number=1, body=BODY, ident=ident(5, run_attempt=2))['state'] == 'published'
    assert api.writes == ['update']
    api = FakeApi(comments=[existing(1, workflow='o/r/other.yml@x')])
    record = pub.publish(api, pr_number=1, body=BODY, ident=ident(5))
    assert (record['state'], api.writes) == ('publication-rejected', [])
    legacy = FakeApi(comments=[{'id': 7, 'body': pub.MARKER + '\nold'}])
    assert pub.publish(legacy, pr_number=1, body=BODY, ident=ident())['operation'] == 'update'


def test_lost_create_response_is_resolved_by_key_not_by_reposting():
    api = FakeApi()
    api.lose = ['applied']
    record = pub.publish(api, pr_number=1, body=BODY, ident=ident())
    assert (record['state'], record['reason']) == ('published', 'lost-response-reconciled-by-key')
    assert api.writes == ['create'] and len(api.store) == 1

    api = FakeApi()
    api.lose = ['not-applied']
    record = pub.publish(api, pr_number=1, body=BODY, ident=ident())
    assert (record['state'], record['reason']) == ('publication-unknown', 'create-not-visible')
    assert api.writes == ['create']  # no blind second create

    api = FakeApi()
    api.lose = ['applied']
    api.list_failures = 0

    original = api.comments
    calls = {'n': 0}

    def flaky(pr):
        calls['n'] += 1
        if calls['n'] > 1:  # the post-loss lookup fails
            raise pub.LostResponse('lookup failed')
        return original(pr)

    api.comments = flaky
    record = pub.publish(api, pr_number=1, body=BODY, ident=ident())
    assert (record['state'], record['reason']) == ('publication-unknown', 'lookup-failed')


def test_lost_update_is_retried_once_because_replace_is_idempotent():
    api = FakeApi(comments=[existing(4)])
    api.lose = ['not-applied']
    record = pub.publish(api, pr_number=1, body=BODY, ident=ident(5))
    assert record['state'] == 'published' and api.writes == ['update', 'update']
    assert pub.parse(api.store[0]['body'])['key'] == ident(5)['key']


def test_provider_refusal_is_definite_rejection():
    api = FakeApi()
    api.refuse = 403
    record = pub.publish(api, pr_number=1, body=BODY, ident=ident())
    assert record['state'] == 'publication-rejected' and record['attempts'][-1]['status'] == 403


def test_reconcile_command_looks_up_without_writing(tmp_path, monkeypatch, capsys):
    api = FakeApi()
    api.lose = ['not-applied']
    record = pub.publish(api, pr_number=1, body=BODY, ident=ident())
    assert record['state'] == 'publication-unknown'
    path = tmp_path / 'record.json'
    path.write_text(json.dumps(record))
    api.create(1, pub.render(BODY, ident())[0])  # the delayed original lands later
    writes = list(api.writes)
    monkeypatch.setenv('GITHUB_TOKEN', 'x')
    monkeypatch.setattr(pub, 'CommentApi', lambda *a, **k: api)
    with pytest.raises(SystemExit) as exit:
        run_cli(['publication', 'reconcile', '--record', str(path), '--repo', 'o/r', '--pr', '1'])
    assert exit.value.code == 0
    assert json.loads(capsys.readouterr().out)['state'] == 'published'
    assert api.writes == writes and json.loads(path.read_text())['state'] == 'publication-unknown'


def test_action_journal_records_publication_outcome(tmp_path, monkeypatch):
    from drift_gate.adapters.github_action import runner as action
    controller = RunController(tmp_path / 'runs', run_id='e' * 32)
    controller.start(data={'publication_target': 'pr-comment'})
    for state in ('validated', 'captured', 'planned', 'analyzing', 'evaluated', 'result-validated', 'persisted'):
        controller.advance(state)
    monkeypatch.setenv('GITHUB_OUTPUT', str(tmp_path / 'out'))
    for name, value in {'GITHUB_WORKFLOW_REF': 'o/r/ci.yml@x', 'GITHUB_RUN_ID': '1',
                        'GITHUB_RUN_NUMBER': '3', 'GITHUB_RUN_ATTEMPT': '1'}.items():
        monkeypatch.setenv(name, value)
    api = FakeApi()
    record = action._publish_comment(controller, token='t', repo='o/r', pr_number=1, body=BODY, head_oid=HEAD,
                                     result_sha256='c' * 64, runner_temp=str(tmp_path), api=api)
    assert record['state'] == 'published' and controller.view().state == 'published'
    assert 'publication_state=published' in (tmp_path / 'out').read_text()

    second = RunController(tmp_path / 'runs', run_id='f' * 32)
    second.start(data={})
    for state in ('validated', 'captured', 'planned', 'analyzing', 'evaluated', 'result-validated', 'persisted'):
        second.advance(state)
    monkeypatch.delenv('GITHUB_RUN_NUMBER')
    record = action._publish_comment(second, token='t', repo='o/r', pr_number=1, body=BODY, head_oid=HEAD,
                                     result_sha256='c' * 64, runner_temp=str(tmp_path), api=FakeApi())
    assert record['state'] == 'publication-rejected' and 'identity-unavailable' in record['reason']
    assert second.view().state == 'publication-rejected'


def test_action_main_journals_every_stage_through_comment_publication(tmp_path, monkeypatch):
    from drift_gate.adapters.docs.content import attach_env_documents, local_document_reader
    from drift_gate.adapters.git.client import GitAdapter
    from drift_gate.adapters.github_action import runner as action
    from drift_gate.adapters.run_store import RunJournal
    from drift_gate.tests.test_contract_projection import repository
    repository(tmp_path, 'stale')
    monkeypatch.chdir(tmp_path)

    class Remote:
        _snapshot_head = HEAD

        def __init__(self, **kwargs):
            pass

        def get_pr_files_and_body(self, number):
            return GitAdapter(tmp_path).get_changed_files('HEAD'), ''

        def attach_env_documents(self, number, files, policy):
            return attach_env_documents(files, policy, local_document_reader(tmp_path))

    fake = FakeApi()
    monkeypatch.setattr(action, 'GitHubAdapter', Remote)
    monkeypatch.setattr('drift_gate.adapters.github.approvals.verify_ignores', lambda *args, **kwargs: [])
    monkeypatch.setattr(pub, 'CommentApi', lambda *a, **k: fake)
    out = tmp_path / 'outputs'
    for name, value in {'GITHUB_TOKEN': 'fixture', 'REPO': 'o/r', 'PR_NUMBER': '1', 'GITHUB_WORKSPACE': str(tmp_path),
                        'RUNNER_TEMP': str(tmp_path), 'POST_COMMENT': 'true', 'ANTHROPIC_API_KEY': '',
                        'GITHUB_EVENT_PATH': '', 'GITHUB_OUTPUT': str(out), 'GITHUB_STEP_SUMMARY': '',
                        'GITHUB_WORKFLOW_REF': 'o/r/ci.yml@x', 'GITHUB_RUN_ID': '9', 'GITHUB_RUN_NUMBER': '2',
                        'GITHUB_RUN_ATTEMPT': '1'}.items():
        monkeypatch.setenv(name, value)
    action.main()
    outputs = dict(line.split('=', 1) for line in out.read_text().splitlines())
    view = RunJournal(tmp_path / 'drift-gate-runs', outputs['run_id']).view()
    assert view.history == ('requested', 'validated', 'captured', 'planned', 'analyzing', 'evaluated',
                            'result-validated', 'persisted', 'publish-pending', 'published')
    assert outputs['publication_state'] == 'published' and fake.writes == ['create']
    record = json.loads((tmp_path / 'drift_gate_publication.json').read_text())
    assert pub.parse(fake.store[0]['body'])['key'] == record['idempotency_key']
    report = json.loads((tmp_path / 'drift_gate_report.json').read_text())
    assert report['result'] == 'fail' and report['execution']['run_id'] == outputs['run_id']


def test_intermediary_footer_is_reported_without_rewrite_loop_or_false_rejection():
    """Live regression: a footer appended in transit made every repeat rewrite and a
    lost-response lookup report a landed write as rejected."""
    api = FakeApi()
    api.footer = '\n\n---\n_appended in transit_'
    record = pub.publish(api, pr_number=1, body=BODY, ident=ident(1))
    assert (record['state'], record['body_match'], record['content_verified']) == ('published', 'suffix-appended', False)
    again = pub.publish(api, pr_number=1, body=BODY, ident=ident(1))
    assert again['reason'] == 'already-published-by-this-attempt' and api.writes == ['create']
    api.lose = ['applied']
    lost = pub.publish(api, pr_number=1, body=BODY, ident=ident(1, run_attempt=2))
    assert (lost['state'], lost['reason']) == ('published', 'lost-response-reconciled-by-key')
    assert lost['reconciliation']['body_match'] == 'suffix-appended'


def test_reconcile_after_a_later_attempt_overwrote_reports_superseded(tmp_path, monkeypatch, capsys):
    api = FakeApi(comments=[existing(4)])
    api.lose = ['applied']
    record = pub.publish(api, pr_number=1, body=BODY, ident=ident(5, run_attempt=1))
    assert record['state'] == 'published'
    pub.publish(api, pr_number=1, body=BODY, ident=ident(5, run_attempt=2))  # later attempt replaces it
    path = tmp_path / 'record.json'
    path.write_text(json.dumps({**record, 'state': 'publication-unknown'}))
    monkeypatch.setenv('GITHUB_TOKEN', 'x')
    monkeypatch.setattr(pub, 'CommentApi', lambda *a, **k: api)
    with pytest.raises(SystemExit) as exit:
        run_cli(['publication', 'reconcile', '--record', str(path), '--repo', 'o/r', '--pr', '1'])
    data = json.loads(capsys.readouterr().out)
    assert exit.value.code == 1
    assert (data['state'], data['reason']) == ('publication-stale', 'superseded-by-later-attempt')
