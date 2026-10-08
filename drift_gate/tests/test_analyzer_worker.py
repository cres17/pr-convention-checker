"""W12 worker isolation: timeout, cancel, crash, bad and oversized output, parser failure, queue, cleanup."""
import os
import subprocess
import sys
import threading
import time

import pytest

from drift_gate.adapters.analyzer_worker import WorkerPool, run_job

SOURCE = 'from fastapi import FastAPI\nimport os\napp = FastAPI()\n@app.get("/a")\ndef a():\n    return os.getenv("KEY")\n'
TEST = {'test_ops': True}


def test_analysis_ops_return_bound_results():
    routes = run_job('python-routes', SOURCE)
    assert (routes.status, routes.value) == ('ok', [['GET', '/a']])
    env = run_job('python-env', SOURCE)
    assert (env.status, env.value) == ('ok', ['KEY'])
    nodes = run_job('tree-sitter-nodes', SOURCE)
    assert nodes.status == 'ok' and nodes.value['nodes'] > 10 and nodes.value['has_error'] is False


def test_timeout_discards_late_reply_and_cancel_kills():
    result = run_job('sleep', '', limits={'timeout_seconds': 0.5}, extra={**TEST, 'payload': {'seconds': 30}})
    assert result.status == 'timeout' and result.value is None and result.elapsed_seconds < 10
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    assert run_job('sleep', '', cancel=cancel, extra={**TEST, 'payload': {'seconds': 30}}).status == 'cancelled'


def test_crash_bad_output_oversized_output_and_parser_failure():
    assert run_job('crash', '', extra=TEST).status == 'crash'
    assert run_job('bad-output', '', extra=TEST).status == 'invalid-output'
    flood = run_job('flood', '', limits={'max_output_bytes': 100_000}, extra={**TEST, 'payload': {'bytes': 5_000_000}})
    assert flood.status == 'oversized-output'
    parser = run_job('parser-init', '', extra=TEST)
    assert parser.status == 'failed'


def test_python_level_network_file_and_process_guards(tmp_path):
    assert 'blocked' in run_job('net', '', extra=TEST).detail
    secret = tmp_path / 'secret.txt'
    secret.write_text('token')
    assert 'blocked' in run_job('read-file', '', extra={**TEST, 'payload': {'path': str(secret)}}).detail


def test_test_ops_are_refused_without_the_explicit_flag():
    assert run_job('crash', '').status == 'crash'  # exit 64 from the refusal, not an abort
    assert 'exit 64' in run_job('sleep', '').detail


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='RLIMIT_AS is enforced on Linux only')
def test_memory_limit_is_enforced_on_linux():
    result = run_job('alloc', '', limits={'max_memory_bytes': 400_000_000},
                     extra={**TEST, 'payload': {'bytes': 800_000_000}})
    assert (result.status, result.detail) == ('failed', 'memory-limit')


@pytest.mark.skipif(os.name != 'posix', reason='process-group kill is POSIX')
def test_timeout_also_ends_grandchildren():
    marker = f'61.{os.getpid()}{int(time.time()) % 1000}'
    result = run_job('spawn-child', '', limits={'timeout_seconds': 1.5}, extra={**TEST, 'payload': {'marker': marker}})
    assert result.status == 'timeout'
    time.sleep(0.5)
    found = subprocess.run(['pgrep', '-f', f'time.sleep({marker})'], capture_output=True, text=True)
    assert found.stdout.strip() == ''


def test_queue_saturation_is_rejected_not_buffered():
    pool = WorkerPool(max_workers=1, max_queue=0, limits={'timeout_seconds': 5})
    first = pool.submit('sleep', '', extra={**TEST, 'payload': {'seconds': 1}})
    assert first is not None
    assert pool.run('python-env', SOURCE).status == 'queue-full'
    first[1].wait()
    assert pool.run('python-env', SOURCE).status == 'ok'
