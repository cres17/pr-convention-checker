"""Check implementation-plan assumptions, without modifying product source."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tokenize

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from drift_gate.core.classification.intensity import classify_file_intensity
from drift_gate.core.engine import run
from drift_gate.core.evaluation.evaluator import evaluate
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.policy.loader import load_policy_from_text

BASE = """rules:
  - id: contract
    severity: major
    when:
      any_changed: [src/**]
      min_change_intensity: impl-only
    require:
      groups:
        - name: spec
          any_changed: [spec.md]
gate:
  fail_on_major_count: 1
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    rows = []
    source = ChangedFile('src/a.py', 'modified', patch='@@ -1 +1 @@\n-x=1\n+x=2\n')

    def record(name, observed, expected):
        assert observed == expected, (name, observed, expected)
        rows.append({'name': name, 'observed': observed,
                     'assertion': 'Current behavior matched independently stated expectation'})

    for label, text in [
        ('duplicate-root-rules', BASE + 'rules: []\n'),
        ('unknown-root-rule-key', BASE.replace('rules:', 'rulse:', 1)),
        ('duplicate-required', BASE.replace('        - name: spec',
            '        - required: true\n          required: false\n          name: spec')),
    ]:
        p = load_policy_from_text(text)
        record(label, run([source], policy=p).result, 'pass')

    for label, value in [('negative-threshold', '-1'), ('boolean-threshold', 'false')]:
        p = load_policy_from_text(BASE.replace('fail_on_major_count: 1',
                                              'fail_on_major_count: ' + value))
        satisfied = [source, ChangedFile('spec.md', 'modified', patch='+updated')]
        result = run(satisfied, policy=p)
        record(label, {'result': result.result, 'violations': len(result.violations)},
               {'result': 'fail', 'violations': 0})

    for label, path in [('explicit-doc-rule', 'docs/a.md'),
                        ('explicit-test-rule', 'tests/a.py')]:
        p = load_policy_from_text(BASE.replace('src/**', path).replace('impl-only', 'any'))
        file = ChangedFile(path, 'modified', patch='-old\n+new')
        result = run([file], policy=p)
        direct = evaluate(p, [file], [])
        record(label, {'engine': result.result, 'skip': result.skip_reason,
                       'direct_violations': len(direct[0])},
               {'engine': 'pass', 'skip': 'docs-only' if label == 'explicit-doc-rule' else 'test-only',
                'direct_violations': 1})

    string_file = ChangedFile('src/a.py', 'modified', patch='-message = "old"\n+message = "new"')
    record('runtime-string-is-code', classify_file_intensity(string_file), 'impl-only')
    # Identical changed line has different lexical roles in valid complete inputs.
    contexts = {'comment': '# release\nx=1\n',
                'string': 'message = """\n# release\n"""\n'}
    roles = {}
    for label, text in contexts.items():
        compile(text, '<probe>', 'exec')
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        roles[label] = [tokenize.tok_name[t.type] for t in tokens if '# release' in t.string]
    record('same-line-different-context', roles, {'comment': ['COMMENT'], 'string': ['STRING']})

    inventory = runpy.run_path(str(ROOT / 'docs/assessment/hardening-audit-2026-10-06/inventory.py'))
    for path, expected in [('new-runtime/worker.py', False), ('drift_gate/core/new.py', True),
                           ('desktop-ui/src/worker.js', False)]:
        record('inventory:' + path, inventory['included'](path), expected)

    text = (ROOT / 'drift_gate/adapters/cli/runner.py').read_text()
    collect = text.split('def _collect_inputs(args)', 1)[1].split('def _git_ok', 1)[0]
    record('remote-mode-before-local-git',
           collect.index('if args.pr and args.repo:') < collect.index('git = GitAdapter()'), True)

    output = {'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'python': sys.version, 'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'scope': 'Pure engine, YAML loader, tokenizer examples and local source inventory; no live GitHub or package run',
              'cases': rows}
    with args.out.open('x', encoding='utf-8') as file:
        json.dump(output, file, ensure_ascii=False, indent=2)
        file.write('\n')
    print(json.dumps({'cases': len(rows), 'output': str(args.out)}))


if __name__ == '__main__':
    main()
