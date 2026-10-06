"""Run the repository's own policy with explicit input and coverage evidence."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from drift_gate.adapters.ast.analyzer import enrich_semantic_signals
from drift_gate.adapters.git.client import GitAdapter, GitInputError
from drift_gate.adapters.policy_loader import load_policy
from drift_gate.core.engine import run
from drift_gate.core.policy.loader import PolicyLoadError
from drift_gate.utils.glob_matcher import matches_any


def inspect_repository(root: Path, base: str) -> dict:
    policy = load_policy(root / '.drift-gate.self.yml')
    files = GitAdapter(root).get_changed_files(base)
    evaluation = run(enrich_semantic_signals(files), policy=policy)
    ignored = [file.path for file in files if matches_any(file.path, policy.ignore_paths)]
    matches = {file.path: [rule.id for rule in policy.rules if matches_any(file.path, rule.when.any_changed)]
               for file in files if file.path not in ignored}
    return {'requested_base': base, 'evaluation': evaluation.to_dict(),
            'coverage': {'kind': 'declared path matches, before intensity filtering',
                         'matched': {path: rules for path, rules in matches.items() if rules},
                         'unmatched': [path for path, rules in matches.items() if not rules],
                         'ignored': ignored}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = inspect_repository(args.repo.resolve(), args.base)
        code = int(result['evaluation']['result'] == 'fail')
    except (GitInputError, PolicyLoadError, OSError, ValueError) as exc:
        result = {'error': {'code': 'input_error', 'message': str(exc)}}
        code = 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.out), 'exit_code': code}))
    raise SystemExit(code)


if __name__ == '__main__':
    main()
