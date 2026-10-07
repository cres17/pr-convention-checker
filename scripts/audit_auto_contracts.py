"""Run frozen v2 contracts through real Git collection; never execute app code."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from drift_gate.adapters.git.client import GitAdapter
from drift_gate.adapters.docs.content import attach_env_documents, local_document_reader
from drift_gate.adapters.inspection import inspect
from drift_gate.adapters.ast.express_routes import attach_express_routes
from drift_gate.core.evaluation.api_schema import response_changes, UnknownResponse, UnsupportedContract
from drift_gate.core.evaluation.routes import complete_route_delta
from drift_gate.core.evaluation.environment import environment_delta
from drift_gate.core.policy.loader import load_policy_from_dict

AXES = ('facts', 'decision', 'verification', 'gate')


def validate_suite(suite):
    """Reject incomplete evaluation contracts instead of vacuous success."""
    protocol = suite.get('protocol') if isinstance(suite, dict) else None
    if (not isinstance(protocol, dict) or type(protocol.get('version')) is not int
        or protocol['version'] < 1 or not isinstance(protocol.get('input'), str) or not protocol['input'].strip()
        or not isinstance(protocol.get('axes'), list) or len(protocol['axes']) != len(AXES)
        or any(not isinstance(axis, str) for axis in protocol['axes']) or set(protocol['axes']) != set(AXES)):
        raise ValueError('suite requires a versioned protocol with input description and four axes')
    cases = suite.get('cases')
    if not isinstance(cases, list) or not cases:
        raise ValueError('suite requires at least one case')
    ids = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get('id'), str) or not case['id'].strip() or case['id'] in ids:
            raise ValueError('cases require unique nonempty ids')
        ids.add(case['id'])
        if not isinstance(case.get('facts_kind'), str) or case['facts_kind'] not in {'routes', 'schema', 'env'}:
            raise ValueError('unsupported facts_kind')
        expected = case.get('expected')
        if not isinstance(expected, dict) or set(expected) != set(AXES):
            raise ValueError('expected must define facts, decision, verification and gate')
        if (any(not isinstance(expected[axis], str) for axis in ('decision', 'verification', 'gate'))
            or expected['decision'] not in {'satisfied', 'violated', 'undetermined', 'not-applicable'}
            or expected['verification'] not in {'verified', 'partial', 'unverified', 'not-applicable'}
            or expected['gate'] not in {'pass', 'warn', 'fail'}):
            raise ValueError('unsupported expected outcome')
        for stage in ('before', 'after'):
            files = case.get(stage)
            if not isinstance(files, dict):
                raise ValueError('before/after must be file mappings')
            for path, content in files.items():
                if (not isinstance(path, str) or not path or '\\' in path or '\0' in path
                    or Path(path).is_absolute() or any(part in {'.', '..', '.git', ''} for part in path.split('/'))):
                    raise ValueError('suite file must be a safe relative path outside .git')
                if content is not None and not isinstance(content, str):
                    raise ValueError('suite file content must be text or null')
        if not isinstance(case.get('policy'), dict):
            raise ValueError('case requires a policy')
    return suite


def facts(files, kind):
    try:
        if kind == 'routes':
            added, removed = complete_route_delta(files)
            return {'added': [f'{m} {p}' for m, p in sorted(added)], 'removed': [f'{m} {p}' for m, p in sorted(removed)]}
        if kind == 'schema':
            delta = response_changes(files)
            if any(isinstance(shape, UnknownResponse) for shape in delta.values()):
                return 'unknown'
            return {f'{m} {p}': shape for (m, p), shape in sorted(delta.items())}
        delta = environment_delta(files)
        return 'unknown' if delta.uncertain else sorted(delta.keys)
    except UnsupportedContract:
        return 'unknown'


def evaluate_case(case):
    with tempfile.TemporaryDirectory(prefix='driftgate-auto-v2-') as directory:
        root = Path(directory).resolve()
        def git(*args):
            return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.PIPE)
        def write(files):
            for path, text in files.items():
                target = root / path
                if not target.resolve().is_relative_to(root):
                    raise ValueError('suite file must be inside the temporary repository')
                target.parent.mkdir(parents=True, exist_ok=True)
                if text is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_text(text, encoding='utf-8')
        git('init')
        write(case['before'])
        git('add', '.')
        git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--allow-empty', '-m', 'frozen baseline')
        write(case['after'])
        git('add', '.')  # evaluate tracked newly added files too
        policy = load_policy_from_dict(case['policy'])
        files = GitAdapter(root).get_changed_files('HEAD')
        sources = attach_express_routes([file for file in files if file.path.startswith('src/')])
        observed = facts(sources, case['facts_kind'])
        inputs = attach_env_documents(files, policy, local_document_reader(root))
        result = inspect(changed_files=inputs, policy=policy).to_dict()
        decision = result['rule_decisions'][0]
        actual = {'facts': observed, 'decision': decision['decision'],
                  'verification': decision['verification'], 'gate': result['result']}
        checks = {axis: value == actual[axis] for axis, value in case['expected'].items()}
        return {'id': case['id'], 'expected': case['expected'], 'actual': actual, 'checks': checks,
                'report': result, 'input_sha256': result['execution']['input_sha256']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path, default=ROOT / 'drift_gate/tests/contracts/auto-contracts-v2.json')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('output exists; previous evidence is immutable')
    try:
        suite = validate_suite(json.loads(args.suite.read_text(encoding='utf-8')))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    rows = [evaluate_case(case) for case in suite['cases']]
    axes = AXES
    result = {'protocol': suite['protocol'], 'suite_sha256': hashlib.sha256(args.suite.read_bytes()).hexdigest(),
              'counts': {axis: {'correct': sum(row['checks'][axis] for row in rows), 'total': len(rows)} for axis in axes},
              'false_verified': [row['id'] for row in rows if row['actual']['verification'] == 'verified'
                                 and not all(row['checks'][axis] for axis in ('facts', 'decision', 'verification'))],
              'missed_known_violations': [row['id'] for row in rows if row['expected']['decision'] == 'violated'
                                          and row['actual']['decision'] != 'violated'], 'cases': rows}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(json.dumps({key: result[key] for key in ('counts', 'false_verified', 'missed_known_violations')}))
    return int(not all(all(row['checks'].values()) for row in rows))


if __name__ == '__main__':
    raise SystemExit(main())
