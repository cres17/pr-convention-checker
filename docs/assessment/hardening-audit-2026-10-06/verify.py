"""Targeted adversarial audit. Mutations only affect a disposable Git clone."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[3]
REVISION = 'f43cada2ea177b63cb0ac4a79be37071113a5191'
SUBJECT = 'drift_gate/core/audit_subject.py'
CONTRACT = 'docs/contracts/gate-and-inputs.md'
OPS = 'docs/ops/drift-gate-self-check.md'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True, type=Path)
    out = parser.parse_args().out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    rows = []
    with tempfile.TemporaryDirectory(prefix='driftgate-hardening-audit-') as tmp:
        repo = Path(tmp) / 'repo'
        subprocess.run(['git', 'clone', '--shared', '--no-checkout', str(ROOT), str(repo)],
                       check=True, capture_output=True)
        def git(*args):
            return subprocess.check_output(['git', *args], cwd=repo, stderr=subprocess.PIPE)
        git('checkout', '--detach', REVISION)
        def put(path, text):
            target = repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding='utf-8')
        def append(path, text):
            put(path, (repo / path).read_text(encoding='utf-8') + text)
        put(SUBJECT, 'def calculate():\n    return 1\n')
        args_path = 'drift_gate/core/audit_args.py'
        args_before = 'def make(a,\n         b=1,\n):\n    return a\n'
        put(args_path, args_before)
        git('add', SUBJECT, args_path)
        git('-c', 'user.name=Audit fixture', '-c', 'user.email=audit@example.invalid', 'commit', '-m', 'Audit fixture')
        baseline = git('rev-parse', 'HEAD').decode().strip()
        env = {**os.environ, 'PYTHONPATH': str(repo), 'ANTHROPIC_API_KEY': ''}
        policy_original = (repo / '.drift-gate.self.yml').read_text()
        def reset(source_change=True):
            git('reset', '--hard', baseline)
            git('clean', '-fd')
            if source_change:
                put(SUBJECT, 'def calculate():\n    return 2\n')
        def run(name, category, expectation, *, extra_env=None, base=baseline):
            directory = out / name
            directory.mkdir()
            output = directory / 'result.json'
            sentinel = b'{"evaluation":{"result":"pass"},"sentinel":"OLD RESULT"}\n'
            output.write_bytes(sentinel)
            process = subprocess.run([sys.executable, 'scripts/check_self.py', '--base', base,
                '--out', str(output)], cwd=repo, env={**env, **(extra_env or {})},
                capture_output=True, timeout=45)
            (directory / 'stdout.log').write_bytes(process.stdout)
            (directory / 'stderr.log').write_bytes(process.stderr)
            (directory / 'change.patch').write_bytes(git('diff', '--no-ext-diff', baseline))
            (directory / 'status.txt').write_bytes(git('status', '--short'))
            data = json.loads(output.read_text())
            evaluation = data.get('evaluation', {})
            stale = output.read_bytes() == sentinel
            row = {'name': name, 'category': category, 'expectation': expectation,
                   'exit_code': process.returncode,
                   'actual': 'process_error' if stale else evaluation.get('result', data.get('error', {}).get('code', 'unknown')),
                   'artifact_result': evaluation.get('result', data.get('error', {}).get('code', 'unknown')),
                   'stale_output': stale,
                   'rules': evaluation.get('scan_metrics', {}).get('evaluated_rules'),
                   'scanned': evaluation.get('scan_metrics', {}).get('scanned_files'),
                   'violations': [v['rule_id'] for v in evaluation.get('violations', [])]}
            rows.append(row)
        reset(); run('source-only', 'control', 'fail')
        reset(); append(CONTRACT, '\ncalculate now returns 2.\n'); run('source-and-correct-document', 'control', 'pass')
        reset(False); append(SUBJECT, '\n# comment\n'); run('comment-only', 'control', 'pass')
        reset(); run('invalid-base', 'control', 'input_error', base='absent-audit-ref')
        reset(); (repo / '.drift-gate.self.yml').unlink(); run('missing-policy', 'control', 'input_error')

        for name, transform in [
            ('empty-rules', lambda p: p.update(rules=[])),
            ('remove-engine-rule', lambda p: p.update(rules=p['rules'][1:])),
            ('downgrade-to-nit', lambda p: p['rules'][0].update(severity='nit')),
            ('raise-failure-threshold', lambda p: p['gate'].update(fail_on_major_count=999)),
            ('ignore-core', lambda p: p['ignore_paths'].append('drift_gate/core/**')),
            ('make-contract-optional', lambda p: p['rules'][0]['require']['groups'][0].update(required=False)),
            ('narrow-trigger', lambda p: p['rules'][0]['when'].update(any_changed=['never-matches/**'])),
            ('raise-intensity', lambda p: p['rules'][0]['when'].update(min_change_intensity='signature-change')),
        ]:
            reset()
            policy = yaml.safe_load(policy_original)
            transform(policy)
            put('.drift-gate.self.yml', yaml.safe_dump(policy, sort_keys=False))
            append(OPS, '\nPolicy edited.\n')
            run(name, 'policy-trust', 'Candidate policy must not weaken trusted obligations')

        for name, content in [
            ('empty-file', ''), ('yaml-null', 'null\n'), ('empty-root-list', '[]\n'),
            ('null-rules', 'rules: null\n'), ('missing-rule-id', 'rules: [{severity: major}]\n'),
            ('null-rule-entry', 'rules: [null]\n'), ('boolean-severity', 'rules: [{id: x, severity: true}]\n'),
            ('wrong-root', 'true\n'), ('broken-yaml', 'rules: [broken'),
        ]:
            reset(); put('.drift-gate.self.yml', content)
            run('schema-' + name, 'input-contract', 'input_error with fresh artifact, exit 2')
        reset()
        policy = yaml.safe_load(policy_original); policy['gate']['fail_on_major_count'] = 'never'
        put('.drift-gate.self.yml', yaml.safe_dump(policy)); append(OPS, '\nPolicy edited.\n')
        run('schema-string-threshold', 'input-contract', 'input_error with fresh artifact, exit 2')

        for name, text in [('whitespace', '\n\n'), ('comment', '\n<!-- reviewed -->\n'),
                           ('unrelated-text', '\nThe weather is sunny.\n')]:
            reset(); append(CONTRACT, text); run('document-' + name, 'document-semantics', 'Cannot certify meaningful contract synchronization')
        reset(); (repo / CONTRACT).unlink(); (repo / CONTRACT).touch()
        run('document-truncated-empty', 'document-semantics', 'fail if contract integrity is required')
        reset(); (repo / CONTRACT).unlink()
        run('document-deleted-with-source', 'control', 'fail')
        reset(False); (repo / CONTRACT).unlink()
        run('document-deleted-alone', 'document-integrity', 'Critical contract deletion should be reviewed')

        for name, target in [('uncovered-python', 'elsewhere/audit_subject.py'),
                             ('ignored-test', 'drift_gate/tests/audit_subject.py'),
                             ('docs-python', 'docs/audit_subject.py'), ('test-root', 'tests/audit_subject.py')]:
            reset(False); (repo / target).parent.mkdir(parents=True, exist_ok=True)
            git('mv', SUBJECT, target)
            run('rename-' + name, 'rename-scope', 'fail; protected source removed')
        reset(False); (repo / SUBJECT).unlink(); run('source-deletion', 'control', 'fail')

        for name, text in [
            ('valid-varargs', args_before.replace('         b=1,', '         *extra,\n         b=1,')),
            ('valid-kwargs', args_before.replace('):', '         **options,\n):')),
            ('ordinary-argument', args_before.replace('):', '         c=2,\n):')),
        ]:
            ast.parse(text)
            reset(False); put(args_path, text)
            run('signature-' + name, 'comment-misclassification', 'fail; valid public signature changed')

        for name, index in [('untracked', False), ('staged', True)]:
            reset(False); put('drift_gate/core/new_audit.py', 'VALUE = 1\n')
            if index: git('add', 'drift_gate/core/new_audit.py')
            run('new-file-' + name, 'collection-scope', 'Only staged file is currently in scope')
        reset(); append(CONTRACT, '\ncalculate now returns 2.\n')
        run('oversize-patch', 'analysis-boundary', 'fail, unavailable analysis must not be treated as checked', extra_env={'DRIFT_GATE_MAX_PATCH_BYTES': '1'})
        reset(); put(SUBJECT, 'bad = "unterminated\n'); append(CONTRACT, '\nReviewed.\n')
        run('syntax-error-with-document', 'analysis-boundary', 'Gate is not a syntax checker; disclose heuristic fallback')
        reset(False); run('empty-diff', 'report-scope', 'pass is valid; preserve no-changes reason')
        reset(False); put('docs/review/audit.md', 'Review\n')
        git('add', 'docs/review/audit.md'); run('docs-only', 'report-scope', 'pass is valid; preserve docs-only reason')
        reset()
        run('zero-push-base', 'first-push', 'input_error; initial comparison needs an explicit policy', base='0' * 40)
    result = {'revision': REVISION, 'fixture_baseline': baseline,
              'at_utc': datetime.now(timezone.utc).isoformat(),
              'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'cases': rows}
    (out / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(rows, indent=2))

if __name__ == '__main__':
    main()
