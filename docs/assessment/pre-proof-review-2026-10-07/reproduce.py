"""Read-only production-code probes for three pre-S1-d review findings."""
import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from drift_gate.adapters.docs.content import attach_env_documents
from drift_gate.core.contracts.discovery import discover_contracts
from drift_gate.core.contracts.planner import DocumentBinding, DocumentBindings, PlanRequest, plan_contracts
from drift_gate.core.evaluation.obligations import inspect_contract_plan, evaluate_contract_plan
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.facts import ContractFamily
from drift_gate.core.policy.loader import load_policy_from_dict


def code(path='/old', key='KNOWN'):
    return ('from fastapi import FastAPI\nimport os\napp = FastAPI()\n'
            f'value = os.getenv({key!r})\n@app.get({path!r})\ndef endpoint(): return {{}}\n')


def source(before, after):
    return ChangedFile('src/api.py', 'modified', before_source=before, after_source=after)


def request(files):
    return PlanRequest('review', 'contracts', tuple(file.path for file in files),
        DocumentBindings('contract-document-bindings-v1', (
            DocumentBinding('api', ('python-fastapi-routes', '1'), ('docs/api.md',)),
            DocumentBinding('env', ('python-env-literals', '1'), ('.env.example',)),
        )))


def run():
    rows = {}
    docs = [ChangedFile('docs/api.md', 'unchanged', after_source='GET /old\n', document_input_state='available')]
    old = [source(code(), code())]
    initial = inspect_contract_plan(request(old), old, docs)
    new = [source(code(), code('/new'))]
    reused = evaluate_contract_plan(initial.plan, new, docs)
    fresh = inspect_contract_plan(request(new), new, docs)
    rows['R1_stale_plan'] = {
        'input': {'old_sources': [asdict(file) for file in old], 'new_sources': [asdict(file) for file in new]},
        'reused_plan': reused.to_dict(), 'fresh_plan_control': fresh.to_dict(),
        'reproduced': reused.truth.value == 'T' and reused.complete_within_selection and fresh.truth.value == 'F',
    }

    files = [source(code(key='OLD'), code(key='NEW'))]
    deleted = ChangedFile('.env.example', 'deleted', documented_env_keys=['NEW'])
    actual = inspect_contract_plan(request(files), files, [deleted])
    explicit_missing = inspect_contract_plan(request(files), files, [replace(deleted, document_input_state='missing')])
    policy = load_policy_from_dict({'rules': [{'id': 'env', 'when': {'any_changed': ['src/**']},
        'require': {'groups': [{'name': 'env', 'all_changed': ['.env.example'], 'content': 'env-keys'}]}}]})
    normalized = attach_env_documents([deleted], policy, lambda _: 'NEW=example\n')
    adapter_control = inspect_contract_plan(request(files), files, normalized)
    rows['R2_deleted_env_document'] = {
        'input': {'sources': [asdict(file) for file in files], 'document': asdict(deleted)},
        'retained_keys': actual.to_dict(), 'explicit_missing_control': explicit_missing.to_dict(),
        'normal_document_adapter_control': adapter_control.to_dict(),
        'reproduced': actual.truth.value == 'T' and actual.complete_within_selection
                      and explicit_missing.truth.value == adapter_control.truth.value == 'F',
    }

    files = [source('value = 1\n', 'value = 2\n')]
    req = PlanRequest('review', 'scope', ('src/api.py',), DocumentBindings('contract-document-bindings-v1'))
    results, discoveries = [], []
    for family in (ContractFamily.API_ROUTE, ContractFamily.ENV_KEY):
        discovery = discover_contracts(files, families=(family,))
        discoveries.append(discovery.to_dict())
        results.append(evaluate_contract_plan(plan_contracts(req, discovery), files, []).to_dict())
    rows['R3_scope_serialization'] = {
        'route_only_discovery': discoveries[0], 'env_only_discovery': discoveries[1],
        'route_only_result': results[0], 'env_only_result': results[1],
        'reproduced': discoveries[0] != discoveries[1] and results[0] == results[1],
    }
    return {'schema': 'pre-proof-review-probes-v1',
            'scope': 'Authored deterministic counterexamples against current internal APIs; not production incidence estimates',
            'findings': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = run()
    with args.out.open('x', encoding='utf-8') as target:
        json.dump(result, target, indent=2, ensure_ascii=False, allow_nan=False)
        target.write('\n')
    states = {name: row['reproduced'] for name, row in result['findings'].items()}
    print(json.dumps(states))
    # Zero means the diagnostic reproduced all findings, not that the product passed.
    raise SystemExit(0 if all(states.values()) else 1)


if __name__ == '__main__':
    main()
