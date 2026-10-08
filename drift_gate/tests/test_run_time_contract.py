"""Invalid times cannot terminate another owner's run or create a new journal."""
import pytest

from drift_gate.adapters.cli.runner import run_cli
from drift_gate.adapters.run_coordinator import RunController
from drift_gate.adapters.run_store import RunStoreError, recover
from drift_gate.core.execution import lifecycle


INVALID_DURATION = (float('nan'), float('inf'), float('-inf'), 0, -1, True, 10 ** 1000)
RUN = 'a' * 32


def active_run(root):
    controller = RunController(root, run_id=RUN)
    controller.start(data={})
    return controller


@pytest.mark.parametrize('duration', INVALID_DURATION,
                         ids=['nan', 'inf', '-inf', 'zero', 'negative', 'bool', 'overflow'])
def test_invalid_lease_preserves_live_journal(tmp_path, duration):
    controller = active_run(tmp_path)
    before = controller.journal.events()
    with pytest.raises(RunStoreError, match='positive finite'):
        recover(tmp_path, stale_after_seconds=duration)
    assert controller.journal.events() == before
    assert controller.view().state == 'requested'


@pytest.mark.parametrize('duration', INVALID_DURATION,
                         ids=['nan', 'inf', '-inf', 'zero', 'negative', 'bool', 'overflow'])
def test_invalid_timeout_does_not_create_store(tmp_path, duration):
    store = tmp_path / 'not-created'
    with pytest.raises(RunStoreError, match='positive finite'):
        RunController(store, run_id=RUN, timeout_seconds=duration)
    assert not store.exists()


@pytest.mark.parametrize('field', ['now_seconds', 'last_activity_seconds', 'stale_after_seconds'])
@pytest.mark.parametrize('invalid', [float('nan'), float('inf'), float('-inf'), True])
def test_pure_recovery_rejects_invalid_comparison_inputs(field, invalid):
    view = lifecycle.RunView(RUN, 'b' * 32, 'requested', 0, ('requested',))
    times = dict(now_seconds=1000, last_activity_seconds=990, stale_after_seconds=60)
    times[field] = invalid
    with pytest.raises(lifecycle.LifecycleError, match='finite'):
        lifecycle.recovery_event(view, **times)


@pytest.mark.parametrize('invalid', [float('nan'), float('inf'), float('-inf'), True])
def test_invalid_recovery_clock_preserves_live_journal(tmp_path, invalid):
    controller = active_run(tmp_path)
    before = controller.journal.events()
    with pytest.raises(RunStoreError, match='finite'):
        recover(tmp_path, stale_after_seconds=60, now=invalid)
    assert controller.journal.events() == before


@pytest.mark.parametrize('duration', ['nan', 'inf', '-inf', '0', '-1'])
def test_cli_recovery_rejects_bad_lease_without_abandoning_run(tmp_path, capsys, duration):
    controller = active_run(tmp_path)
    before = controller.journal.events()
    with pytest.raises(SystemExit) as stopped:
        run_cli(['run', 'recover', '--run-store', str(tmp_path), f'--stale-after={duration}'])
    assert stopped.value.code == 2
    assert 'positive finite' in capsys.readouterr().err
    assert controller.journal.events() == before


@pytest.mark.parametrize('duration', ['nan', 'inf', '-inf', '0', '-1'])
def test_cli_check_rejects_bad_timeout_before_git_capture(tmp_path, capsys, duration):
    store = tmp_path / 'not-created'
    with pytest.raises(SystemExit) as stopped:
        run_cli(['check', '--run-store', str(store), f'--timeout-seconds={duration}', '--json'])
    assert stopped.value.code == 2
    assert 'positive finite' in capsys.readouterr().out
    assert not store.exists()


def test_finite_lease_keeps_live_run_and_recovers_only_expired_run(tmp_path):
    controller = active_run(tmp_path)
    activity = controller.journal.last_activity()
    assert recover(tmp_path, stale_after_seconds=60.5, now=activity + 60) == []
    assert recover(tmp_path, stale_after_seconds=60.5, now=activity + 60.5) == [
        {'run_id': RUN, 'from': 'requested', 'to': 'abandoned'}]
