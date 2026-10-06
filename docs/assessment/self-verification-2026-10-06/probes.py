"""Disposable experiments: rejected cleanup proposal and review boundaries."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from drift_gate.desktop.progress_drafts import (
    DraftSession, cache_draft, discard_recoveries, recovery_copy,
)
from drift_gate.desktop.progress_service import extract_requirements, save_baseline, load_baseline
from drift_gate.adapters.policy_loader import load_policy
from drift_gate.utils.glob_matcher import match_glob


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE)


def repository(root):
    root.mkdir()
    git(root, 'init')
    git(root, 'config', 'user.name', 'Verification fixture')
    git(root, 'config', 'user.email', 'verification@example.invalid')
    (root / 'README.md').write_text('# Fixture\n- [ ] 로그인 기능\n', encoding='utf-8')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'fixture baseline')
    return root


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    env = {**os.environ, 'PYTHONPATH': str(ROOT), 'ANTHROPIC_API_KEY': ''}
    result = {'head': git(ROOT, 'rev-parse', 'HEAD').decode().strip()}

    def cli(name, root, arguments):
        run = subprocess.run([sys.executable, '-m', 'drift_gate', *arguments], cwd=root,
                             env=env, capture_output=True, timeout=60)
        (out / (name + '.stdout')).write_bytes(run.stdout)
        (out / (name + '.stderr')).write_bytes(run.stderr)
        return {'exit_code': run.returncode, 'arguments': arguments,
                'stdout': run.stdout.decode('utf-8', errors='replace'),
                'stderr': run.stderr.decode('utf-8', errors='replace')}

    with tempfile.TemporaryDirectory(prefix='driftgate-probes-') as temporary:
        root = repository(Path(temporary) / 'fixture')
        (root / 'checklist.md').write_text('# No checked items\n', encoding='utf-8')
        result['invalid_base'] = {
            'check': cli('invalid-check', root, ['check', '--base', 'missing-review-ref', '--json', '--anthropic-api-key', '']),
            'review': cli('invalid-review', root, ['review', '--base', 'missing-review-ref', '--format', 'json', '--fail-on', 'low']),
            'self_audit': cli('invalid-self-audit', root, ['self-audit', '--base', 'missing-review-ref', '--checklist', 'checklist.md', '--json']),
            'valid_review_control': cli('valid-review', root, ['review', '--base', 'HEAD', '--format', 'json']),
        }
        # Existing AI proposal: remove copies from sessions no longer running.
        data = Path(temporary) / 'draft-data'
        baseline = save_baseline(root, data, extract_requirements(root, ['README.md']))
        draft = deepcopy(baseline)
        draft['requirements'][0]['title'] = '종료 전에 편집한 미저장 제목'
        owner = uuid.uuid4().hex
        session = DraftSession(root, data, owner)
        cache_draft(root, data, draft, owner, session)
        active = recovery_copy(root, data, baseline)
        active_rejected = False
        try:
            discard_recoveries(root, data, [{'key': active['recovery_key'], 'revision': active['recovery_revision']}])
        except ValueError:
            active_rejected = True
        finally:
            session.close()
        closed = recovery_copy(root, data, baseline)
        inactive_selection = [o for o in closed['recovery_options'] if not o['active']]
        # Apply the proposed rule ONLY to the disposable fixture, with fresh revisions.
        discard_recoveries(root, data, [{'key': o['key'], 'revision': o['revision']} for o in inactive_selection])
        after = recovery_copy(root, data, baseline)
        stored = load_baseline(root, data)
        result['rejected_cleanup_proposal'] = {
            'active_before_close': active['recovery_options'][0]['active'],
            'active_deletion_rejected': active_rejected,
            'active_after_close': closed['recovery_options'][0]['active'],
            'recoverable_title_before_proposed_cleanup': closed['recovery']['requirements'][0]['title'],
            'inactive_candidates': len(inactive_selection),
            'recovery_after_proposed_cleanup': after,
            'confirmed_title': stored['requirements'][0]['title'],
            'confirmed_baseline_unchanged': stored == baseline,
            'scope': 'real service APIs; proposed automatic selection simulated in a disposable repository',
        }

        # Product-path checks: missing docs detected, cosmetic edits also satisfy path rules.
        (root / '.drift-gate.yml').write_bytes((ROOT / '.drift-gate.yml').read_bytes())
        (root / 'src/routes').mkdir(parents=True)
        (root / 'docs').mkdir()
        route = root / 'src/routes/session.py'
        route.write_text('def create_session(user):\n    return user\n', encoding='utf-8')
        spec = root / 'docs/spec.md'
        spec.write_text('# Session\ncreate_session(user)\n', encoding='utf-8')
        changelog = root / 'CHANGELOG.md'
        changelog.write_text('# Changelog\nInitial version.\n', encoding='utf-8')
        git(root, 'add', '.'); git(root, 'commit', '-m', 'API fixture')
        route.write_text('def create_session(user, expires_in):\n    return (user, expires_in)\n', encoding='utf-8')
        scenarios = {}
        for name in ['missing-docs', 'cosmetic-docs', 'updated-contract']:
            if name == 'cosmetic-docs':
                spec.write_text('# Session\ncreate_session(user)\n<!-- formatting -->\n', encoding='utf-8')
                changelog.write_text('# Changelog\nInitial version.\n<!-- formatting -->\n', encoding='utf-8')
            elif name == 'updated-contract':
                spec.write_text('# Session\ncreate_session(user, expires_in): expires_in is required.\n', encoding='utf-8')
                changelog.write_text('# Changelog\nBreaking change: create_session requires expires_in.\n', encoding='utf-8')
            run = cli(name, root, ['check', '--base', 'HEAD', '--json', '--anthropic-api-key', ''])
            report = json.loads(run['stdout'])
            scenarios[name] = {'exit_code': run['exit_code'], 'gate': report['result'],
                               'violations': [v['rule_id'] for v in report['violations']]}
        result['path_policy_controls'] = scenarios

    # Byte decoding happens before the per-JSON-frame exception boundary.
    valid = b'{"jsonrpc":"2.0","id":7,"method":"tools/list"}\n'
    mcp = {}
    for name, frame in [('valid', valid), ('bad-json-then-valid', b'{\n' + valid), ('bad-utf8-then-valid', b'\xff\n' + valid)]:
        p = subprocess.run([sys.executable, '-m', 'drift_gate.adapters.mcp.server'], input=frame,
                           cwd=ROOT, env=env, capture_output=True, timeout=30)
        (out / (name + '.stdout')).write_bytes(p.stdout)
        (out / (name + '.stderr')).write_bytes(p.stderr)
        lines = [json.loads(line) for line in p.stdout.splitlines()]
        mcp[name] = {'exit_code': p.returncode, 'following_request_answered': any(r.get('id') == 7 and 'result' in r for r in lines),
                     'stderr': p.stderr.decode('utf-8', errors='replace')}
    result['mcp_frames'] = mcp

    changed = git(ROOT, 'diff', '--name-only', '729a3cd', '01e28e1').decode().splitlines()
    policy = load_policy(ROOT / '.drift-gate.yml')
    coverage = {p: [rule.id for rule in policy.rules if any(match_glob(p, pattern) for pattern in rule.when.any_changed)] for p in changed}
    production = {p: hits for p, hits in coverage.items() if ((p.startswith('drift_gate/') and '/tests/' not in p and p.endswith('.py')) or (p.startswith('desktop-ui/src/') and not p.endswith(('.test.ts', '.test.tsx'))))}
    result['policy_coverage'] = {'changed_files': len(changed), 'matched': {p: hits for p, hits in coverage.items() if hits},
                                  'production_file_count': len(production), 'production_matched': {p: hits for p, hits in production.items() if hits}}
    (out / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
