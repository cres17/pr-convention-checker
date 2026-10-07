"""Read-only product probes for the enterprise design; writes a NEW receipt only.

Runs authored fixtures in temporary Git repositories and transpiles an authored
TypeScript snippet. Does not execute target repository application code.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.audit_auto_contracts import evaluate_case
from drift_gate.adapters.ast.express_routes import extract_express_routes
from drift_gate.core.evaluation.api_schema import UnsupportedContract
from drift_gate.core.evaluation.openapi_document import load_openapi


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def policy(mode):
    return {'rules': [{'id': 'route-duty', 'severity': 'blocker',
                      'when': {'any_changed': ['src/**']},
                      'require': {'groups': [{'name': 'API',
                                             'all_changed': ['openapi.json'],
                                             'content': mode}]}}],
            'gate': {'on_unverified': 'fail'}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('refusing to replace existing evidence')
    module = ('from fastapi import FastAPI\nimport os\n'
              'setting = os.getenv("EXISTING_KEY")\napp = FastAPI()\n'
              '@app.get("/old")\ndef endpoint():\n    return {}\n')
    stale = json.dumps({'openapi': '3.1.0', 'paths': {'/old': {'get': {'responses': {}}}}})
    cases = []
    for mode, env in [('auto-strict', True), ('api-routes', True), ('auto-strict', False)]:
        before = module if env else module.replace('import os\nsetting = os.getenv("EXISTING_KEY")\n', '')
        after = before.replace('"/old"', '"/new"')
        case = {'id': f'{mode}-env-{env}', 'before': {'src/api.py': before, 'openapi.json': stale},
                'after': {'src/api.py': after}, 'policy': policy(mode), 'facts_kind': 'routes',
                'expected': {'facts': {'added': ['GET /new'], 'removed': ['GET /old']}}}
        cases.append({'input': case, 'observed': evaluate_case(case)})

    imports = ["import type express from 'express';", "import /* retained comment */ type express from 'express';",
               "import express from 'express';"]
    express = []
    ts_module = ROOT / 'desktop-ui/node_modules/typescript'
    for prefix in imports:
        source = prefix + "\nconst app = express();\napp.get('/catalog', (req, res) => res.end());\n"
        try:
            routes = sorted([list(route) for route in extract_express_routes(source, 'typescript')])
            observed = {'outcome': 'accepted', 'routes': routes}
        except UnsupportedContract as exc:
            observed = {'outcome': 'unknown', 'reason': str(exc)}
        compiler = None
        if ts_module.exists():
            program = ("const ts = require(process.argv[1]);"
                       "let source = ''; process.stdin.on('data', x => source += x);"
                       "process.stdin.on('end', () => {const result = ts.transpileModule(source,"
                       "{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022},reportDiagnostics:true});"
                       "process.stdout.write(JSON.stringify({version:ts.version,output:result.outputText,"
                       "diagnostics:result.diagnostics.map(d=>d.code)}));});")
            compiler = json.loads(subprocess.check_output(['node', '-e', program, str(ts_module)], input=source.encode(), cwd=ROOT))
        api_doc = json.dumps({'openapi': '3.1.0', 'paths': {'/catalog': {'get': {'responses': {}}}}})
        gate_case = {'id': f'express-import-{len(express)}',
                     'before': {'src/api.ts': source.replace('/catalog', '/old'), 'openapi.json': stale},
                     'after': {'src/api.ts': source, 'openapi.json': api_doc},
                     'policy': policy('api-routes'), 'facts_kind': 'routes', 'expected': {}}
        express.append({'source': source, 'analyzer': observed, 'transpile_only_oracle': compiler,
                        'gate_input': gate_case, 'gate_observation': evaluate_case(gate_case)})

    numeric = []
    for value in ['1', 'NaN', '1e999']:
        text = '{"openapi":"3.1.0","paths":{},"x-number":' + value + '}'
        try:
            parsed = load_openapi(text)
            row = {'outcome': 'accepted', 'finite': math.isfinite(parsed['x-number'])}
        except UnsupportedContract as exc:
            row = {'outcome': 'unknown', 'reason': str(exc)}
        numeric.append({'input': text, 'observed': row})

    prior_path = ROOT / 'docs/assessment/auto-update-2026-10-07/verification-final.json'
    prior = json.loads(prior_path.read_text())
    prior_match = {}
    for section in ['source_hashes', 'input_hashes', 'test_hashes', 'evidence_hashes']:
        entries = prior[section]
        mismatches = [name for name, expected in entries.items()
                      if not (ROOT / name).is_file() or sha(ROOT / name) != expected]
        prior_match[section] = {'total': len(entries), 'mismatches': mismatches}
    result = {'schema': 'enterprise-design-probes-v1', 'started_at': datetime.now(timezone.utc).isoformat(),
              'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'state': 'uncommitted worktree; previous receipt hash comparison identifies operating inputs',
              'platform': platform.platform(), 'python': platform.python_version(),
              'prior_receipt_sha256': sha(prior_path), 'prior_receipt_comparison': prior_match,
              'mixed_contract_dispatch': cases, 'express_type_imports': express,
              'json_numeric_domain': numeric,
              'limitations': ['Three authored defect probes with controls, not a blind benchmark.',
                              'No full regression rerun, remote CI, native installer or OS matrix.',
                              'TypeScript transpileModule erasure observation is not a typecheck or HTTP execution.'],
              'reproducer_sha256': sha(Path(__file__))}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'prior_receipt_comparison': prior_match,
                      'mixed_contract_dispatch': [{'id': row['input']['id'], 'actual': row['observed']['actual']} for row in cases],
                      'express_type_imports': [row['analyzer'] for row in express],
                      'json_numeric_domain': numeric}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
