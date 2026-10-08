"""W15 run lifecycle, cancellation/retry, latest fencing and publication recovery."""
from hashlib import sha256
import itertools
import json
import os
from pathlib import Path
import threading
import time

import pytest

from drift_gate.adapters import run_store
from drift_gate.adapters.cli.runner import run_cli
from drift_gate.adapters.run_coordinator import RunController, RunTerminated, cancel_run
from drift_gate.core.execution import latest, lifecycle
from drift_gate.core.execution.publication import reconcile
from drift_gate.tests.test_git_immutable import repo as repository_fixture, commit

RUN = 'a' * 32
OWNER = 'b' * 32
A, B = '1' * 40, '2' * 40
AUTH, AUTH2 = 'c' * 64, 'd' * 64


def ev(state, controller='owner', **extra):
    return {'kind': 'state', 'state': state, 'controller': controller, 'owner': OWNER, 'run_id': RUN, **extra}


def journal(*states, controller='owner'):
    events = [ev('requested', attempt=1, retry_of=None)]
    events += [ev(s, controller) for s in states]
    return [{**e, 'sequence': i} for i, e in enumerate(events)]


def view_of(*states):
    return lifecycle.fold(journal(*states))


HAPPY = ('validated', 'captured', 'planned', 'analyzing', 'evaluated', 'result-validated',
         'persisted', 'publish-pending', 'published')


# -- core state machine ---------------------------------------------------------
def test_semantic_completion_is_result_validated_not_publication():
    assert not view_of(*HAPPY[:5]).semantic_completed
    done = view_of(*HAPPY[:6])
    assert done.semantic_completed and not done.closed
    final = view_of(*HAPPY)
    assert final.closed and final.state == 'published' and final.history[-1] == 'published'


def test_reply_after_cancel_is_rejected_but_may_be_annotated():
    cancelled = view_of('validated', 'captured', 'planned', 'analyzing', 'cancelled')
    assert cancelled.closed
    assert lifecycle.decide(cancelled, ev('evaluated')).reason == 'run-closed'
    note = {'kind': 'annotation', 'annotation': 'late-response-discarded', 'run_id': RUN}
    assert lifecycle.decide(cancelled, note).accepted
    assert lifecycle.decide(cancelled, ev('cancelled', 'operator')).reason == 'run-closed'


def test_failures_stop_at_durable_result_and_respect_controllers():
    durable = view_of(*HAPPY[:7])
    for state in lifecycle.FAILURES:
        assert lifecycle.decide(durable, ev(state, 'recovery' if state == 'abandoned' else 'owner')).reason \
            == 'result-already-durable'
    running = view_of('validated', 'captured', 'planned', 'analyzing')
    assert lifecycle.decide(running, ev('evaluated', 'operator')).reason == 'progress-requires-owner'
    assert lifecycle.decide(running, {**ev('evaluated'), 'owner': 'e' * 32}).reason == 'not-run-owner'
    assert lifecycle.decide(running, ev('cancelled', 'recovery')).reason == 'cancel-requires-owner-or-operator'
    assert lifecycle.decide(running, ev('abandoned', 'operator')).reason == 'abandon-requires-recovery'
    assert lifecycle.decide(running, ev('internal-error', 'operator')).reason == 'failure-requires-owner'
    assert lifecycle.decide(running, ev('persisted')).reason == 'invalid-transition'
    assert lifecycle.decide(running, {**ev('evaluated'), 'run_id': 'f' * 32}).reason == 'foreign-run'


def test_every_state_event_pair_keeps_closed_runs_closed():
    """Exhaustive over states x target states x controllers (one-step table)."""
    controllers = ('owner', 'operator', 'recovery', 'reconciler')
    checked = 0
    for current in lifecycle.STATES:
        if current == 'requested':
            view = view_of()
        else:
            view = lifecycle.RunView(RUN, OWNER, current, 2, ('requested', current))
        for target, controller in itertools.product(lifecycle.STATES, controllers):
            decision = lifecycle.decide(view, ev(target, controller))
            checked += 1
            if view.closed:
                assert not decision.accepted
            if decision.accepted and target in lifecycle.FAILURES:
                assert current in lifecycle.STAGES[:lifecycle.STAGES.index('persisted')]
            if decision.accepted and lifecycle.STATES.index(target) < len(lifecycle.STAGES):
                assert target != 'requested'
    assert checked == len(lifecycle.STATES) ** 2 * len(controllers)


