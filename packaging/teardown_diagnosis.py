"""Repeat the packaged UI check and record each run's shutdown trace (design W16, Intel Qt exit).

Each run uses a fresh fixture and settings directory, ``DRIFT_GATE_TEARDOWN_TRACE``
and the same network block as the package verifier. The script records exit
codes, durations, the last trace events and any faulthandler stack. It never
retries a failed run into a pass: every attempt is kept. Exit status is 0 so the
diagnosis is preserved; the regular verification step stays the gate.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_package import fixture, network_block  # noqa: E402


def attempt(executable, output, index):
    run_dir = output / f'run-{index:02d}'
    run_dir.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='driftgate-teardown-') as temporary:
        root = Path(temporary)
        fixture(root / 'fixture')
        cache = root / 'empty-parser-cache'
        cache.mkdir()
        trace = run_dir / 'teardown-trace.txt'
        env = {**os.environ, 'DRIFT_GATE_PACKAGE_CHECK_ID': uuid.uuid4().hex,
               'TREE_SITTER_LANGUAGE_PACK_CACHE_DIR': str(cache),
               'TREE_SITTER_LANGUAGE_PACK_LIBS_DIR': str(root / 'absent-user-libraries'),
               'QT_QPA_PLATFORM': 'offscreen', 'QTWEBENGINE_CHROMIUM_FLAGS': '--no-sandbox --disable-gpu',
               'DRIFT_GATE_TEARDOWN_TRACE': str(trace)}
        started = time.monotonic()
        with network_block(executable, run_dir) as (prefix, _):
            with (run_dir / 'app.log').open('wb') as log:
                process = subprocess.Popen([*prefix, str(executable), '--verify-package', str(root / 'fixture'),
                                            str(run_dir / 'result.json')], env=env, cwd=str(root),
                                           stdout=log, stderr=subprocess.STDOUT)
                try:
                    code = process.wait(timeout=90)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(); code = 'timeout'
    events = trace.read_text(encoding='utf-8', errors='replace').splitlines() if trace.exists() else []
    stack = [line for line in events if 'Fatal Python error' in line or line.startswith(('Thread', 'Current thread'))]
    reached = [line.split()[2] for line in events if len(line.split()) > 2]
    return {'run': index, 'exit_code': code, 'seconds': round(time.monotonic() - started, 2),
            'last_events': reached[-6:], 'faulthandler_lines': stack[:20],
            'result_written': (run_dir / 'result.json').exists(),
            'crashed_after_event_loop': 'event-loop-returned' in reached and code not in (0, 1)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path)
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--output', type=Path, default=Path('build/teardown-diagnosis'))
    args = parser.parse_args()
    executable = args.executable.resolve(strict=True)
    args.output.mkdir(parents=True, exist_ok=False)
    runs = [attempt(executable, args.output, index) for index in range(1, args.runs + 1)]
    codes = {}
    for row in runs:
        codes[str(row['exit_code'])] = codes.get(str(row['exit_code']), 0) + 1
    summary = {'schema': 'qt-teardown-diagnosis-v1', 'platform': sys.platform, 'executable': str(executable),
               'runs': runs, 'exit_codes': codes,
               'nonzero_runs': [row['run'] for row in runs if row['exit_code'] != 0],
               'crash_phase': sorted({row['last_events'][-1] if row['last_events'] else 'before-trace'
                                      for row in runs if row['exit_code'] not in (0,)}),
               'interpretation': 'observation only; a clean set of runs does not prove the earlier failure is fixed'}
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps({'exit_codes': codes, 'nonzero_runs': summary['nonzero_runs']}))


if __name__ == '__main__':
    main()
