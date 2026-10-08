"""Adversarial review probes. Run with 791565f installed and jsonschema 4.26.0.

No source edits; all mutable inputs and repositories live in a temporary directory.
These are authored regression counterexamples, not a blind accuracy evaluation.
"""
import copy
import io
import json
import tempfile
import zipfile
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

from jsonschema import Draft202012Validator
from drift_gate.adapters import holdout as h
from drift_gate.adapters.analysis_cache import AnalysisCache, key_inputs
from drift_gate.adapters.cli.runner import run_cli
from drift_gate.adapters.inspection import inspect
from drift_gate.adapters.org_service import OrgService, OrgError
from drift_gate.core.contracts.dependency import build_graph, impact
from drift_gate.core.evaluation.compatibility import compare_documents
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.input_manifest import canonical_bytes
from drift_gate.core.policy.loader import load_policy_from_dict

RESULTS = {}

def document(schema, status='200'):
    return {'openapi': '3.1.0', 'info': {'title': 'probe', 'version': '1'},
            'paths': {'/x': {'get': {'responses': {status: {
                'description': 'response', 'content': {'application/json': {'schema': schema}}}}}}}}

def compatibility_case(name, old, new, witness):
    before, after = document(old), document(new)
    policy = load_policy_from_dict({'rules': [{'id': 'compat', 'when': {'any_changed': ['openapi.json']},
        'require': {'groups': [{'name': 'compatible', 'any_changed': ['openapi.json'],
                               'content': 'api-compatibility', 'direction': 'response'}]}, 'severity': 'blocker'}]})
    gate = inspect(changed_files=[ChangedFile(path='openapi.json', status='modified',
        patch='@@ -1 +1 @@\n-' + json.dumps(before) + '\n+' + json.dumps(after) + '\n',
        before_source=json.dumps(before), after_source=json.dumps(after))], policy=policy)
    RESULTS[name] = {'old': old, 'new': new, 'witness': witness,
        'oracle_old_accepts': Draft202012Validator(old).is_valid(witness),
        'oracle_new_accepts': Draft202012Validator(new).is_valid(witness),
        'comparison': compare_documents(before, after, 'response').to_dict(), 'actual_gate': gate.result}

