"""Trace production calls while running an existing behavior assertion test."""
import argparse
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
TEST = 'test_recreated_same_version_baseline_rejects_old_editor_and_preserves_new_edits'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Output already exists; use a new path')
    calls = []

    def profile(frame, event, _arg):
        if event == 'call' and frame.f_code.co_filename.endswith('/desktop/progress_context.py'):
            calls.append(frame.f_code.co_name)

    sys.setprofile(profile)
    try:
        code = pytest.main(['-q', str(ROOT / 'drift_gate/tests/test_progress_service.py') + '::' + TEST])
    finally:
        sys.setprofile(None)
    result = {'pytest_exit_code': int(code), 'test': TEST,
              'production_functions_executed': sorted(set(calls)),
              'baseline_id_call_count': calls.count('baseline_id')}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, indent=2)
        handle.write('\n')
    print(json.dumps(result))
    raise SystemExit(code)


if __name__ == '__main__':
    main()