def test_fold_rejects_gaps_rejected_events_and_bad_lineage():
    events = journal('validated', 'captured')
    with pytest.raises(lifecycle.LifecycleError, match='gap'):
        lifecycle.fold([events[0], events[2]])
    bad = journal('validated', 'cancelled') + [{**ev('captured'), 'sequence': 3}]
    with pytest.raises(lifecycle.LifecycleError, match='run-closed'):
        lifecycle.fold(bad)
    with pytest.raises(lifecycle.LifecycleError, match='lineage'):
        lifecycle.fold([{**events[0], 'retry_of': None, 'attempt': 2}])
    with pytest.raises(lifecycle.LifecycleError, match='lineage'):
        lifecycle.fold([{**events[0], 'retry_of': RUN, 'attempt': 2}])
    with pytest.raises(lifecycle.LifecycleError, match='hex'):
        lifecycle.fold([{**events[0], 'run_id': 'X'}])


def test_recovery_never_turns_pending_publication_into_not_sent():
    kwargs = dict(now_seconds=1000, last_activity_seconds=0, stale_after_seconds=60)
    assert lifecycle.recovery_event(view_of('validated', 'captured', 'planned', 'analyzing'),
                                    **kwargs)['state'] == 'abandoned'
    assert lifecycle.recovery_event(view_of(*HAPPY[:8]), **kwargs)['state'] == 'publication-unknown'
    assert lifecycle.recovery_event(view_of(*HAPPY[:7]), **kwargs)['state'] == 'publication-skipped'
    target = lifecycle.fold([{**journal()[0], 'data': {'publication_target': 'main'}}]
                            + [{**ev(s), 'sequence': i + 1} for i, s in enumerate(HAPPY[:7])])
    assert lifecycle.recovery_event(target, **kwargs)['state'] == 'publication-rejected'
    assert lifecycle.recovery_event(view_of('validated'), now_seconds=10, last_activity_seconds=0,
                                    stale_after_seconds=60) is None
    assert lifecycle.recovery_event(view_of(*HAPPY), **kwargs) is None


def test_retry_requires_closed_predecessor():
    assert lifecycle.retry_admission(view_of('validated')).reason == 'previous-run-not-closed'
    assert lifecycle.retry_admission(view_of('validated', 'timed-out')).accepted
    unknown = view_of(*HAPPY[:8], 'publication-unknown')
    assert lifecycle.retry_admission(unknown).reason == 'previous-run-not-closed'


# -- latest fencing --------------------------------------------------------------
def ledger(*steps):
    """steps: ('obs', head, auth) or ('pub', ticket). Returns (state, decisions)."""
    entries, decisions, tickets = [], [], {}
    state = latest.TargetState('t')
    for step in steps:
        if step[0] == 'obs':
            entry, ticket, generation = latest.observe(state, head_oid=step[1], authority_sha256=step[2])
            tickets[ticket] = {'ticket': ticket, 'generation': generation, 'head_oid': step[1],
                               'authority_sha256': step[2]}
            entries.append({**entry, 'sequence': len(entries)})
        else:
            request = {**tickets[step[1]], 'run_id': f'{step[1]:032x}', 'receipt_sha256': 'e' * 64,
                       'result_sha256': 'f' * 64}
            decision = latest.decide_publish(state, request, completed=True)
            decisions.append(decision.reason)
            if decision.accepted:
                entries.append({**latest.publish_entry(request), 'sequence': len(entries)})
        state = latest.fold('t', entries)
    return state, decisions


def test_head_aba_cannot_resurrect_old_attempt():
    state, decisions = ledger(('obs', A, AUTH), ('obs', B, AUTH), ('obs', A, AUTH), ('pub', 1), ('pub', 3), ('pub', 2))
    assert decisions == ['generation-changed', 'compare-and-set-matched', 'generation-changed']
    assert state.latest.ticket == 3 and state.generation == 3
    assert state.to_dict()['latest_status'] == 'current'


