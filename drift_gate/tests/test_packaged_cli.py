"""W16: headless CLI inside the packaged app and Qt teardown tracing.

The packaged check itself runs in the desktop workflow against the built
executable; here the same verifier drives a wrapper that enters through the
packaged app's ``--cli`` path, so the verifier and the entry point are tested
without PyInstaller.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from drift_gate.desktop.cli_entry import run_cli_passthrough

ROOT = Path(__file__).resolve().parents[2]


def test_non_cli_arguments_are_left_to_the_ui():
    assert run_cli_passthrough(['DriftGate']) is None
    assert run_cli_passthrough(['DriftGate', '--verify-package', 'a', 'b']) is None


@pytest.mark.skipif(os.name == 'nt', reason='the wrapper executable is a POSIX shell script')
def test_package_cli_verifier_through_the_cli_entry(tmp_path):
    wrapper = tmp_path / 'DriftGate'
    entry = ("import sys; from drift_gate.desktop.cli_entry import run_cli_passthrough; "
             "sys.exit(run_cli_passthrough(['DriftGate'] + sys.argv[1:]))")
    wrapper.write_text(f'#!/bin/sh\nexport PYTHONPATH="{ROOT}"\nexec "{sys.executable}" -c "{entry}" "$@"\n')
    wrapper.chmod(0o755)
    completed = subprocess.run([sys.executable, str(ROOT / 'packaging/verify_package_cli.py'), str(wrapper),
                                '--output', str(tmp_path / 'out')], capture_output=True, text=True, timeout=600)
    assert completed.returncode == 0, completed.stderr[-2000:]
    result = json.loads((tmp_path / 'out/result.json').read_text())
    assert result['gate_result'] == 'fail' and result['replay_matches'] and result['repository_deleted_before_replay']
    assert result['run_history'][-1] == 'publication-skipped' and result['spans_verified'] > 0
    assert [step['step'] for step in result['steps']] == ['check-with-evidence-and-journal', 'bundle-verify',
                                                         'bundle-replay', 'bundle-spans']


def test_teardown_trace_records_events_and_enables_faulthandler(tmp_path):
    trace = tmp_path / 'trace.txt'
    code = ("from drift_gate.desktop.cli_entry import trace; trace('main-start', argv=1); "
            "trace('event-loop-returned', code=0); import faulthandler; print(faulthandler.is_enabled())")
    completed = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, cwd=ROOT,
                               env={**os.environ, 'DRIFT_GATE_TEARDOWN_TRACE': str(trace)}, timeout=60)
    assert completed.returncode == 0 and completed.stdout.strip() == 'True'
    events = [line.split()[2] for line in trace.read_text().splitlines()]
    assert events == ['main-start', 'event-loop-returned', 'atexit']
    untraced = subprocess.run([sys.executable, '-c', "from drift_gate.desktop.cli_entry import trace; trace('x')"],
                              cwd=ROOT, env={k: v for k, v in os.environ.items() if k != 'DRIFT_GATE_TEARDOWN_TRACE'},
                              capture_output=True, timeout=60)
    assert untraced.returncode == 0


@pytest.mark.skipif(os.name == 'nt', reason='the fake executable is a POSIX shell script')
def test_teardown_diagnosis_records_every_run_with_a_relative_output(tmp_path, monkeypatch):
    from contextlib import contextmanager
    import importlib.util
    spec = importlib.util.spec_from_file_location('teardown_diagnosis', ROOT / 'packaging/teardown_diagnosis.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    @contextmanager
    def no_block(executable, directory):
        assert directory.is_absolute()  # the run's cwd is a temporary directory, not the caller's
        yield [], 'test: no network block'

    monkeypatch.setattr(module, 'network_block', no_block)
    counter = tmp_path / 'count'
    fake = tmp_path / 'DriftGate'
    fake.write_text('#!/bin/sh\n'
                    f'n=$(cat "{counter}" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "{counter}"\n'
                    'echo "1.0 pid=1 main-start " >> "$DRIFT_GATE_TEARDOWN_TRACE"\n'
                    'echo "2.0 pid=1 event-loop-returned code=0" >> "$DRIFT_GATE_TEARDOWN_TRACE"\n'
                    '[ "$n" = 2 ] && exit 134\nexit 0\n')
    fake.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['teardown_diagnosis.py', str(fake), '--runs', '3', '--output', 'diag'])
    module.main()
    summary = json.loads((tmp_path / 'diag/summary.json').read_text())
    assert summary['exit_codes'] == {'0': 2, '134': 1} and summary['nonzero_runs'] == [2]
    assert summary['crash_phase'] == ['event-loop-returned'] and summary['runs_without_trace'] == []
    assert summary['runs'][1]['crashed_after_event_loop']
