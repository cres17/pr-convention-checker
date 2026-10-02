"""Conflicting editors and separate processes must never silently lose edits."""
from copy import deepcopy
import multiprocessing

import pytest

from drift_gate.desktop.progress_service import (
    BaselineConflict, extract_requirements, load_baseline, save_baseline,
)
from drift_gate.desktop.store_lock import store_lock
from drift_gate.tests.test_progress_service import project


def _writer(root, data, payload, barrier, results):
    barrier.wait(timeout=15)
    try:
        result = save_baseline(root, data, payload)
        results.put(('saved', result['version']))
    except BaselineConflict as exc:
        results.put(('conflict', exc.baseline['version']))


def test_stale_editor_cannot_erase_another_edit_and_identical_retry_is_safe(tmp_path):
    root = project(tmp_path)
    data = tmp_path / 'data'
    first = save_baseline(root, data, extract_requirements(root, ['README.md']))
    left, right = deepcopy(first), deepcopy(first)
    left['requirements'][0]['criterion'] = '첫 편집기의 완료 조건'
    second = save_baseline(root, data, left)
    right['requirements'][1]['criterion'] = '다른 편집기의 완료 조건'
    with pytest.raises(BaselineConflict) as failure:
        save_baseline(root, data, right)
    assert failure.value.baseline == second == load_baseline(root, data)
    # A lost reply can be retried without a false conflict or another version.
    retry = deepcopy(second)
    retry['version'] = first['version']
    assert save_baseline(root, data, retry) == second
    right.pop('version')
    with pytest.raises(BaselineConflict):
        save_baseline(root, data, right)
    assert load_baseline(root, data) == second


@pytest.mark.parametrize('existing', [False, True])
def test_separate_process_writers_check_version_inside_the_same_lock(tmp_path, existing):
    root = project(tmp_path)
    data = tmp_path / 'data'
    base = extract_requirements(root, ['README.md'])
    if existing:
        base = save_baseline(root, data, base)
    left, right = deepcopy(base), deepcopy(base)
    left['requirements'][0]['title'] = '첫 창의 편집'
    right['requirements'][1]['title'] = '다른 창의 편집'
    context = multiprocessing.get_context('spawn')
    barrier, results = context.Barrier(3), context.Queue()
    processes = [context.Process(target=_writer, args=(root, data, draft, barrier, results))
                 for draft in (left, right)]
    try:
        for process in processes:
            process.start()
        barrier.wait(timeout=15)
        for process in processes:
            process.join(timeout=15)
            assert process.exitcode == 0
        outcome = [results.get(timeout=2) for _ in processes]
        assert sorted(status for status, _ in outcome) == ['conflict', 'saved']
        expected = 2 if existing else 1
        assert all(version == expected for _, version in outcome)
        assert load_baseline(root, data)['version'] == expected
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        results.close()
        results.join_thread()


def test_lock_timeout_and_exception_release(tmp_path):
    target = tmp_path / 'baseline.json'
    with store_lock(target):
        with pytest.raises(TimeoutError):
            with store_lock(target, timeout=0.05):
                pytest.fail('Another writer entered the transaction')
    with pytest.raises(ValueError):
        with store_lock(target):
            raise ValueError('failed validation')
    with store_lock(target, timeout=0.05):
        pass