def test_reverse_completion_and_authority_change():
    state, decisions = ledger(('obs', A, AUTH), ('obs', A, AUTH), ('pub', 2), ('pub', 1))
    assert decisions == ['compare-and-set-matched', 'newer-or-same-result-already-latest']
    assert state.generation == 1
    state, decisions = ledger(('obs', A, AUTH), ('pub', 1), ('obs', A, AUTH2))
    assert state.generation == 2 and state.to_dict()['latest_status'] == 'stale'


def test_forged_requests_and_incomplete_runs_are_refused():
    state, _ = ledger(('obs', A, AUTH), ('obs', B, AUTH), ('obs', A, AUTH))
    good = {'ticket': 3, 'generation': 3, 'head_oid': A, 'authority_sha256': AUTH}
    assert latest.decide_publish(state, good, completed=False).reason == 'run-not-semantically-completed'
    assert latest.decide_publish(state, {**good, 'ticket': 1}, completed=True).reason == 'ticket-observation-mismatch'
    assert latest.decide_publish(state, {**good, 'ticket': 9}, completed=True).reason == 'unknown-ticket'
    forged = [{**latest.observe(latest.TargetState('t'), head_oid=A, authority_sha256=AUTH)[0], 'sequence': 0},
              {'kind': 'observe', 'head_oid': B, 'authority_sha256': AUTH, 'ticket': 2, 'generation': 1,
               'sequence': 1}]
    with pytest.raises(latest.LedgerError, match='observation'):
        latest.fold('t', forged)


def test_bounded_model_of_latest_pointer_invariants():
    """Every sequence of 7 events over {observe A, observe B, observe A with new authority,
    publish any issued ticket}. Also counts where a head-only check (rejected design) would
    have accepted an attempt from an earlier generation."""
    observations = [('obs', A, AUTH), ('obs', B, AUTH), ('obs', A, AUTH2)]
    counts = {'explored': 0, 'accepted': 0, 'violations': 0, 'head_only_would_resurrect': 0}

    def walk(state, entries, tickets, depth):
        counts['explored'] += 1
        if depth == 7:
            return
        for step in observations + [('pub', t) for t in sorted(tickets)]:
            new_entries, new_tickets = entries, tickets
            if step[0] == 'obs':
                entry, ticket, generation = latest.observe(state, head_oid=step[1], authority_sha256=step[2])
                new_entries = entries + [{**entry, 'sequence': len(entries)}]
                new_tickets = {**tickets, ticket: (generation, step[1], step[2])}
            else:
                generation, head, auth = tickets[step[1]]
                request = {'ticket': step[1], 'generation': generation, 'head_oid': head, 'authority_sha256': auth,
                           'run_id': f'{step[1]:032x}', 'receipt_sha256': 'e' * 64, 'result_sha256': 'f' * 64}
                decision = latest.decide_publish(state, request, completed=True)
                naive = (head == state.head_oid and (state.latest is None or state.latest.ticket < step[1]))
                if naive and generation != state.generation:
                    counts['head_only_would_resurrect'] += 1
                if decision.accepted:
                    counts['accepted'] += 1
                    if (generation != state.generation or (head, auth) != (state.head_oid, state.authority_sha256)
                            or (state.latest is not None and state.latest.ticket >= step[1])):
                        counts['violations'] += 1
                    new_entries = entries + [{**latest.publish_entry(request), 'sequence': len(entries)}]
            walk(latest.fold('t', new_entries), new_entries, new_tickets, depth + 1)

    walk(latest.TargetState('t'), [], {}, 0)
    assert counts['violations'] == 0
    assert counts['accepted'] > 0 and counts['head_only_would_resurrect'] > 0
    assert counts['explored'] > 100_000, counts


