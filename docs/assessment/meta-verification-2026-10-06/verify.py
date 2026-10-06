"""Audit saved evidence and exercise the product against real Git mutations.

All destructive Git operations are confined to a temporary clone. Expected
outcomes are defined here before running the product. No production edits.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent / 'saved-evidence'
HEAD = 'f43cada2ea177b63cb0ac4a79be37071113a5191'
BASE = '01e28e1620941a539d3e9c14972201b30adafd3b'
CONTRACTS = ['docs/contracts/gate-and-inputs.md', 'docs/contracts/mcp-transport.md',
             'docs/ops/drift-gate-self-check.md']

def normalize(value):
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items() if k != 'runtime_seconds'}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    return value

def embedded_json(path):
    text = path.read_text(encoding='utf-8')
    for raw in re.findall(r'<pre[^>]*>(.*?)</pre>', text, flags=re.S):
        try:
            result = json.loads(html.unescape(re.sub(r'<[^>]+>', '', raw)))
        except (ValueError, TypeError):
            continue
        if isinstance(result, dict) and 'summary' in result:
            return result
    raise AssertionError('No embedded evaluation JSON')

def assert_visible_summary(path, result):
    text = path.read_text(encoding='utf-8')
    decision = result['result']
    assert f'class="status status-{decision}">{decision.upper()}' in text
    count = result['scan_metrics']['scanned_files']
    assert f'<span>Scanned Files</span><b>{count}</b>' in text

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True, type=Path)
    out = parser.parse_args().out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    rows = []
    with tempfile.TemporaryDirectory(prefix='driftgate-meta-verification-') as tmp:
        checkout = Path(tmp) / 'repo'
        subprocess.run(['git', 'clone', '--shared', '--no-checkout', str(ROOT), str(checkout)],
                       check=True, capture_output=True)
        env = {**os.environ, 'PYTHONPATH': str(checkout), 'ANTHROPIC_API_KEY': ''}

        def git(*args):
            return subprocess.check_output(['git', *args], cwd=checkout, stderr=subprocess.PIPE)

        def reset(revision=HEAD):
            git('checkout', '--detach', '--force', revision)
            git('reset', '--hard', revision)
            git('clean', '-fd')

        def write(path, content):
            target = checkout / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8')

        def execute(name, args, expected):
            result = subprocess.run([sys.executable, *args], cwd=checkout, env=env,
                                    capture_output=True, timeout=180)
            (out / (name + '.stdout')).write_bytes(result.stdout)
            (out / (name + '.stderr')).write_bytes(result.stderr)
            data = json.loads((out / (name + '.json')).read_text())
            actual = data.get('evaluation', data).get('result', 'input_error')
            row = {'name': name, 'arguments': args, 'expected': expected, 'actual': actual,
                   'exit_code': result.returncode, 'matches_expected': actual == expected}
            row['expected_exit_code'] = {'pass': 0, 'fail': 1, 'input_error': 2}[expected]
            row['matches_expected'] &= result.returncode == row['expected_exit_code']
            if 'coverage' in data:
                row['coverage'] = data['coverage']
            rows.append(row)
            return data

        def check(name, expected, base=BASE):
            return execute(name, ['scripts/check_self.py', '--base', base,
                '--out', str(out / (name + '.json'))], expected)

        reset()
        for name in ['push', 'pr']:
            saved = json.loads((EVIDENCE / name / 'self-check.json').read_text())
            metadata = json.loads((EVIDENCE / (name + '-run.json')).read_text())
            assert metadata['headSha'] == HEAD and metadata['conclusion'] == 'success'
            actual = check(name + '-replay', 'pass', saved['requested_base'])
            paths = set(git('diff', '--name-only', '-z', saved['requested_base'], HEAD).decode().strip('\0').split('\0'))
            coverage = actual['coverage']
            reported = set(coverage['matched']) | set(coverage['unmatched']) | set(coverage['ignored'])
            rows[-1]['git_path_set_equal'] = paths == reported
            rows[-1]['saved_evidence_equal_except_runtime'] = normalize(saved) == normalize(actual)
            assert paths == reported and normalize(saved) == normalize(actual), name
        process = subprocess.run([sys.executable, '-m', 'drift_gate', 'check', '--base', BASE,
            '--policy', '.drift-gate.self.yml', '--json', '--anthropic-api-key', '',
            '--out-html', str(out / 'latest-gate.html')], cwd=checkout, env=env,
            capture_output=True, timeout=180)
        (out / 'latest-gate.stdout').write_bytes(process.stdout)
        (out / 'latest-gate.stderr').write_bytes(process.stderr)
        latest = json.loads(process.stdout)
        saved = json.loads((EVIDENCE / 'push/self-check.json').read_text())
        assert process.returncode == 0 and normalize(latest) == normalize(saved['evaluation'])
        assert normalize(embedded_json(out / 'latest-gate.html')) == normalize(latest)
        assert_visible_summary(out / 'latest-gate.html', latest)
        rows.append({'name': 'latest-html-agrees-with-remote-evaluation', 'matches_expected': True,
                     'actual': latest['result'], 'expected': 'pass', 'exit_code': process.returncode})
        # Independently remove each required document from the actual reviewed tree.
        for index, document in enumerate(CONTRACTS):
            reset()
            (checkout / document).unlink()
            check('missing-required-' + str(index + 1), 'fail')
        reset()
        for document in CONTRACTS:
            (checkout / document).unlink()
        write('docs/review/unrelated.md', 'A review says everything is safe.\n')
        git('add', 'docs/review/unrelated.md')
        check('unrelated-report-cannot-substitute', 'fail')
        reset()
        for document in CONTRACTS:
            write(document, '# Reviewed\nAll changes look good.\n')
        check('content-free-contract-substitution', 'fail')
        reset()
        check('invalid-base', 'input_error', 'meta-audit-absent-ref')
        (checkout / '.drift-gate.self.yml').unlink()
        check('missing-policy', 'input_error')
        reset()
        write('.drift-gate.self.yml', 'rules: [broken')
        check('malformed-policy', 'input_error')
        reset()
        check('wrong-valid-base-head', 'fail', HEAD)
        reset()
        write('drift_gate/core/meta_audit_new.py', 'VALUE = 42\n')
        check('untracked-new-source', 'fail', HEAD)
        git('add', 'drift_gate/core/meta_audit_new.py')
        check('staged-new-source', 'fail', HEAD)
        reset()
        target = checkout / 'drift_gate/core/engine.py'
        target.write_text(target.read_text() + '\nMETA_AUDIT_VALUE = 42\n', encoding='utf-8')
        write('.drift-gate.self.yml', 'rules: []\ngate:\n  fail_on_blocker: true\n  fail_on_major_count: 1\n')
        check('policy-removes-all-its-own-rules', 'fail', HEAD)
        reset()
        target = checkout / 'drift_gate/desktop/resources.py'
        target.write_text(target.read_text() + '\nMETA_AUDIT_VALUE = 42\n', encoding='utf-8')
        check('uncovered-production-source', 'fail', HEAD)
        reset()
        target = checkout / 'drift_gate/core/engine.py'
        target.write_text(target.read_text() + '\nMETA_AUDIT_VALUE = 42\n', encoding='utf-8')
        (checkout / CONTRACTS[0]).unlink()
        check('deleted-contract-cannot-substitute', 'fail', HEAD)

        # Recreate the historical HTML using the actual historical product/policy.
        reset(BASE)
        oldbase = '729a3cde70c3457b633798bb50273d815d4d2c12'
        process = subprocess.run([sys.executable, '-m', 'drift_gate', 'check', '--base', oldbase,
            '--json', '--anthropic-api-key', '', '--out-html', str(out / 'historical-gate.html')],
            cwd=checkout, env=env, capture_output=True, timeout=180)
        (out / 'historical-replay.stdout').write_bytes(process.stdout)
        (out / 'historical-replay.stderr').write_bytes(process.stderr)
        saved = json.loads((ROOT / 'docs/assessment/self-verification-2026-10-06/product-run/gate.stdout').read_text())
        original_html = embedded_json(ROOT / 'docs/assessment/self-verification-2026-10-06/product-run/gate.html')
        replay = json.loads(process.stdout)
        assert normalize(saved) == normalize(original_html) == normalize(replay)
        assert normalize(embedded_json(out / 'historical-gate.html')) == normalize(replay)
        assert_visible_summary(ROOT / 'docs/assessment/self-verification-2026-10-06/product-run/gate.html', original_html)
        rows.append({'name': 'historical-html-integrity-and-replay', 'matches_expected': True,
            'old_head': BASE, 'old_base': oldbase, 'exit_code': process.returncode,
            'actual': replay['result'], 'expected': 'warn',
            'note': 'Historical HTML is authentic but describes an older commit and example policy.'})
    receipt = {'head': HEAD, 'measured_at_utc': datetime.now(timezone.utc).isoformat(),
        'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'saved_evidence_sha256': {str(p.relative_to(EVIDENCE)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in sorted(EVIDENCE.rglob('*')) if p.is_file()},
        'comparison_exclusion': 'runtime_seconds only', 'cases': rows,
        'limitations_found': [r['name'] for r in rows if not r['matches_expected']]}
    (out / 'results.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'cases': len(rows), 'limitations_found': receipt['limitations_found']}, indent=2))

if __name__ == '__main__':
    main()
