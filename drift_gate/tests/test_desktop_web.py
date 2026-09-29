"""Bridge contract checks; no model calls or real user repository mutations."""
import json
import os
import re
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
pytest.importorskip('PySide6.QtWebEngineWidgets')
from PySide6.QtWidgets import QApplication
from drift_gate.desktop.web_app import DesktopBridge, scan_payload
from drift_gate.tests.test_subscription_review import scan, response
from drift_gate.desktop.subscription_review import parse_review
from drift_gate.tests.test_progress_service import project


def of_type(messages, kind):
    """Newest message of a type; a save also sends a trailing progressHistory event."""
    return next(m for m in reversed(messages) if m['type'] == kind)


def settle(bridge):
    """Wait for the progress worker, then deliver its queued events."""
    assert bridge.progress_pool.waitForDone(10000)
    QApplication.processEvents()


def test_payload_uses_engine_result_without_reclassification():
    value = scan()
    payload = scan_payload(value)
    assert payload['result'] == value.result.to_dict()
    assert payload['policy'] == value.policy_source
    assert payload['files'] == []


def test_bridge_keeps_llm_separate_and_exports(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    bridge = DesktopBridge()
    bridge.scan = scan()
    bridge.review = parse_review(response('fail'), 'codex')
    target = tmp_path / 'report.json'
    monkeypatch.setattr('drift_gate.desktop.web_app.QFileDialog.getSaveFileName',lambda *args: (str(target),''))
    bridge.exportReport('json')
    data = json.loads(target.read_text(encoding='utf-8'))
    assert data['result'] == 'pass'
    assert data['llm_review']['verdict'] == 'fail'


def test_export_suggests_project_named_file(monkeypatch):
    QApplication.instance() or QApplication([])
    bridge = DesktopBridge()
    bridge.scan = scan()
    seen = []
    monkeypatch.setattr('drift_gate.desktop.web_app.QFileDialog.getSaveFileName',
                        lambda *args: (seen.append(args[2]), ('', ''))[1])
    bridge.exportReport('html')
    assert re.fullmatch(r'.*[\\/]sample_drift-report_\d{8}-\d{6}\.html', seen[0])


def test_bridge_does_not_start_llm_without_scan():
    QApplication.instance() or QApplication([])
    bridge = DesktopBridge()
    bridge.startReview('codex', '')
    assert bridge.review_worker is None


def test_progress_bridge_reads_documents_and_persists_reviewed_baseline(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    repo = project(tmp_path)
    bridge = DesktopBridge()
    monkeypatch.setattr(bridge, '_progress_dir', lambda: tmp_path / 'app-data')
    messages = []
    bridge.event.connect(lambda raw: messages.append(json.loads(raw)))
    bridge.listProjectDocs(str(repo))
    settle(bridge)
    assert messages[-1]['type'] == 'progressDocs'
    assert messages[-1]['requested_path'] == str(repo)
    bridge.previewProgress(str(repo), json.dumps(['README.md']))
    settle(bridge)
    preview = messages[-1]
    assert preview['type'] == 'progressPreview'
    bridge.saveProgress(str(repo), json.dumps(preview))
    settle(bridge)
    assert [m['type'] for m in messages[-3:]] == ['progressSaved', 'progressReport', 'progressHistory']
    assert of_type(messages, 'progressReport')['report']['counts']['complete'] == 0
    assert len(messages[-1]['snapshots']) == 1


def test_failed_save_reports_each_invalid_item_and_items_carry_effective_status(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    repo = project(tmp_path)
    bridge = DesktopBridge()
    monkeypatch.setattr(bridge, '_progress_dir', lambda: tmp_path / 'app-data')
    messages = []
    bridge.event.connect(lambda raw: messages.append(json.loads(raw)))
    bridge.previewProgress(str(repo), json.dumps(['README.md']))
    settle(bridge)
    draft = messages[-1]
    draft['requirements'][0]['title'] = ' '
    draft['requirements'][1]['implementation_status'] = 'not_implemented'
    bridge.saveProgress(str(repo), json.dumps(draft))
    settle(bridge)
    failure = messages[-1]
    assert failure['type'] == 'progressError'
    assert {(e['id'], e['field']) for e in failure['errors']} == {
        (draft['requirements'][0]['id'], 'title'),
        (draft['requirements'][1]['id'], 'implementation_note'),
    }
    draft['requirements'][0]['title'] = '로그인'
    draft['requirements'][1]['implementation_note'] = '확인함'
    bridge.saveProgress(str(repo), json.dumps(draft))
    settle(bridge)
    assert {i['effective_status'] for i in of_type(messages, 'progressReport')['report']['items']} == {'unknown', 'not_implemented'}


def test_open_document_only_opens_text_files_inside_the_scanned_repository(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    repo = project(tmp_path)
    (repo / 'run.sh').write_text('echo hi\n', encoding='utf-8')
    bridge = DesktopBridge()
    bridge.scan = scan()
    bridge.scan = type(bridge.scan)(repo, bridge.scan.base, 0, bridge.scan.result)
    opened, messages = [], []
    monkeypatch.setattr('drift_gate.desktop.web_app.QDesktopServices.openUrl',
                        lambda url: (opened.append(url.toLocalFile()), True)[1])
    bridge.event.connect(lambda raw: messages.append(json.loads(raw)))
    bridge.openDocument('README.md')
    assert opened == [str((repo / 'README.md').resolve())]
    for bad in ('run.sh', '../x.md', 'docs/**', 'missing.md'):
        bridge.openDocument(bad)
    assert len(opened) == 1
    assert [m['type'] for m in messages] == ['error'] * 4


def test_progress_requests_run_off_the_ui_thread_in_request_order(tmp_path, monkeypatch):
    import threading
    QApplication.instance() or QApplication([])
    repo = project(tmp_path)
    bridge = DesktopBridge()
    monkeypatch.setattr(bridge, '_progress_dir', lambda: tmp_path / 'app-data')
    threads, messages = [], []
    real = __import__('drift_gate.desktop.web_app', fromlist=['x']).list_documents

    def slow_list(path):
        threads.append(threading.current_thread())
        return real(path)
    monkeypatch.setattr('drift_gate.desktop.web_app.list_documents', slow_list)
    bridge.event.connect(lambda raw: messages.append(json.loads(raw)['type']))
    bridge.listProjectDocs(str(repo))
    bridge.previewProgress(str(repo), json.dumps(['README.md']))
    bridge.previewProgress(str(repo), '{broken')
    settle(bridge)
    assert threads and threads[0] is not threading.main_thread()
    assert messages == ['progressDocs', 'progressPreview', 'progressError']


def _saved_baseline(tmp_path, monkeypatch):
    repo = project(tmp_path)
    (repo / "README.md").write_text(
        "# Service\n- [x] 로그인 화면을 `src/login.py`에 만든다\n[가이드](docs/gone.md)\n", encoding="utf-8")
    bridge = DesktopBridge()
    monkeypatch.setattr(bridge, '_progress_dir', lambda: tmp_path / 'app-data')
    messages = []
    bridge.event.connect(lambda raw: messages.append(json.loads(raw)))
    bridge.previewProgress(str(repo), json.dumps(['README.md']))
    settle(bridge)
    bridge.saveProgress(str(repo), json.dumps(messages[-1]))
    settle(bridge)
    assert of_type(messages, 'progressReport')
    return repo, bridge, messages


def test_progress_link_check_runs_on_the_saved_baseline(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    repo, bridge, messages = _saved_baseline(tmp_path, monkeypatch)
    bridge.checkProgressLinks(str(repo))
    settle(bridge)
    result = messages[-1]
    assert result['type'] == 'progressLinks'
    assert [(i['target'], i['confidence']) for i in result['issues']] == [('docs/gone.md', 'high')]


@pytest.mark.parametrize('kind,marker', [('md', '# 프로젝트 현황'), ('json', '"doc_claims_unbacked": 1')])
def test_progress_report_export_uses_project_file_name(tmp_path, monkeypatch, kind, marker):
    QApplication.instance() or QApplication([])
    repo, bridge, messages = _saved_baseline(tmp_path, monkeypatch)
    suggested = []
    target = tmp_path / f'out.{kind}'
    monkeypatch.setattr('drift_gate.desktop.web_app.QFileDialog.getSaveFileName',
                        lambda *args: (suggested.append(args[2]), (str(target), ''))[1])
    bridge.exportProgress(str(repo), kind)
    settle(bridge)
    assert re.fullmatch(rf'.*[\\/]repo_(?:[\w.-]+_)?progress_\d{{8}}-\d{{6}}\.{kind}', suggested[0])
    assert messages[-1] == {'type': 'progressExported', 'requested_path': str(repo), 'file': str(target)}
    assert marker in target.read_text(encoding='utf-8')
    bridge.exportProgress(str(repo), 'exe')  # unknown kinds are ignored
    assert len(suggested) == 1


def test_scan_reports_which_progress_evidence_it_touches(tmp_path, monkeypatch):
    from drift_gate.core.models.changed_file import ChangedFile
    from drift_gate.desktop.service import DesktopScan
    QApplication.instance() or QApplication([])
    repo, bridge, messages = _saved_baseline(tmp_path, monkeypatch)
    draft = of_type(messages, 'progressSaved')['baseline']
    draft['requirements'][0].update(implementation_status='implemented',
                                    evidence={'path': 'src/login.py', 'line': 1, 'note': '확인'})
    bridge.saveProgress(str(repo), json.dumps(draft))
    settle(bridge)
    (repo / 'src/login.py').write_text('def login():\n    return 2\n', encoding='utf-8')
    base = scan()
    touched = DesktopScan(repo, 'HEAD', 1, base.result, (ChangedFile('src/login.py', 'modified'),))
    messages.clear()
    bridge._emit_scan_impact(touched, 'scan-1')
    settle(bridge)
    assert [m['type'] for m in messages] == ['scanImpact']
    impact = messages[0]
    assert impact['scan_at'] == 'scan-1'
    assert [(i['path'], i['invalidated']) for i in impact['items']] == [('src/login.py', True)]
    untouched = DesktopScan(repo, 'HEAD', 1, base.result, (ChangedFile('docs/other.md', 'added'),))
    messages.clear()
    bridge._emit_scan_impact(untouched, 'scan-2')
    settle(bridge)
    assert messages == []  # nothing to say, and no progress error either


def test_missing_policy_is_previewed_and_created_only_on_request(tmp_path):
    import subprocess
    from drift_gate.desktop.app import ScanWorker
    QApplication.instance() or QApplication([])
    repo = tmp_path / 'fresh'
    (repo / 'src/routes').mkdir(parents=True)
    (repo / 'src/routes/users.py').write_text('x\n', encoding='utf-8')
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    seen = []
    worker = ScanWorker(str(repo), 'HEAD')
    worker.policy_missing.connect(lambda repository: seen.append(('missing', repository)))
    worker.failed.connect(lambda message: seen.append(('failed', message)))
    worker.run()
    assert seen[0] == ('missing', str(repo.resolve())) and seen[1][0] == 'failed'

    bridge = DesktopBridge()
    messages = []
    bridge.event.connect(lambda raw: messages.append(json.loads(raw)))
    bridge.previewPolicy(str(repo), 'auto')
    settle(bridge)
    assert messages[-1]['type'] == 'policyPreview' and messages[-1]['preset'] == 'api'
    assert not (repo / '.drift-gate.yml').exists()
    bridge.createPolicy(str(repo), 'auto')
    settle(bridge)
    assert messages[-1]['type'] == 'policyCreated' and (repo / '.drift-gate.yml').is_file()
    bridge.createPolicy(str(repo), 'auto')  # second attempt must not overwrite
    settle(bridge)
    assert messages[-1]['type'] == 'error' and '덮어쓰지' in messages[-1]['message']
