"""2026-10-23 QA 후속 수정의 회귀 검사."""
import json
import subprocess
import sys

import pytest

from drift_gate.adapters import org_service
from drift_gate.adapters.mcp.server import handle_request
from drift_gate.adapters.run_store import Conflict, RunStoreError
from drift_gate.core.engine import run
from drift_gate.reporters.markdown import MarkdownReporter
from drift_gate.tests.test_multi_review_adapters import repository


def _check(root, *extra):
    return subprocess.run([sys.executable, '-c', 'from drift_gate.adapters.cli.runner import run_cli; run_cli()', 'check', '--policy', '.drift-gate.yml',
                           *extra], cwd=root, capture_output=True, encoding='utf-8', timeout=60, check=False)


def test_untracked_files_are_reported_in_markdown_and_stderr(tmp_path):
    root = repository(tmp_path)
    (root / 'src/new.py').write_text('new = 1\n', encoding='utf-8')
    text = _check(root)
    assert 'Untracked files not evaluated:** 1' in text.stdout
    assert 'src/new.py' in text.stdout
    machine = _check(root, '--json')
    assert json.loads(machine.stdout)['execution']['untracked_skipped'] == ['src/new.py']
    assert '1 untracked file(s) were not evaluated' in machine.stderr


def test_clean_tree_has_no_untracked_notice(tmp_path):
    root = repository(tmp_path)
    assert 'Untracked files' not in _check(root).stdout
    assert 'untracked' not in _check(root, '--json').stderr


def test_untracked_notice_is_capped():
    result = run([])
    result.execution = {'run_id': 'r', 'untracked_skipped': [f'n{i}.py' for i in range(25)]}
    markdown = MarkdownReporter().render(result)
    assert '`n19.py`' in markdown and '`n20.py`' not in markdown
    assert '5 more (see the JSON report)' in markdown


def test_mcp_unknown_tool_is_invalid_params():
    response = handle_request({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                               'params': {'name': 'nope', 'arguments': {}}})
    assert response['error'] == {'code': -32602, 'message': 'unknown tool: nope'}


@pytest.mark.parametrize('value', ['abc', '0', '-1', '1.5', '١'])
def test_action_rejects_bad_pr_number_without_traceback(monkeypatch, capsys, value):
    from drift_gate.adapters.github_action import runner
    monkeypatch.setenv('GITHUB_TOKEN', 'fixture')
    monkeypatch.setenv('REPO', 'o/r')
    monkeypatch.setenv('PR_NUMBER', value)
    monkeypatch.delenv('CONTRACT_PROOFS', raising=False)
    with pytest.raises(SystemExit) as exc:
        runner.main()
    assert exc.value.code == 1
    assert '::error title=Drift Gate configuration::PR_NUMBER must be a positive integer' in capsys.readouterr().err


class _Sequence:
    def __init__(self, errors):
        self.errors = list(errors)
        self.appended = []

    def read(self):
        return self.appended

    def append(self, entry, *, expected_length):
        if self.errors:
            raise self.errors.pop(0)
        self.appended.append(entry)


def _service(tmp_path, monkeypatch, sequence):
    monkeypatch.setattr(org_service, 'Sequence', lambda path: sequence)
    service = org_service.OrgService.__new__(org_service.OrgService)
    service._tenant = lambda tenant_id: tmp_path / tenant_id
    service.clock = lambda: __import__('datetime').datetime(2026, 10, 23)
    return service


def test_audit_retries_only_conflicts(tmp_path, monkeypatch):
    sequence = _Sequence([Conflict('raced'), Conflict('raced')])
    _service(tmp_path, monkeypatch, sequence)._audit('t', 'a', 'x', 'ok')
    assert len(sequence.appended) == 1


def test_audit_surfaces_non_conflict_errors(tmp_path, monkeypatch):
    sequence = _Sequence([RunStoreError('Run store entry limit reached')])
    with pytest.raises(RunStoreError, match='entry limit'):
        _service(tmp_path, monkeypatch, sequence)._audit('t', 'a', 'x', 'ok')


def test_audit_still_reports_persistent_contention(tmp_path, monkeypatch):
    sequence = _Sequence([Conflict('raced')] * 5)
    with pytest.raises(org_service.OrgError, match='audit-log-contended'):
        _service(tmp_path, monkeypatch, sequence)._audit('t', 'a', 'x', 'ok')
