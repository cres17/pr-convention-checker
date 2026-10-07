"""Production API controls for the three pre-proof findings; synthetic inputs."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from drift_gate.core.contracts.discovery import discover_contracts
from drift_gate.core.contracts.planner import DocumentBinding, DocumentBindings, PlanRequest, plan_contracts
from drift_gate.core.evaluation.contract_proof import inspect_contract_proof
from drift_gate.core.evaluation.obligations import evaluate_contract_plan, inspect_contract_plan
from drift_gate.core.evaluation.result_guard import ResultValidationError, validate_proof_payload
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.facts import ContractFamily


def code(path='/old', key='KNOWN'):
    return ('from fastapi import FastAPI\nimport os\napp = FastAPI()\n'
            f'value = os.getenv({key!r})\n@app.get({path!r})\ndef endpoint(): return {{}}\n')


def req(files):
    return PlanRequest('review', 'contracts', tuple(file.path for file in files),
        DocumentBindings('contract-document-bindings-v1', (
            DocumentBinding('api', ('python-fastapi-routes', '1'), ('docs/api.md',)),
            DocumentBinding('env', ('python-env-literals', '1'), ('.env.example',)),
        )))


def run():
    docs = [ChangedFile('docs/api.md', 'unchanged', after_source='GET /old\n', document_input_state='available')]
    old = [ChangedFile('src/api.py', 'modified', before_source=code(), after_source=code())]
    plan = inspect_contract_plan(req(old), old, docs).plan
    changed = [replace(old[0], after_source=code('/new'))]
    try:
        evaluate_contract_plan(plan, changed, docs)
    except ValueError as exc:
        reuse = {'rejected': True, 'error': str(exc)}
    else:
        reuse = {'rejected': False}
    fresh = inspect_contract_proof(req(changed), changed, docs)
    env_files = [replace(old[0], before_source=code(key='OLD'), after_source=code(key='NEW'))]
    deleted = ChangedFile('.env.example', 'deleted', documented_env_keys=['NEW'])
    uncertain = inspect_contract_proof(req(env_files), env_files, [deleted])
    missing = inspect_contract_proof(req(env_files), env_files, [replace(deleted, document_input_state='missing')])
    plain = [replace(old[0], before_source='value=1', after_source='value=2')]
    plain_req = PlanRequest('review', 'scope', ('src/api.py',), DocumentBindings('contract-document-bindings-v1'))
    family_results = [evaluate_contract_plan(plan_contracts(plain_req, discover_contracts(plain, families=(family,))),
        plain, []).to_dict() for family in (ContractFamily.API_ROUTE, ContractFamily.ENV_KEY)]
    json_proof = json.loads(json.dumps(fresh.proof.to_dict()))
    validate_proof_payload(json_proof, fresh.context)
    mutations = {}
    for kind in ('truth', 'coverage', 'witness', 'latest-head'):
        payload = json.loads(json.dumps(json_proof))
        root = next(row for row in payload['nodes'] if row['spec']['id'] == payload['root_ref'])
        if kind == 'truth': root['truth'] = 'T'
        elif kind == 'coverage': root['coverage']['closed_domains'] = []
        elif kind == 'witness': root['sufficient_witness_refs'] = ['missing']
        else: payload['current_head_certified'] = True
        try:
            validate_proof_payload(payload, fresh.context)
        except ResultValidationError as exc:
            mutations[kind] = {'rejected': True, 'error': str(exc)}
        else:
            mutations[kind] = {'rejected': False}
    checks = {'R1_previous_plan_rejected': reuse['rejected'] and fresh.root.truth.value == 'F',
              'R2_deleted_env_not_satisfied': uncertain.root.truth.value == 'U' and missing.root.truth.value == 'F',
              'R3_distinct_scope_serialization': family_results[0] != family_results[1],
              'all_tampered_proofs_rejected': all(row['rejected'] for row in mutations.values())}
    return {'schema': 'proof-fix-controls-v1', 'checks': checks,
            'stale_plan': reuse, 'fresh_plan': fresh.to_dict(),
            'deleted_env': uncertain.to_dict(), 'explicit_missing_env': missing.to_dict(),
            'declared_families': family_results, 'tamper_controls': mutations,
            'scope': 'Authored nonblind API controls, not parser soundness or real PR accuracy'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = run()
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(result['checks']))
    raise SystemExit(0 if all(result['checks'].values()) else 1)


if __name__ == '__main__':
    main()
