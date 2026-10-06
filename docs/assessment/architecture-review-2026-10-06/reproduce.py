"""Observational audit cases, not acceptance tests. Run with the project installed.

Only temporary synthetic repositories are modified. Assertions describe the
reviewed defects; after a fix, convert the cases to desired-behavior regressions.
"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from drift_gate.adapters.git.client import GitAdapter
from drift_gate.core.engine import run
from drift_gate.core.models.policy import Policy
from drift_gate.desktop.progress_drafts import export_draft, import_draft, cache_draft
from drift_gate.desktop.progress_service import extract_requirements, save_baseline, load_baseline
from drift_gate.desktop.verification_records import parse_results


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout


def make_repo(root):
    root.mkdir()
    git(root, 'init', '-q')
    git(root, 'config', 'user.name', 'Review Fixture')
    git(root, 'config', 'user.email', 'fixture@example.invalid')
    git(root, 'config', 'core.quotePath', 'true')
    (root / 'README.md').write_text('# Plan\n- [ ] Feature\n', encoding='utf-8')
    (root / 'src/routes').mkdir(parents=True)
    (root / 'src/routes/결제.py').write_text('value = 1\n', encoding='utf-8')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'fixture')
    return root


def main():
    results = {}
    with tempfile.TemporaryDirectory(prefix='driftgate-architecture-') as temporary:
        directory = Path(temporary).resolve()
        root = make_repo(directory / 'repo')
        (root / 'src/routes/결제.py').write_text('value = 2\n', encoding='utf-8')
        policy = Policy.from_dict({'rules': [{'id': 'route-docs', 'when': {'any_changed': ['src/routes/**']},
            'require': {'groups': [{'name': 'spec', 'any_changed': ['docs/spec.md'], 'content': 'paths'}]},
            'severity': 'blocker'}]})
        collected = GitAdapter(root).get_changed_files('HEAD')
        result = run(collected, policy=policy)
        assert result.result == 'pass' and collected[0].path != 'src/routes/결제.py'
        results['quoted_filename'] = {'gate': result.result, 'paths': [f.path for f in collected],
            'patch_bytes': [len(f.patch) for f in collected]}
        git(root, 'config', 'core.quotePath', 'false')
        control = run(GitAdapter(root).get_changed_files('HEAD'), policy=policy)
        assert control.result == 'fail'
        results['quoted_filename']['control_gate'] = control.result

        missing = GitAdapter(root).get_changed_files('no-such-review-ref')
        assert missing == []  # Only one commit, so fallback HEAD~1 also fails.
        result = run(missing, policy=policy)
        assert result.result == 'pass' and result.skip_reason == 'no-changes'
        results['invalid_base'] = {'gate': result.result, 'skip_reason': result.skip_reason,
            'real_changes': len(GitAdapter(root).get_changed_files('HEAD'))}
        (root / '.drift-gate.yml').write_text('''rules:
  - id: route-docs
    when:
      any_changed: ["src/routes/**"]
    require:
      groups:
        - name: spec
          any_changed: ["docs/spec.md"]
          content: paths
    severity: blocker
''', encoding='utf-8')
        cli = subprocess.run([sys.executable, '-c', 'from drift_gate.adapters.cli.runner import run_cli; run_cli()',
            'check', '--base', 'no-such-review-ref', '--json'], cwd=root, capture_output=True, text=True)
        cli_result = json.loads(cli.stdout)
        results['invalid_base']['cli_exit'] = cli.returncode
        results['invalid_base']['cli_result'] = cli_result['result']
        assert cli.returncode == 0 and cli_result['result'] == 'pass'
        control_cli = subprocess.run([sys.executable, '-c', 'from drift_gate.adapters.cli.runner import run_cli; run_cli()',
            'check', '--base', 'HEAD', '--json'], cwd=root, capture_output=True, text=True)
        assert control_cli.returncode == 1 and json.loads(control_cli.stdout)['result'] == 'fail'
        results['invalid_base']['valid_base_cli_exit'] = control_cli.returncode

        state = directory / 'state'
        draft = extract_requirements(root, ['README.md'])
        too_many = deepcopy(draft)
        too_many['requirements'] = [{**deepcopy(draft['requirements'][0]), 'id': str(i)} for i in range(121)]
        rejected = {}
        for name, operation in {
            'save': lambda: save_baseline(root, state, deepcopy(too_many)),
            'cache': lambda: cache_draft(root, state, too_many),
            'export': lambda: export_draft(root, too_many, directory / 'too-many.json'),
        }.items():
            try:
                operation()
            except ValueError as exc:
                rejected[name] = str(exc)
        assert len(rejected) == 3
        results['manual_121_backend'] = rejected

        git(root, 'remote', 'add', 'origin', 'https://example.invalid/team/project.git')
        baseline = save_baseline(root, state, deepcopy(draft))
        clone = make_repo(directory / 'clone')
        git(clone, 'remote', 'add', 'origin', 'https://example.invalid/team/project.git')
        loaded = load_baseline(clone, state)
        assert loaded['repository'] == str(root)  # Portable baseline keeps original writer's path.
        exported = directory / 'clone-backup.json'
        export_draft(clone, loaded, exported)
        try:
            import_draft(clone, state, exported)
        except ValueError as exc:
            results['same_clone_roundtrip'] = {'error': str(exc), 'wrapper_matches_current_repo': True,
                'draft_repository_is_original_clone': True}
        else:
            raise AssertionError('Expected valid same-clone export/import incompatibility')

        bad = directory / 'results.json'
        bad.write_text(json.dumps({'testResults': [{'name': 'sample', 'assertionResults': 1}]}))
        try:
            parse_results(bad)
        except TypeError as exc:
            results['malformed_test_results'] = {'exception': type(exc).__name__, 'message': str(exc)}
        else:
            raise AssertionError('Expected unhandled TypeError')

        # A real accepted baseline can exceed the draft's 2MB limit through notes.
        big = deepcopy(baseline)
        big['requirements'][0]['verification_note'] = 'x' * 2_000_001
        saved = save_baseline(root, state, big)
        export_draft(root, saved, directory / 'large-backup.json')
        try:
            import_draft(root, state, directory / 'large-backup.json')
        except ValueError as exc:
            results['export_import_size'] = {'saved': True, 'export_bytes': (directory / 'large-backup.json').stat().st_size,
                'import_error': str(exc)}
        else:
            raise AssertionError('Expected size asymmetry')
        missing_repo_base = deepcopy(draft)
        missing_repo_base['edit_base'] = deepcopy(draft)
        missing_repo_base['edit_base'].pop('repository', None)
        source = directory / 'missing-repository.json'
        export_draft(root, missing_repo_base, source)
        imported_key = import_draft(root, state, source)
        assert imported_key
        results['wire_contract_gap'] = {'backend_import_accepted': True,
            'edit_base_repository': 'missing; UI rejection is in ui-audit.tsx.fixture'}
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
