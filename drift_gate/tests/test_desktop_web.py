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
    assert messages[-1]['type'] == 'progressDocs'
    assert messages[-1]['requested_path'] == str(repo)
    bridge.previewProgress(str(repo), json.dumps(['README.md']))
    preview = messages[-1]
    assert preview['type'] == 'progressPreview'
    bridge.saveProgress(str(repo), json.dumps(preview))
    assert messages[-2]['type'] == 'progressSaved'
    assert messages[-1]['type'] == 'progressReport'
    assert messages[-1]['report']['counts']['complete'] == 0


def test_failed_save_reports_each_invalid_item_and_items_carry_effective_status(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    repo = project(tmp_path)
    bridge = DesktopBridge()
    monkeypatch.setattr(bridge, '_progress_dir', lambda: tmp_path / 'app-data')
    messages = []
    bridge.event.connect(lambda raw: messages.append(json.loads(raw)))
    bridge.previewProgress(str(repo), json.dumps(['README.md']))
    draft = messages[-1]
    draft['requirements'][0]['title'] = ' '
    draft['requirements'][1]['implementation_status'] = 'not_implemented'
    bridge.saveProgress(str(repo), json.dumps(draft))
    failure = messages[-1]
    assert failure['type'] == 'progressError'
    assert {(e['id'], e['field']) for e in failure['errors']} == {
        (draft['requirements'][0]['id'], 'title'),
        (draft['requirements'][1]['id'], 'implementation_note'),
    }
    draft['requirements'][0]['title'] = '로그인'
    draft['requirements'][1]['implementation_note'] = '확인함'
    bridge.saveProgress(str(repo), json.dumps(draft))
    assert messages[-1]['type'] == 'progressReport'
    assert {i['effective_status'] for i in messages[-1]['report']['items']} == {'unknown', 'not_implemented'}


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
