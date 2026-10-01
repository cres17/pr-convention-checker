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
    from pathlib import Path
    assert [Path(item) for item in opened] == [(repo / 'README.md').resolve()]  # toLocalFile() uses '/' on Windows
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
    assert messages[-1] == {'type': 'progressExported', 'requested_path': str(repo), 'file': str(target), 'request_id': '', 'request_done': True}
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


def isolated_settings(bridge, tmp_path):
    """Keep tests from touching the real per-user settings."""
    from PySide6.QtCore import QSettings
    bridge.settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat)


def test_test_results_are_linked_to_items_after_the_user_picks_a_file(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    repo, bridge, messages = _saved_baseline(tmp_path, monkeypatch)
    isolated_settings(bridge, tmp_path)
    draft = of_type(messages, 'progressSaved')['baseline']
    draft['requirements'][0]['test_patterns'] = ['test_login']
    bridge.saveProgress(str(repo), json.dumps(draft))
    settle(bridge)
    results = tmp_path / 'junit.xml'
    results.write_text('<testsuite><testcase classname="t" name="test_login_ok"/>'
                       '<testcase classname="t" name="test_login_bad"><failure/></testcase></testsuite>', encoding='utf-8')
    chosen = []
    monkeypatch.setattr('drift_gate.desktop.web_app.QFileDialog.getOpenFileName',
                        lambda *args: (chosen.append(args[2]), (str(results), ''))[1])
    bridge.loadTestResults(str(repo))
    settle(bridge)
    assert chosen == [str(repo.resolve())]
    linked = messages[-1]
    assert linked['type'] == 'progressTests' and linked['file'] == 'junit.xml' and linked['total'] == 2
    only = next(iter(linked['items'].values()))
    assert (only['passed'], only['failed']) == (1, 1)
    monkeypatch.setattr('drift_gate.desktop.web_app.QFileDialog.getOpenFileName', lambda *args: ('', ''))
    count = len(messages)
    bridge.loadTestResults(str(repo))  # cancellation completes loading without replacing records
    settle(bridge)
    assert len(messages) == count + 1
    assert messages[-1] == {"type": "progressTestsCancelled", "requested_path": str(repo), "request_id": "", "request_done": True}
    results.write_text('not a result file', encoding='utf-8')
    monkeypatch.setattr('drift_gate.desktop.web_app.QFileDialog.getOpenFileName', lambda *args: (str(results), ''))
    bridge.loadTestResults(str(repo))
    settle(bridge)
    assert messages[-1]['type'] == 'progressError'


def test_chosen_result_file_is_remembered_and_read_again_when_the_project_opens(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    repo, bridge, messages = _saved_baseline(tmp_path, monkeypatch)
    isolated_settings(bridge, tmp_path)
    draft = of_type(messages, 'progressSaved')['baseline']
    draft['requirements'][0]['test_patterns'] = ['test_login']
    bridge.saveProgress(str(repo), json.dumps(draft))
    settle(bridge)
    results = tmp_path / 'junit.xml'
    results.write_text('<testsuite><testcase classname="t" name="test_login_ok"/></testsuite>', encoding='utf-8')
    monkeypatch.setattr('drift_gate.desktop.web_app.QFileDialog.getOpenFileName', lambda *args: (str(results), ''))
    bridge.loadTestResults(str(repo))
    settle(bridge)
    assert 'remembered' not in of_type(messages, 'progressTests')

    messages.clear()
    bridge.inspectProgress(str(repo))  # what the screen does when the project is opened
    settle(bridge)
    assert [m['type'] for m in messages] == ['progressReport', 'progressHistory', 'progressTests']
    assert messages[-1]['remembered'] is True and messages[-1]['file'] == 'junit.xml'

    results.unlink()  # a vanished file is skipped without an error
    messages.clear()
    bridge.inspectProgress(str(repo))
    settle(bridge)
    assert [m['type'] for m in messages] == ['progressReport', 'progressHistory']

    results.write_text('<testsuite/>', encoding='utf-8')
    bridge.forgetTestResults(str(repo))
    messages.clear()
    bridge.inspectProgress(str(repo))
    settle(bridge)
    assert 'progressTests' not in [m['type'] for m in messages]


def test_progress_bridge_roundtrips_document_roles_and_context_only_baseline(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    repo = project(tmp_path)
    bridge = DesktopBridge()
    monkeypatch.setattr(bridge, '_progress_dir', lambda: tmp_path / 'app-data')
    messages = []
    bridge.event.connect(lambda raw: messages.append(json.loads(raw)))
    bridge.previewProgress(str(repo), json.dumps([{'path': 'README.md', 'kind': 'past'}]))
    settle(bridge)
    preview = of_type(messages, 'progressPreview')
    assert preview['document_kinds'] == {'README.md': 'past'}
    assert preview['requirements'] == []
    bridge.saveProgress(str(repo), json.dumps(preview))
    settle(bridge)
    assert of_type(messages, 'progressReport')['report']['total'] == 0
    bridge.listProjectDocs(str(repo))
    settle(bridge)
    assert of_type(messages, 'progressDocs')['baseline']['document_kinds'] == {'README.md': 'past'}


def test_test_picker_cancel_completes_without_changing_remembered_file(tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    QApplication.instance() or QApplication([])
    repo = project(tmp_path)
    bridge = DesktopBridge()
    bridge.settings = QSettings(str(tmp_path / "cancel.ini"), QSettings.Format.IniFormat)
    key = bridge._results_key(str(repo))
    bridge.settings.setValue(key, "old.xml")
    messages = []
    bridge.event.connect(lambda raw: messages.append(json.loads(raw)))
    monkeypatch.setattr("drift_gate.desktop.web_app.QFileDialog.getOpenFileName", lambda *args: ("", ""))
    bridge.loadTestResults(str(repo))
    assert messages == [{"type": "progressTestsCancelled", "requested_path": str(repo), "request_id": "", "request_done": True}]
    assert bridge.settings.value(key) == "old.xml"


def test_progress_request_id_is_echoed_on_every_save_response(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    repo = project(tmp_path)
    bridge = DesktopBridge()
    monkeypatch.setattr(bridge, '_progress_dir', lambda: tmp_path / 'data')
    messages = []
    bridge.event.connect(lambda raw: messages.append(json.loads(raw)))
    bridge.previewProgress(str(repo), json.dumps(['README.md']), 'session:extract')
    settle(bridge)
    assert messages[-1]['request_id'] == 'session:extract'
    assert messages[-1]['request_done']
    bridge.saveProgress(str(repo), json.dumps(messages[-1]), 'session:save')
    settle(bridge)
    assert [message['request_id'] for message in messages[-3:]] == ['session:save'] * 3
    assert [message['request_done'] for message in messages[-3:]] == [False, False, True]


def test_cancel_and_failed_progress_requests_keep_their_request_id(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    repo = project(tmp_path)
    bridge = DesktopBridge()
    messages = []
    bridge.event.connect(lambda raw: messages.append(json.loads(raw)))
    monkeypatch.setattr('drift_gate.desktop.web_app.QFileDialog.getOpenFileName', lambda *args: ('', ''))
    bridge.loadTestResults(str(repo), 'session:cancel')
    assert messages[-1]['type'] == 'progressTestsCancelled'
    assert messages[-1]['request_id'] == 'session:cancel'
    bridge.listProjectDocs(str(tmp_path / 'missing'), 'session:error')
    settle(bridge)
    assert messages[-1]['type'] == 'progressError'
    assert messages[-1]['request_id'] == 'session:error'
    assert messages[-1]['request_done']


def test_draft_recovers_on_a_new_bridge_and_clears_only_after_successful_save(tmp_path, monkeypatch):
    from drift_gate.desktop.progress_drafts import recovery_copy
    from drift_gate.desktop.progress_service import extract_requirements, save_baseline
    QApplication.instance() or QApplication([])
    repo = project(tmp_path)
    directory = tmp_path / 'recovery-data'
    baseline = save_baseline(repo, directory, extract_requirements(repo, ['README.md']))
    draft = json.loads(json.dumps(baseline))
    draft['requirements'][0].update(title='재시작 전 편집', criterion='')
    first = DesktopBridge()
    monkeypatch.setattr(first, '_progress_dir', lambda: directory)
    first.cacheProgressDraft(str(repo), json.dumps(draft), 'first:draft')
    settle(first)
    second = DesktopBridge()
    monkeypatch.setattr(second, '_progress_dir', lambda: directory)
    messages = []
    second.event.connect(lambda raw: messages.append(json.loads(raw)))
    second.listProjectDocs(str(repo), 'second:docs')
    settle(second)
    docs = of_type(messages, 'progressDocs')
    assert docs['baseline']['requirements'][0]['title'] != '재시작 전 편집'
    assert docs['recovery']['requirements'][0]['title'] == '재시작 전 편집'
    second.saveProgress(str(repo), json.dumps(draft), 'second:bad-save')
    settle(second)
    assert recovery_copy(repo, directory, baseline)['recovery']
    draft['requirements'][0]['criterion'] = '다시 입력한 완료 조건'
    second.saveProgress(str(repo), json.dumps(draft), 'second:save')
    settle(second)
    assert of_type(messages, 'progressSaved')['baseline']['version'] == 2
    assert recovery_copy(repo, directory, baseline) == {}


def test_draft_write_error_and_explicit_discard_have_correlated_responses(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    repo = project(tmp_path)
    bridge = DesktopBridge()
    monkeypatch.setattr(bridge, '_progress_dir', lambda: tmp_path / 'draft-data')
    messages = []
    bridge.event.connect(lambda raw: messages.append(json.loads(raw)))
    bridge.cacheProgressDraft(str(repo), '{}', 'draft:bad')
    settle(bridge)
    assert messages[-1]['type'] == 'progressDraftError'
    assert messages[-1]['request_id'] == 'draft:bad' and messages[-1]['request_done']
    bridge.discardProgressDraft(str(repo), 'draft:delete')
    settle(bridge)
    assert messages[-1]['type'] == 'progressDraftDiscarded'
    assert messages[-1]['request_id'] == 'draft:delete'


@pytest.mark.parametrize('discard', [False, True])
def test_native_close_protects_unsaved_progress(monkeypatch, discard):
    from types import SimpleNamespace
    from PySide6.QtWidgets import QMessageBox
    from drift_gate.desktop.web_app import WebDesktopWindow
    answer = QMessageBox.StandardButton.Yes if discard else QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: answer)
    window = SimpleNamespace(bridge=SimpleNamespace(progress_dirty=True, scan_thread=None, review_worker=None,
        progress_pool=SimpleNamespace(waitForDone=lambda timeout: True)))
    results = []
    event = SimpleNamespace(ignore=lambda: results.append('ignored'), accept=lambda: results.append('accepted'))
    WebDesktopWindow.closeEvent(window, event)
    assert results == ['accepted' if discard else 'ignored']