# -- publication reconciliation ---------------------------------------------------
def test_lost_response_reconciliation_table():
    key, body = '1' * 64, '2' * 64
    args = dict(key=key, body_sha256=body)
    assert reconcile(**args, operation='create', target_comment_id=None, lookup=None).state == 'publication-unknown'
    found = reconcile(**args, operation='create', target_comment_id=None,
                      lookup=[{'id': 1, 'key': key, 'body_sha256': body}, {'id': 2, 'key': key, 'body_sha256': body}])
    assert (found.state, found.comment_id, found.duplicates) == ('published', 1, 1)
    assert reconcile(**args, operation='create', target_comment_id=None,
                     lookup=[{'id': 1, 'key': key, 'body_sha256': '3' * 64}]).state == 'publication-rejected'
    absent = reconcile(**args, operation='create', target_comment_id=None, lookup=[])
    assert (absent.state, absent.retry_safe) == ('publication-unknown', False)
    update = reconcile(**args, operation='update', target_comment_id=7, lookup=[{'id': 7, 'key': '4' * 64}])
    assert (update.state, update.retry_safe) == ('publication-unknown', True)
    assert not reconcile(**args, operation='update', target_comment_id=7, lookup=[]).retry_safe


# -- local store -----------------------------------------------------------------
def test_store_appends_are_exclusive_under_contention(tmp_path):
    sequence = run_store.Sequence(tmp_path / 'seq')
    sequence.append({'n': 0}, expected_length=0)
    barrier, outcomes = threading.Barrier(8), []

    def writer(index):
        barrier.wait()
        try:
            sequence.append({'writer': index}, expected_length=1)
            outcomes.append('won')
        except run_store.Conflict:
            outcomes.append('conflict')

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert outcomes.count('won') == 1 and len(sequence.read()) == 2
    assert not [n for n in os.listdir(tmp_path / 'seq') if n.startswith('.')]


def test_store_detects_edits_gaps_and_foreign_files(tmp_path):
    sequence = run_store.Sequence(tmp_path / 'seq')
    for i in range(3):
        sequence.append({'n': i}, expected_length=i)
    first = tmp_path / 'seq/00000001.json'
    original = first.read_bytes()
    first.write_bytes(original.replace(b'"n":1', b'"n":9'))
    with pytest.raises(run_store.RunStoreError, match='chain'):
        sequence.read()
    first.write_bytes(original)
    (tmp_path / 'seq/00000002.json').rename(tmp_path / 'seq/00000004.json')
    with pytest.raises(run_store.RunStoreError, match='gap'):
        sequence.read()
    (tmp_path / 'seq/00000004.json').rename(tmp_path / 'seq/00000002.json')
    (tmp_path / 'seq/notes.txt').write_text('x')
    with pytest.raises(run_store.RunStoreError, match='Unexpected'):
        sequence.read()


def test_recover_marks_silent_owner_abandoned_once(tmp_path):
    controller = RunController(tmp_path, run_id=RUN)
    controller.start(data={})
    for state in ('validated', 'captured', 'planned', 'analyzing'):
        controller.advance(state)
    assert run_store.recover(tmp_path, stale_after_seconds=60) == []
    recorded = run_store.recover(tmp_path, stale_after_seconds=60, now=time.time() + 120)
    assert recorded == [{'run_id': RUN, 'from': 'analyzing', 'to': 'abandoned'}]
    assert run_store.recover(tmp_path, stale_after_seconds=60, now=time.time() + 240) == []
    with pytest.raises(RunTerminated) as closed:
        controller.advance('evaluated')  # The slow owner is fenced out after recovery.
    assert closed.value.state == 'abandoned'


# -- coordinator -----------------------------------------------------------------
def started(tmp_path, **kwargs):
    controller = RunController(tmp_path, run_id=RUN, poll_seconds=0.02, **kwargs)
    controller.start(data={})
    for state in ('validated', 'captured', 'planned', 'analyzing'):
        controller.advance(state)
    return controller


def test_operator_cancel_discards_late_reply(tmp_path):
    controller = started(tmp_path, late_grace_seconds=2)
    release = threading.Event()

    class Late:
        result = 'pass'

    def analysis():
        release.wait(5)
        return Late()

    def operator():
        time.sleep(0.1)
        cancel_run(tmp_path, RUN, reason='test')
        release.set()

    threading.Thread(target=operator).start()
    with pytest.raises(RunTerminated) as closed:
        controller.call('analyzing', analysis)
    view = controller.view()
    assert closed.value.state == view.state == 'cancelled'
    assert 'evaluated' not in view.history
    assert view.annotations[-1]['annotation'] == 'late-response-discarded'
    assert view.annotations[-1]['gate_result'] == 'pass'


