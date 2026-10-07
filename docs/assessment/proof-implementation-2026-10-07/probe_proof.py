"""Reproduce the six mixed-contract design rows through real Git and document adapters."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from drift_gate.adapters.docs.content import attach_env_documents, local_document_reader
from drift_gate.adapters.git.client import GitAdapter
from drift_gate.core.contracts.planner import DocumentBinding, DocumentBindings, PlanRequest
from drift_gate.core.evaluation.contract_proof import inspect_contract_proof
from drift_gate.core.policy.loader import load_policy_from_dict


def code(path='/old', key='KNOWN', dynamic=False):
    access = 'name' if dynamic else repr(key)
    return ('from fastapi import FastAPI\nimport os\napp = FastAPI()\n'
            f'value = os.getenv({access})\n@app.get({path!r})\ndef endpoint(): return {{}}\n')


def cases():
    # Author-defined expectations precede the probe execution. These are
    # nonblind regression controls, not an independent holdout dataset.
    baseline = {'src/api.py': code(), 'docs/api.md': 'GET /old\n', '.env.example': 'KNOWN=example\n'}
    return [
        ('unchanged-env-stale-api', baseline, {'src/api.py': code('/new')}, 'F', True),
        ('new-env-missing-api', baseline, {'src/api.py': code('/new', 'NEW'), '.env.example': 'NEW=example\n',
                                        'docs/api.md': None}, 'F', True),
        ('dynamic-env-stale-api', {**baseline, 'src/api.py': code(dynamic=True)},
         {'src/api.py': code('/new', dynamic=True)}, 'F', False),
        ('dynamic-env-current-api', {**baseline, 'src/api.py': code(dynamic=True)},
         {'src/api.py': code('/new', dynamic=True), 'docs/api.md': 'GET /new\n'}, 'U', False),
        ('both-no-delta', {**baseline, 'src/api.py': code() + 'unrelated = 1\n'},
         {'src/api.py': code() + 'unrelated = 2\n'}, 'T', True),
        ('unsupported-source-current-api', {**baseline, 'src/opaque.go': 'package api\n// before\n'},
         {'src/api.py': code('/new'), 'docs/api.md': 'GET /new\n', 'src/opaque.go': 'package api\n// after\n'}, 'U', False),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    mappings = DocumentBindings('contract-document-bindings-v1', (
        DocumentBinding('route-doc', ('python-fastapi-routes', '1'), ('docs/api.md',)),
        DocumentBinding('env-doc', ('python-env-literals', '1'), ('.env.example',)),
        DocumentBinding('response-doc', ('python-response-primitives', '2'), ('openapi.json',)),
    ))
    modes = {'python-env-literals': 'env-keys', 'python-response-primitives': 'api-schema',
             'python-fastapi-routes': 'api-routes'}
    policy = load_policy_from_dict({'rules': [{'id': 'collection-only', 'when': {'any_changed': ['src/**']},
        'require': {'groups': [{'name': binding.id, 'all_changed': list(binding.selectors),
                               'content': modes[binding.profile_ref[0]]} for binding in mappings.entries]}}]})
    rows = []
    for name, before, changes, truth, complete in cases():
        with tempfile.TemporaryDirectory(prefix='driftgate-planner-probe-') as directory:
            root = Path(directory)

            def git(*arguments):
                return subprocess.check_output(['git', *arguments], cwd=root, stderr=subprocess.PIPE)

            def write(files):
                for path, content in files.items():
                    target = root / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if content is None:
                        target.unlink(missing_ok=True)
                    else:
                        target.write_text(content, encoding='utf-8')

            git('init'); write(before); git('add', '.')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'baseline')
            write(changes); git('add', '.')
            adapter = GitAdapter(root)
            files = adapter.get_changed_files('HEAD')
            sources = [file for file in files if file.path.startswith('src/')]
            observations = attach_env_documents(files, policy, local_document_reader(root))
            docs = [file for file in observations if not file.path.startswith('src/')]
            request = PlanRequest('contract-sync', 'contracts', tuple(file.path for file in sources), mappings)
            evaluation = inspect_contract_proof(request, sources, docs)
            actual = {'truth': evaluation.root.truth.value, 'complete_within_selection': evaluation.root.coverage.complete}
            expected = {'truth': truth, 'complete_within_selection': complete}
            rows.append({'id': name, 'before': before, 'changes': changes, 'expected': expected, 'actual': actual,
                         'matched': actual == expected, 'source_paths': list(request.source_paths),
                         'evaluation': evaluation.to_dict()})
    payload = {'schema': 'proof-git-probe-v1',
               'scope': 'Six authored nonblind mixed-contract controls; Git snapshots and bounded current document reads',
               'cases': rows, 'matched': sum(row['matched'] for row in rows), 'total': len(rows)}
    with args.out.open('x', encoding='utf-8') as target:
        json.dump(payload, target, indent=2, ensure_ascii=False, allow_nan=False); target.write('\n')
    print(json.dumps({'matched': payload['matched'], 'total': payload['total']}))
    raise SystemExit(0 if all(row['matched'] for row in rows) else 1)


if __name__ == '__main__':
    main()