def main(root):
    compatibility_case('oneof_overlap', {'oneOf': [{'type': 'number'}, {'type': 'integer'}]},
                       {'type': 'integer'}, 1)
    compatibility_case('allof_additional_properties', {'allOf': [
        {'type': 'object', 'properties': {'a': {'type': 'string'}}, 'additionalProperties': False},
        {'type': 'object', 'properties': {'b': {'type': 'string'}}, 'additionalProperties': False}]},
        {'type': 'object', 'properties': {'a': {'type': 'string'}, 'b': {'type': 'string'}},
         'additionalProperties': False}, {'a': 'x'})
    RESULTS['default_response'] = compare_documents(document({'type': 'string'}, 'default'),
        document({'type': 'integer'}, '200'), 'response').to_dict()
    old = document({'type': 'string'})
    new = copy.deepcopy(old)
    new['paths']['/x']['parameters'] = [{'name': 'tenant', 'in': 'query', 'required': True,
                                       'schema': {'type': 'string'}}]
    RESULTS['path_item_required_parameter'] = compare_documents(old, new, 'request').to_dict()

    sources = {'app.js': 'export async function run() { return import("./dep.js"); }\n',
               'dep.js': 'export const x = 1;\n'}
    graph = build_graph(sources)
    RESULTS['literal_dynamic_import'] = impact(graph, graph, ['dep.js']).to_dict()
    control = build_graph({**sources, 'app.js': 'import {x} from "./dep.js";\n'})
    RESULTS['static_import_control'] = impact(control, control, ['dep.js']).to_dict()

    cache = AnalysisCache(root / 'cache')
    inputs = key_inputs(artifact_sha256='a' * 64, op='python-env', profile=('python-env-literals', '1'),
                        engine_sha256='b' * 64, parser_sha256='c' * 64)
    cache.put(inputs, status='complete', value=['SECRET_KEY'])
    entry_path = next((root / 'cache').rglob('*.json'))
    entry = json.loads(entry_path.read_bytes())
    entry['value'] = []
    entry_path.write_bytes(canonical_bytes(entry))
    read = cache.get(inputs)
    RESULTS['cache_value_tamper'] = {'value_after_tamper': read['value'] if read else None, 'stats': cache.stats()}

    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    service = OrgService(root / 'org', clock=lambda: now[0])
    service.create_tenant('tenant', admin_id='admin', retention_days=1)
    service.add_principal('admin', 'tenant', 'limited', roles=['admin'], scopes=['org/A'])
    result_id = service.store_result('admin', 'tenant', 'org/B', {'marker': 'outside-scope-B'})
    try:
        service.get_result('limited', 'tenant', result_id)
        denied = False
    except OrgError:
        denied = True
    archive = root / 'backup.zip'
    service.backup('limited', 'tenant', archive)
    with zipfile.ZipFile(archive) as z:
        leaked = any(b'outside-scope-B' in z.read(name) for name in z.namelist())
    now[0] += timedelta(days=2)
    removed = service.purge('limited', 'tenant')
    service.add_principal('limited', 'tenant', 'escalated', roles=['admin'], scopes=['*'])
    RESULTS['org_scope'] = {'direct_read_denied_control': denied, 'backup_contains_out_of_scope_result': leaked,
        'purge_deletes_out_of_scope_result': result_id in removed,
        'limited_admin_created_wildcard_admin': True}

    # Score labels from an entirely different frozen input with colliding case IDs.
    def make_case(route, doc):
        source = lambda r: f'from fastapi import FastAPI\napp=FastAPI()\n@app.get("{r}")\ndef h():\n    return 1\n'
        return {'case_id': 'shared-id', 'repository': 'org/repo', 'source_family': 'family',
            'policy': {'rules': [{'id': 'api', 'when': {'any_changed': ['src/**']},
                'require': {'groups': [{'name': 'docs', 'any_changed': ['docs/api.md'], 'content': 'api-routes'}]},
                'severity': 'blocker'}]},
            'changed_files': [{'path': 'src/api.py', 'status': 'modified', 'patch': '@@\n-x\n+y\n',
                'before_source': source('/old'), 'after_source': source(route)},
                {'path': 'docs/api.md', 'status': 'modified', 'patch': '@@\n+GET /new\n',
                 'after_source': doc, 'document_input_state': 'available'}],
            'expected': {'gate': 'pass', 'rules': {'api': {'decision': 'satisfied', 'support': 'supported'}}}}
    a = h.freeze({'schema': h.CASES, 'split': 'holdout', 'cases': [make_case('/new', 'GET /new\n')]}, protocol='A')
    b = h.freeze({'schema': h.CASES, 'split': 'holdout', 'cases': [make_case('/different', 'GET /stale\n')]}, protocol='B')
    packet = h.review_packet(b, instructions='review B')
    reviews = [{'item_id': item['item_id'], 'reviewer_id': reviewer, 'reviewer_kind': 'llm-proxy',
                'label': 'violated' if item['kind'] == 'rule' else 'fail'}
               for item in packet['items'] for reviewer in ('r1', 'r2')]
    labels = h.adjudicate(packet, reviews)
    results = h.run_frozen(a, sha256(canonical_bytes(a)).hexdigest())
    rp, lp, out = root / 'results.json', root / 'labels.json', root / 'metrics.json'
    rsha, lsha = h.write_once(rp, results), h.write_once(lp, labels)
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        try:
            run_cli(['holdout', 'score', '--results', str(rp), '--results-sha256', rsha,
                     '--labels', str(lp), '--labels-sha256', lsha, '--out', str(out)])
        except SystemExit as exc:
            exit_code = exc.code
    RESULTS['holdout_cross_input_labels'] = {'exit_code': exit_code, 'cli': json.loads(stdout.getvalue()),
        'source_A_sha256': sha256(canonical_bytes(a)).hexdigest(),
        'source_B_sha256': sha256(canonical_bytes(b)).hexdigest(),
        'both_file_pins_correct': True, 'metrics_written': out.exists(),
        'results_gate_A': results['cases'][0]['gate'], 'reviewed_gate_B': 'fail',
        'labels_fields': sorted(labels)}

    # The production inspection adapter enriches Express facts; the holdout runner does not.
    case = make_case('/new', 'GET /v1/products\n')
    js = ('import express from "express";\nconst app=express();\nconst router=express.Router();\n'
          'function handler(req,res) { res.send("ok"); }\n'
          'router.route("/catalog").get(handler);\napp.use("/v1",router);\n')
    case['changed_files'][0] = {'path': 'src/api.js', 'status': 'modified',
        'patch': '@@\n-router.route("/catalog").get(handler);\n+router.route("/products").get(handler);\n',
        'before_source': js, 'after_source': js.replace('/catalog', '/products')}
    prod = inspect(changed_files=[h._changed_file(f) for f in case['changed_files']],
                   policy=load_policy_from_dict(case['policy']))
    held = h.run_frozen(h.freeze({'schema': h.CASES, 'split': 'holdout', 'cases': [case]}, protocol='express'), 'e'*64)
    RESULTS['holdout_express_equivalence'] = {'production_gate': prod.result,
        'production_rules': [d.status for d in prod.rule_decisions], 'holdout': held['cases'], 'units': held['units']}

if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='driftgate-review-') as temporary:
        main(Path(temporary))
    print(json.dumps(RESULTS, indent=2, ensure_ascii=False))
