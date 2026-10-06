"""Repository policy controls are fixed independently of the real diff's result."""
from pathlib import Path
import json
import shutil
import subprocess
import sys

import pytest

from drift_gate.adapters.policy_loader import load_policy
from drift_gate.core.engine import run
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.tests.test_git_collection import repository, git
from scripts.check_self import inspect_repository

ROOT = Path(__file__).resolve().parents[2]
POLICY = load_policy(ROOT / '.drift-gate.self.yml')


@pytest.mark.parametrize('source,document', [
    ('drift_gate/core/engine.py', 'docs/contracts/gate-and-inputs.md'),
    ('drift_gate/adapters/git/client.py', 'docs/contracts/gate-and-inputs.md'),
    ('drift_gate/adapters/mcp/server.py', 'docs/contracts/mcp-transport.md'),
    ('drift_gate/desktop/progress_service.py', 'docs/contracts/progress-storage.md'),
    ('drift_gate/desktop/json_store.py', 'docs/contracts/progress-storage.md'),
    ('drift_gate/desktop/web_app.py', 'docs/contracts/desktop-bridge.md'),
    ('desktop-ui/src/features/project-progress/rebase.ts', 'docs/contracts/desktop-bridge.md'),
    ('packaging/verify_package.py', 'docs/ops/drift-gate-self-check.md'),
    ('.github/workflows/ci.yml', 'docs/ops/drift-gate-self-check.md'),
])
def test_self_policy_requires_its_own_contract_not_an_unrelated_report(source, document):
    change = ChangedFile(path=source, status='modified', patch='-value = 1\n+value = 2\n')
    unrelated = ChangedFile(path='docs/review/unrelated.md', status='modified', patch='+review\n')
    required = ChangedFile(path=document, status='modified', patch='+updated contract\n')
    assert run([change], policy=POLICY).result == 'fail'
    assert run([change, unrelated], policy=POLICY).result == 'fail'
    assert run([change, required], policy=POLICY).result == 'pass'


def test_self_policy_tests_and_comment_only_changes_do_not_require_contract_rewrites():
    files = [ChangedFile(path='drift_gate/tests/test_example.py', status='modified', patch='+def test_case(): pass\n'),
             ChangedFile(path='desktop-ui/src/example.test.ts', status='modified', patch='+test("x", () => {});\n'),
             ChangedFile(path='drift_gate/core/engine.py', status='modified', patch='+# explanatory comment\n', before_source='', after_source='# explanatory comment\n')]
    assert run(files, policy=POLICY).result == 'pass'


def test_self_check_collects_real_diff_and_reports_uncovered_paths(tmp_path):
    root = repository(tmp_path)
    shutil.copyfile(ROOT / '.drift-gate.self.yml', root / '.drift-gate.self.yml')
    for name in ['drift_gate/core/engine.py', 'elsewhere.py']:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('value = 2\n', encoding='utf-8')
    git(root, 'add', 'drift_gate/core/engine.py', 'elsewhere.py')
    for document in (ROOT / 'docs/contracts').glob('*.md'):
        target = root / 'docs/contracts' / document.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(document, target)
    target = root / 'docs/ops/drift-gate-self-check.md'
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / 'docs/ops/drift-gate-self-check.md', target)
    result = inspect_repository(root, 'HEAD')
    assert result['evaluation']['result'] == 'fail'
    assert result['coverage']['matched']['drift_gate/core/engine.py'] == ['self-engine-contract']
    assert result['coverage']['unmatched'] == ['elsewhere.py']


@pytest.mark.parametrize('failure', ['policy-missing', 'policy-invalid', 'base-invalid'])
def test_self_check_preserves_input_error_evidence(tmp_path, failure):
    root = repository(tmp_path)
    if failure == 'policy-invalid':
        (root / '.drift-gate.self.yml').write_text('rules: [broken', encoding='utf-8')
    elif failure == 'base-invalid':
        shutil.copyfile(ROOT / '.drift-gate.self.yml', root / '.drift-gate.self.yml')
    output = root / 'build/result.json'
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/check_self.py'), '--repo', str(root),
        '--base', 'absent-ref' if failure == 'base-invalid' else 'HEAD', '--out', str(output)],
        capture_output=True, timeout=20)
    assert result.returncode == 2, result.stderr
    assert json.loads(output.read_text(encoding='utf-8'))['error']['code'] == 'input_error'
