"""Reproduce the focused preset through Git objects, the CLI and stored replay.

These are authored control fixtures, not independent holdout accuracy. Temporary
repositories and evidence are cleaned up after use; the JSON report retains
subjects, decisions, reasons and replay verification, never secret values.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from drift_gate.adapters.cli.presets import POLICY_PRESETS
from drift_gate.adapters.evidence_bundle import load_bundle
from drift_gate.adapters.execution import atomic_json


POLICY = POLICY_PRESETS['focused-python']
CONFIG = 'import os\nexisting = os.getenv("EXISTING")\n'
API = ('from fastapi import FastAPI\napp = FastAPI()\n'
       '@app.get("/old")\ndef handler():\n    return {"status": "ok"}\n')


def openapi(*paths):
    return json.dumps({'openapi': '3.1.0', 'info': {'title': 'fixture', 'version': '1'},
        'paths': {path: {'get': {'responses': {'200': {'description': 'ok'}}}} for path in paths}}) + '\n'


def git(root, *args):
    return subprocess.check_output(['git', '-c', 'core.autocrlf=false', *args], cwd=root,
                                   stderr=subprocess.PIPE).decode().strip()


def commit(root, files, message):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8', newline='\n')
    git(root, 'add', '-A')
    git(root, '-c', 'user.name=Focused fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', message)
    return git(root, 'rev-parse', 'HEAD')


def scenarios():
    new_config = CONFIG + 'billing = os.getenv("BILLING_TOKEN")\n'
    new_api = API.replace('/old', '/new')
    added_api = API + '@app.get("/new")\ndef added_handler():\n    return {"status": "ok"}\n'
    dynamic_config = CONFIG + 'key = "BILLING_" + suffix\nbilling = os.getenv(key)\n'
    dynamic_api = API.replace('@app.get("/old")', 'path = "/" + suffix\n@app.get(path)')
    return [
        ('env-missing', {}, {'src/config/settings.py': new_config}, 'env-sample-content', 'violated', 'block'),
        ('env-fixed', {}, {'src/config/settings.py': new_config, '.env.example': 'EXISTING=\nBILLING_TOKEN=\n'},
         'env-sample-content', 'satisfied', 'allow'),
        ('env-already-documented', {'.env.example': 'EXISTING=\nBILLING_TOKEN=\n'},
         {'src/config/settings.py': new_config}, 'env-sample-content', 'satisfied', 'allow'),
        ('env-dynamic', {}, {'src/config/settings.py': dynamic_config}, 'env-sample-content', 'undetermined', 'review'),
        ('api-missing', {}, {'src/api/app.py': new_api}, 'api-route-content', 'violated', 'block'),
        ('api-fixed', {}, {'src/api/app.py': new_api, 'docs/openapi.json': openapi('/new')},
         'api-route-content', 'satisfied', 'allow'),
        ('api-already-documented', {'docs/openapi.json': openapi('/old', '/new')},
         {'src/api/app.py': added_api}, 'api-route-content', 'satisfied', 'allow'),
        ('api-dynamic', {}, {'src/api/app.py': dynamic_api}, 'api-route-content', 'undetermined', 'review'),
        ('api-unreadable-document', {}, {'src/api/app.py': new_api, 'docs/openapi.json': '{broken'},
         'api-route-content', 'undetermined', 'review'),
        ('env-no-new-key', {}, {'src/config/settings.py': CONFIG.replace('"EXISTING")', '"EXISTING", "default")')},
         'env-sample-content', 'not-applicable', 'allow'),
        ('known-violation-with-open-scope', {},
         {'src/config/settings.py': new_config, 'src/api/app.py': dynamic_api},
         'env-sample-content', 'violated', 'block'),
    ]


def run_scenarios():
    rows = []
    with TemporaryDirectory(prefix='driftgate-focused-') as temporary:
        workspace = Path(temporary)
        for name, base_files, updates, rule_id, decision, action in scenarios():
            root = workspace / name
            root.mkdir()
            git(root, 'init', '-q')
            base = commit(root, {'.drift-gate.yml': POLICY, 'src/config/settings.py': CONFIG,
                '.env.example': 'EXISTING=\n', 'src/api/app.py': API, 'docs/openapi.json': openapi('/old'),
                **base_files}, 'before')
            head = commit(root, updates, 'after')
            command = [sys.executable, '-I', '-m', 'drift_gate', 'check', '--base', base, '--head', head,
                '--policy', '.drift-gate.yml', '--trusted-policy-ref', base,
                '--trusted-policy-sha256', sha256(POLICY.encode()).hexdigest(),
                '--evidence-store', str(workspace / (name + '-evidence')), '--anthropic-api-key', '', '--json']
            process = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=60)
            output = json.loads(process.stdout)
            if 'error' in output:
                raise RuntimeError(f'{name}: {output["error"]}')
            actual = next(row for row in output['rule_decisions'] if row['rule_id'] == rule_id)
            expected_code = 1 if action == 'block' else 0
            reference = output['execution']['evidence_bundle']
            bundle = load_bundle(reference['path'], expected_receipt_sha256=reference['receipt_sha256'])
            replay = bundle.replay()
            replay_matches = replay.execution['bundle_replay']['recorded_result_matches_current']
            valid = (actual['decision'] == decision and output['enforcement']['action'] == action
                     and process.returncode == expected_code and replay_matches)
            rows.append({'case_id': name, 'subject': {'base': base, 'head': head},
                'rule': rule_id, 'expected': {'decision': decision, 'action': action, 'exit': expected_code},
                'observed': {'decision': actual['decision'], 'verification': actual['verification'],
                             'action': output['enforcement']['action'], 'exit': process.returncode,
                             'groups': actual['satisfied_groups'] + actual['unsatisfied_groups']},
                'input_sha256': output['execution']['input_sha256'], 'receipt_sha256': reference['receipt_sha256'],
                'replay_matches': replay_matches, 'passed': valid})
    return {'schema': 'focused-flow-check-v1', 'basis': 'author-created control fixtures; not holdout accuracy',
            'policy_sha256': sha256(POLICY.encode()).hexdigest(),
            'temporary_evidence_retained': False, 'passed': all(row['passed'] for row in rows), 'cases': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, help='JSON report path')
    args = parser.parse_args()
    result = run_scenarios()
    atomic_json(args.out, result)
    print(json.dumps({'passed': result['passed'], 'cases': len(result['cases']), 'report': str(Path(args.out).resolve())}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