def test_deadline_closes_run_and_late_reply_cannot_reopen_it(tmp_path):
    controller = started(tmp_path, timeout_seconds=0.15, late_grace_seconds=2)
    with pytest.raises(RunTerminated) as closed:
        controller.call('analyzing', lambda: time.sleep(0.4) or 'late')
    view = controller.view()
    assert closed.value.state == view.state == 'timed-out'
    assert view.data['termination']['stage'] == 'analyzing'
    assert view.annotations[-1]['outcome'] == 'value'


def test_reply_racing_a_cancel_is_rejected(tmp_path):
    controller = started(tmp_path)

    def analysis():
        cancel_run(tmp_path, RUN)  # cancellation lands just before the reply
        return 'value'

    with pytest.raises(RunTerminated) as closed:
        controller.call('analyzing', analysis)
    assert closed.value.reason == 'reply-after-close'
    assert controller.view().annotations[-1]['annotation'] == 'late-response-discarded'


def test_worker_error_propagates_and_is_recorded_by_owner(tmp_path):
    controller = started(tmp_path)
    with pytest.raises(ZeroDivisionError):
        controller.call('analyzing', lambda: 1 / 0)
    controller.fail('internal-error', 'ZeroDivisionError', 'division by zero')
    assert controller.view().state == 'internal-error'


