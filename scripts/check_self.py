"""Run the repository's own policy with explicit input and coverage evidence."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from drift_gate.adapters.ast.analyzer import enrich_semantic_signals
from drift_gate.adapters.git.client import GitAdapter, GitInputError
from drift_gate.adapters.policy_loader import read_policy
from drift_gate.core.engine import run
from drift_gate.core.policy.loader import PolicyLoadError
from drift_gate.core.change_paths import change_paths, is_ignored, triggers
from drift_gate.adapters.execution import identity, digest, atomic_json
from drift_gate.adapters.source_scope import product_path


def inspect_repository(root: Path, base: str, trusted_policy_ref=None) -> dict:
    source, policy = read_policy(root / '.drift-gate.self.yml')
    if not policy.rules:
        raise PolicyLoadError('Self-check requires a nonempty policy')
    if trusted_policy_ref:
        from drift_gate.adapters.git.client import _git
        from drift_gate.core.policy.loader import load_policy_from_text
        from drift_gate.core.policy.guard import weakening_reasons
        commit = _git(['rev-parse', '--verify', '--end-of-options', f'{trusted_policy_ref}^{{commit}}'], root).decode().strip()
        trusted = load_policy_from_text(_git(['show', f'{commit}:.drift-gate.self.yml'], root).decode('utf-8'))
        reasons = weakening_reasons(trusted, policy)
        if reasons:
            raise PolicyLoadError('Candidate weakened trusted obligations: ' + '; '.join(reasons))
    git = GitAdapter(root)
    files = git.get_changed_files(base)
    evaluation = run(enrich_semantic_signals(files), policy=policy)
    ignored = [file.path for file in files if is_ignored(file, policy.ignore_paths)]
    matches = {file.path: [rule.id for rule in policy.rules if triggers(file, rule.when.any_changed)]
               for file in files if file.path not in ignored}
    unmatched = [f.path for f in files if f.path not in ignored and not matches.get(f.path)
                 and any(product_path(p) for p in change_paths(f))]
    if unmatched:
        raise PolicyLoadError('Unclassified product paths: ' + ', '.join(unmatched))
    for rule in policy.rules:
        for group in rule.require.groups:
            for path in group.all_changed:
                if path.startswith('docs/') and not any(c in path for c in '*?['):
                    target = root / path
                    if not target.is_file() or not target.read_text(encoding='utf-8').strip():
                        raise PolicyLoadError('Required contract missing or empty: ' + path)
    return {'requested_base': base, 'inputs': git.provenance,
            'policy_sha256': digest(source),
            'trusted_policy_ref': trusted_policy_ref, 'warnings': policy.load_warnings,
            'evaluation': evaluation.to_dict(),
            'coverage': {'kind': 'declared path matches, before intensity filtering',
                         'matched': {path: rules for path, rules in matches.items() if rules},
                         'unmatched': [path for path, rules in matches.items() if not rules],
                         'ignored': ignored}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--trusted-policy-ref', help='Reject weaker obligations than this explicitly selected commit')
    args = parser.parse_args()
    execution = identity()
    try:
        result = inspect_repository(args.repo.resolve(), args.base, args.trusted_policy_ref)
        code = int(result['evaluation']['result'] == 'fail')
    except (GitInputError, PolicyLoadError, OSError, ValueError) as exc:
        result = {'error': {'code': 'input_error', 'message': str(exc)}}
        code = 2
    except Exception as exc:
        import traceback
        traceback.print_exc()
        result = {'error': {'code': 'execution_error', 'message': str(exc)}}
        code = 3
    result['execution'] = {**execution, 'status': 'success' if code in (0, 1) else result['error']['code']}
    atomic_json(args.out, result)
    print(json.dumps({'output': str(args.out), 'exit_code': code}))
    raise SystemExit(code)


if __name__ == '__main__':
    main()
