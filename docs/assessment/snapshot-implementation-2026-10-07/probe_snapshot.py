"""Actual local Git capture, filesystem change and in-memory replay controls."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from drift_gate.adapters.cli.runner import run_cli
from drift_gate.adapters.inspection import inspect_snapshot
from drift_gate.adapters.mcp.tools import drift_gate_check_local
from drift_gate.desktop.service import scan_repository


POLICY = '''rules:
  - id: api
    when:
      any_changed: [src/**]
    require:
      groups:
        - name: contract
          any_changed: [docs/api.md]
          content: api-routes
    severity: blocker
'''


def run_probe():
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(prefix='driftgate-snapshot-') as directory:
        root = Path(directory)
        def git(*args):
            return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.PIPE)
        def code(route):
            return f"from fastapi import FastAPI\napp = FastAPI()\n@app.get('{route}')\ndef endpoint(): return {{}}\n"
        git('init'); (root / 'src').mkdir(); (root / 'docs').mkdir()
        (root / '.drift-gate.yml').write_text(POLICY)
        (root / 'src/api.py').write_text(code('/old'))
        (root / 'docs/api.md').write_text('GET /old\n')
        git('add', '.'); git('-c', 'user.name=Control', '-c', 'user.email=control@example.invalid', 'commit', '-m', 'base')
        (root / 'src/api.py').write_text(code('/new'))
        try:
            os.chdir(root)
            stream = io.StringIO()
            with redirect_stdout(stream), redirect_stderr(io.StringIO()):
                try: run_cli(['check', '--base', 'HEAD', '--json'])
                except SystemExit as finished: cli_code = finished.code
            cli = json.loads(stream.getvalue())
            mcp = drift_gate_check_local(mode='full')
            desktop = scan_repository(root)
            first = desktop.result.to_dict()
            snapshot = desktop.result.input_snapshot
            captures = {name: value['execution']['input_capture'] for name, value in
                        [('cli', cli), ('mcp', mcp), ('desktop', first)]}
            expected_source = hashlib.sha256(code('/new').encode()).hexdigest()
            source_entry = next(entry for entry in captures['desktop']['artifacts']
                                if entry['path'] == 'src/api.py' and entry['role'] == 'after-source')
            (root / 'src/api.py').write_text(code('/later'))
            (root / 'docs/api.md').write_text('GET /later\n')
            later = scan_repository(root).result.to_dict()
            # Cleanup happens while the private capsule remains alive.
            os.chdir(previous)
            shutil.rmtree(root)
            replay = inspect_snapshot(snapshot).to_dict()
            keys = ('result', 'verification', 'rule_decisions', 'summary')
            checks = {
                'local_entrypoint_manifests_equal': all(value == captures['cli'] for value in captures.values()),
                'captured_source_digest_matches_control': source_entry['observed_text_sha256'] == expected_source,
                'stale_then_updated_gate': first['result'] == 'fail' and later['result'] == 'pass' and cli_code == 1,
                'replay_after_repository_deleted': all(replay[key] == first[key] for key in keys),
                'replay_capture_identity_unchanged': replay['execution']['input_capture'] == captures['desktop'],
                'new_attempt_identity': replay['execution']['run_id'] != first['execution']['run_id'],
                'new_checkout_input_digest_changed': later['execution']['input_capture']['input_sha256'] != captures['desktop']['input_sha256'],
                'no_authenticity_or_selection_claim': all(not captures['desktop'][key] for key in
                    ('original_bytes_certified', 'revision_certified', 'selection_complete')),
            }
            return {'schema': 'snapshot-local-controls-v1',
                    'scope': 'Authored nonblind local Git controls; no remote CI, installer or input authenticity certification',
                    'checks': checks, 'passed': sum(checks.values()), 'total': len(checks),
                    'control_sources': {'before': code('/old'), 'captured': code('/new'), 'later': code('/later')},
                    'captures': captures, 'first': {key: first[key] for key in keys},
                    'later': {key: later[key] for key in keys}, 'replay': {key: replay[key] for key in keys}}
        finally:
            os.chdir(previous)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(); result = run_probe()
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(result['checks']))
    raise SystemExit(0 if result['passed'] == result['total'] else 1)


if __name__ == '__main__':
    main()