# -- CLI -------------------------------------------------------------------------
@pytest.fixture
def git_repository(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    return repository_fixture.__wrapped__(root)


def check(capsys, repository, store, *extra, head=None, code=None):
    from drift_gate.desktop.package_git_check import POLICY
    root, base, default_head = repository
    with pytest.raises(SystemExit) as exit:
        run_cli(['check', '--base', base, '--head', head or default_head, '--trusted-policy-ref', base,
                 '--trusted-policy-sha256', sha256(POLICY.encode()).hexdigest(), '--run-store', str(store),
                 '--json', *extra])
    data = json.loads(capsys.readouterr().out)
    if code is not None:
        assert exit.value.code == code, data
    return exit.value.code, data


def show(capsys, store, *args):
    with pytest.raises(SystemExit):
        run_cli(['run', *args, '--run-store', str(store)])
    return json.loads(capsys.readouterr().out)


def test_cli_journals_every_stage_and_persists_result(git_repository, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(git_repository[0])
    _, data = check(capsys, git_repository, tmp_path / 'runs', code=1)
    run = data['execution']['run']
    assert run['history'] == ['requested', *HAPPY[:7], 'publication-skipped']
    assert run['semantic_completed'] and run['closed']
    raw = (tmp_path / 'runs/runs' / run['run_id'] / 'result.json').read_bytes()
    assert sha256(raw).hexdigest() == run['result_file_sha256']
    assert json.loads(raw)['result'] == 'fail'
    assert show(capsys, tmp_path / 'runs', 'show', run['run_id'])['state'] == 'publication-skipped'


def test_cli_timeout_retry_and_lineage(git_repository, tmp_path, monkeypatch, capsys):
    from drift_gate.adapters import inspection
    monkeypatch.chdir(git_repository[0])
    real = inspection.inspect_snapshot
    monkeypatch.setattr(inspection, 'inspect_snapshot', lambda *a, **k: time.sleep(1.0) or real(*a, **k))
    _, data = check(capsys, git_repository, tmp_path / 'runs', '--timeout-seconds', '0.3', code=3)
    assert data['error']['code'] == 'timed_out'
    first = data['execution']['run']
    assert first['state'] == 'timed-out' and not first['semantic_completed']
    monkeypatch.setattr(inspection, 'inspect_snapshot', real)
    _, data = check(capsys, git_repository, tmp_path / 'runs', '--retry-of', first['run_id'], code=1)
    second = data['execution']['run']
    assert (second['retry_of'], second['attempt']) == (first['run_id'], 2)
    assert second['retry_input_relation'] == 'same-input'
    previous = show(capsys, tmp_path / 'runs', 'show', first['run_id'])
    assert previous['state'] == 'timed-out'  # never reopened
    assert previous['annotations'][-1] == {'annotation': 'retry-created', 'retry_run_id': second['run_id'],
                                           'attempt': 2}


def test_cli_rejects_retry_of_open_run_and_records_input_rejection(git_repository, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(git_repository[0])
    open_run = RunController(tmp_path / 'runs', run_id=RUN)
    open_run.start(data={})
    _, data = check(capsys, git_repository, tmp_path / 'runs', '--retry-of', RUN, code=2)
    assert 'previous-run-not-closed' in data['error']['message']
    with pytest.raises(SystemExit) as exit:
        run_cli(['check', '--base', 'HEAD', '--head', 'HEAD', '--run-store', str(tmp_path / 'runs'), '--json'])
    assert exit.value.code == 2
    run = json.loads(capsys.readouterr().out)['execution']['run']
    assert run['state'] == 'rejected-input' and run['history'] == ['requested', 'rejected-input']
    with pytest.raises(SystemExit) as exit:
        run_cli(['check', '--timeout-seconds', '1', '--json'])
    assert exit.value.code == 2 and 'requires --run-store' in json.loads(capsys.readouterr().out)['error']['message']


def test_cli_operator_cancel_command(tmp_path, capsys):
    controller = RunController(tmp_path, run_id=RUN)
    controller.start(data={})
    with pytest.raises(SystemExit) as exit:
        run_cli(['run', 'cancel', RUN, '--run-store', str(tmp_path), '--reason', 'superseded'])
    assert exit.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data['cancelled'] and data['run']['termination']['message'] == 'superseded'
    with pytest.raises(SystemExit) as exit:
        run_cli(['run', 'cancel', RUN, '--run-store', str(tmp_path)])
    assert exit.value.code == 1 and json.loads(capsys.readouterr().out)['reason'] == 'run-closed'


def test_cli_latest_pointer_fences_concurrent_head_change(git_repository, tmp_path, monkeypatch, capsys):
    root, base, head_a = git_repository
    monkeypatch.chdir(root)
    (root / 'docs/api.md').write_bytes(b'GET /new\n')
    head_b = commit(root, 'docs')
    store, evidence = tmp_path / 'runs', tmp_path / 'evidence'
    target = ['--latest-target', 'repo#1', '--evidence-store', str(evidence)]
    _, data = check(capsys, git_repository, store, *target, head=head_a, code=1)
    assert data['execution']['run']['publication']['state'] == 'published'

    from drift_gate.adapters import inspection
    real = inspection.inspect_snapshot

    def slow_with_concurrent_runs(*args, **kwargs):
        # While A is analysed, runs for B and then A again observe the target.
        ledger = run_store.TargetLedger(store, 'repo#1')
        state, _ = ledger.state()
        ledger.observe(head_oid=head_b, authority_sha256=state.authority_sha256, run_id='9' * 32)
        ledger.observe(head_oid=head_a, authority_sha256=state.authority_sha256, run_id='8' * 32)
        return real(*args, **kwargs)

    monkeypatch.setattr(inspection, 'inspect_snapshot', slow_with_concurrent_runs)
    _, data = check(capsys, git_repository, store, *target, head=head_a, code=1)
    publication = data['execution']['run']['publication']
    assert (publication['state'], publication['reason']) == ('publication-stale', 'generation-changed')
    assert data['execution']['run']['semantic_completed']  # the result itself stands
    monkeypatch.setattr(inspection, 'inspect_snapshot', real)
    _, data = check(capsys, git_repository, store, *target, head=head_b, code=0)
    assert data['execution']['run']['publication']['state'] == 'published'
    pointer = show(capsys, store, 'latest', 'repo#1')
    assert pointer['latest']['head_oid'] == head_b and pointer['latest_status'] == 'current'
    assert pointer['latest']['run_id'] == data['execution']['run_id']


def test_latest_target_requires_receipts_and_immutable_head(tmp_path, capsys):
    with pytest.raises(SystemExit) as exit:
        run_cli(['check', '--run-store', str(tmp_path), '--latest-target', 'x', '--json'])
    assert exit.value.code == 2
    assert 'requires immutable --head' in json.loads(capsys.readouterr().out)['error']['message']


SLOW_CHILD = '''
import sys, time
from drift_gate.adapters import inspection
inspection.inspect_snapshot = lambda *a, **k: time.sleep(60)
from drift_gate.adapters.cli.runner import run_cli
run_cli(sys.argv[1:])
'''


def spawn_slow_check(git_repository, store):
    import subprocess
    import sys
    from drift_gate.desktop.package_git_check import POLICY
    root, base, head = git_repository
    process = subprocess.Popen([sys.executable, '-c', SLOW_CHILD, 'check', '--base', base, '--head', head,
                                '--trusted-policy-ref', base, '--trusted-policy-sha256',
                                sha256(POLICY.encode()).hexdigest(), '--run-store', str(store), '--json'],
                               cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[2])})
    deadline = time.time() + 60
    while time.time() < deadline:
        runs = run_store.list_runs(store)
        view = run_store.RunJournal(store, runs[0]).view() if runs else None  # None: first entry not linked yet
        if view is not None and view.state == 'analyzing':
            return process, runs[0]
        if process.poll() is not None:
            raise AssertionError(process.communicate())
        time.sleep(0.05)
    process.kill()
    raise AssertionError('child never reached analyzing')


def test_killed_process_is_recovered_as_abandoned(git_repository, tmp_path):
    store = tmp_path / 'runs'
    process, run_id = spawn_slow_check(git_repository, store)
    process.kill()  # SIGKILL on POSIX, TerminateProcess on Windows: no cleanup runs
    process.communicate(timeout=30)
    view = run_store.RunJournal(store, run_id).view()
    assert view.state == 'analyzing' and not view.closed
    assert run_store.recover(store, stale_after_seconds=30) == []  # still within the lease
    recorded = run_store.recover(store, stale_after_seconds=30, now=time.time() + 60)
    assert recorded == [{'run_id': run_id, 'from': 'analyzing', 'to': 'abandoned'}]
    assert run_store.RunJournal(store, run_id).view().data['termination']['last_state'] == 'analyzing'


@pytest.mark.skipif(os.name == 'nt', reason='POSIX SIGTERM delivery')
def test_sigterm_is_recorded_as_cancelled(git_repository, tmp_path):
    import signal
    store = tmp_path / 'runs'
    process, run_id = spawn_slow_check(git_repository, store)
    process.send_signal(signal.SIGTERM)
    out, _ = process.communicate(timeout=30)
    assert process.returncode == 3
    assert json.loads(out)['execution']['run']['state'] == 'cancelled'
    view = run_store.RunJournal(store, run_id).view()
    assert view.state == 'cancelled' and view.data['termination']['code'] == 'interrupt'


def test_local_unknown_publication_is_reconciled_only_when_entry_is_found(tmp_path, capsys):
    def pending(run_id, publish):
        ledger = run_store.TargetLedger(tmp_path, 'main')
        observation = ledger.observe(head_oid=A, authority_sha256=AUTH, run_id=run_id)
        controller = RunController(tmp_path, run_id=run_id)
        controller.start(data={'publication_target': 'main'})
        for state in HAPPY[:7]:
            controller.advance(state)
        request = {**{k: observation[k] for k in ('ticket', 'generation', 'head_oid', 'authority_sha256')},
                   'run_id': run_id, 'receipt_sha256': 'e' * 64, 'result_sha256': 'f' * 64}
        controller.advance('publish-pending', publication_request={'target': 'main', **request})
        if publish:
            assert ledger.publish(request, completed=True)[0].accepted  # landed, then the owner died
        assert run_store.recover(tmp_path, stale_after_seconds=1, now=time.time() + 10)[0]['to'] == \
            'publication-unknown'

    pending('1' * 32, publish=False)
    assert run_store.reconcile_latest(tmp_path, '1' * 32)['reason'] == 'entry-not-found-kept-unknown'
    pending('2' * 32, publish=True)
    with pytest.raises(SystemExit) as exit:
        run_cli(['run', 'reconcile', '2' * 32, '--run-store', str(tmp_path)])
    assert exit.value.code == 0 and json.loads(capsys.readouterr().out)['state'] == 'published'
    view = run_store.RunJournal(tmp_path, '2' * 32).view()
    assert view.history[-2:] == ('publication-unknown', 'published')
    assert view.annotations[-1]['annotation'] == 'publication-reconciled'
