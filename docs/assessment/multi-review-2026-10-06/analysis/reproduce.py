import contextlib
import hashlib
import io
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from drift_gate.adapters.git import client
from drift_gate.adapters.ast.analyzer import enrich_semantic_signals
from drift_gate.core.classification.intensity import classify_file_intensity
from drift_gate.core.engine import run
from drift_gate.core.patch_lines import changed_lines
from drift_gate.core.policy.loader import load_policy_from_text

OUT = Path(__file__).parent
POLICY = '''rules:
  - id: contract
    when:
      any_changed: ['src/**']
      min_change_intensity: impl-only
    require:
      groups:
        - name: docs
          all_changed: ['spec.md']
    severity: major
gate:
  fail_on_major_count: 1
'''

def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.PIPE)

def initialize(root):
    git(root, 'init')
    (root / 'src').mkdir()
    (root / 'src/a.py').write_text('def record():\n    print("called")\n    return 1\n\n# before\n')
    git(root, 'add', '.')
    git(root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'baseline')

def check(root):
    adapter = client.GitAdapter(root)
    files = enrich_semantic_signals(adapter.get_changed_files('HEAD'))
    result = run(files, policy=load_policy_from_text(POLICY)).to_dict()
    return {'result': result, 'provenance': adapter.provenance,
            'files': [{**f.to_dict(), 'raw_lines': changed_lines(f), 'code_lines': changed_lines(f, code_only=True),
                       'intensity': classify_file_intensity(f)} for f in files]}

results = {}
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    initialize(root)
    src = root / 'src/a.py'
    source = src.read_text().replace('# before', '# after') + '++record()\n'
    src.write_text(source)
    actual_execution = io.StringIO()
    with contextlib.redirect_stdout(actual_execution):
        exec(compile(source, '<valid-python>', 'exec'), {})
    results['header_prefix_bypass'] = check(root)
    results['header_prefix_bypass']['runtime_stdout'] = actual_execution.getvalue()
    src.write_text(source.replace('++record()', '+record()'))
    results['header_prefix_control'] = check(root)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    initialize(root)
    original_git = client._git
    mutated = False

    def injected_git(args, cwd):
        global mutated
        value = original_git(args, cwd)
        if '--name-status' in args and not mutated:
            mutated = True
            source = root / 'src/a.py'
            source.write_text(source.read_text() + 'record()\n')
        return value

    with patch.object(client, '_git', side_effect=injected_git):
        results['snapshot_race'] = check(root)
    results['snapshot_race']['actual_patch'] = git(root, 'diff', 'HEAD').decode()
    results['snapshot_race']['actual_snapshot_sha256'] = hashlib.sha256(git(root, 'diff', '--no-ext-diff', '--no-textconv', '--find-renames', 'HEAD', '--')).hexdigest()
    results['snapshot_race_control'] = check(root)

(OUT / 'results.json').write_text(json.dumps(results, indent=2))
print(json.dumps({key: {'decision': val['result']['result'], 'files': len(val['files']),
                       'intensities': [f['intensity'] for f in val['files']]}
                  for key, val in results.items()}, indent=2))
