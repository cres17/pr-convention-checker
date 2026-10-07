"""Execute bounded discovery examples; write a new receipt without overwriting evidence."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from drift_gate.core.contracts.discovery import discover_contracts
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.facts import ContractFamily


def examples():
    route = 'from fastapi import FastAPI\napp = FastAPI()\n@app.get("/old")\ndef endpoint(): return {}\n'
    response = ('from fastapi import FastAPI\nfrom pydantic import BaseModel\napp = FastAPI()\n'
                'class Item(BaseModel):\n    id: int\n'
                '@app.get("/items", response_model=Item)\ndef endpoint(): return {}\n')
    mixed = route + 'import os\nvalue = os.getenv("KNOWN")\n'
    dynamic = 'import os\nvalue = os.getenv(name)\n'
    opaque = 'from external import app\n@app.get("/outside")\ndef endpoint(): return {}\n'

    def python(text):
        return ChangedFile('src/api.py', 'modified', before_source=text, after_source=text)

    adapter_routes = ChangedFile('src/api.ts', 'modified', before_routes=[('GET', '/old')],
                                 after_routes=[('GET', '/new')])
    # Adapter rows here are declared observations, not independent source/runtime proof.
    return [
        ('mixed-python', [python(mixed)], None, True, ['api-route', 'env-key'], []),
        ('primitive-response', [python(response)], None, True, ['api-response', 'api-route'], []),
        ('opaque-response', [python(response.replace('id: int', 'id: list[int]'))], None,
         False, ['api-response', 'api-route'], ['api-response']),
        ('dynamic-env', [python(dynamic)], None, False, ['env-key'], ['env-key']),
        ('external-registration', [python(opaque)], None, False, ['api-route'], ['api-response', 'api-route']),
        ('unsupported-go', [ChangedFile('src/api.go', 'modified', before_source='', after_source='package api')],
         None, False, [], ['api-response', 'api-route', 'env-key']),
        ('express-all-families', [adapter_routes], None, False, ['api-route'], ['api-response', 'env-key']),
        ('express-route-only', [adapter_routes], (ContractFamily.API_ROUTE,), True, ['api-route'], []),
        ('empty-selection', [], None, False, [], []),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    rows = []
    for name, files, families, complete, candidates, open_families in examples():
        result = discover_contracts(files, **({'families': families} if families is not None else {}))
        actual = {'complete_within_selection': result.complete_within_selection,
                  'candidate_families': sorted({domain.family.value for domain in result.candidates}),
                  'open_families': sorted({domain.family.value for domain in result.open_domains})}
        expected = {'complete_within_selection': complete, 'candidate_families': candidates,
                    'open_families': open_families}
        rows.append({'id': name, 'files': [asdict(file) for file in files],
                     'requested_families': [family.value for family in families] if families is not None else 'default-all',
                     'expected': expected, 'actual': actual, 'matched': actual == expected,
                     'discovery': result.to_dict()})
    payload = {'schema': 'discovery-examples-v1',
               'scope': 'Authored nonblind module/profile regression examples; not PR accuracy or service closure',
               'cases': rows, 'matched': sum(row['matched'] for row in rows), 'total': len(rows)}
    with args.out.open('x', encoding='utf-8') as target:
        json.dump(payload, target, indent=2, ensure_ascii=False, allow_nan=False)
        target.write('\n')
    print(json.dumps({'matched': payload['matched'], 'total': payload['total'], 'output': str(args.out)}))
    raise SystemExit(0 if all(row['matched'] for row in rows) else 1)


if __name__ == '__main__':
    main()
