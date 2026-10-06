"""Local React surface hosted by Qt; only trusted bundled UI gets a bridge."""
import hashlib
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSettings, QStandardPaths, QThread, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox

from drift_gate.desktop.app import ScanWorker
from drift_gate.desktop.resources import WEB_ROOT
from drift_gate.desktop.policy_setup import create_policy, preview_policy
from drift_gate.desktop.service import resolve_document
from drift_gate.desktop.review_dialog import ReviewWorker, review_html
from drift_gate.desktop.subscription_review import build_review_prompt, find_cli
from drift_gate.adapters.report_naming import default_report_path, detect_project
from drift_gate.desktop.progress_report import render_markdown
from drift_gate.desktop.progress_context import inspection_context
from drift_gate.desktop.progress_limits import MAX_DRAFT_BYTES
from drift_gate.desktop.progress_drafts import (
    DraftSession, cache_draft, recovery_copy, discard_draft, discard_recovery, discard_recoveries, export_draft, import_draft,
)
from drift_gate.reporters.html import HtmlReporter
from drift_gate.desktop.progress_service import (
    BaselineConflict, BaselineError, check_references, evidence_candidates, extract_requirements, inspect_progress,
    link_test_results, list_documents, load_baseline, progress_history_view, capture_progress_history, record_snapshot, repository_root,
    save_baseline, scan_impact,
)


def scan_payload(scan):
    return {'repository': str(scan.repository), 'base': scan.base,
            'changed_file_count': scan.changed_file_count, 'result': scan.result.to_dict(),
            'policy': scan.policy_source,
            'files': [{'path': f.path, 'patch': f.patch, 'status': f.status} for f in scan.files],
            'at': datetime.now(timezone.utc).isoformat()}


class LocalOnly(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info):
        url = info.requestUrl()
        if url.scheme() == 'file':
            if not Path(url.toLocalFile()).resolve().is_relative_to(WEB_ROOT.resolve()):
                info.block(True)
        elif url.scheme() not in {'qrc', 'data', 'blob', 'about'}:
            info.block(True)


class LocalPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, _nav_type, _is_main_frame):
        return url.scheme() == 'file' and Path(url.toLocalFile()).resolve().is_relative_to(WEB_ROOT.resolve())


class _ProgressSignals(QObject):
    raw = Signal(str)


class ProgressTask(QRunnable):
    """Runs one project-progress request off the UI thread and emits ready-made events."""

    def __init__(self, signals, path, work, error_type='progressError', request_id=''):
        super().__init__()
        self.signals, self.path, self.work = signals, path, work
        self.error_type, self.request_id = error_type, request_id

    def run(self):
        try:
            events = [{'type': kind, 'requested_path': self.path, **data} for kind, data in self.work()]
            if not events and self.request_id:
                raise ValueError('작업 결과를 받지 못했습니다. 다시 시도해 주세요.')
            encoded = self._encode(events)
        except BaselineConflict as exc:
            encoded = self._encode([{'type': 'progressError', 'message': str(exc), 'current_baseline': exc.baseline}])
        except BaselineError as exc:
            encoded = self._encode([{'type': self.error_type, 'message': str(exc), 'errors': exc.errors}])
        except (ValueError, OSError, KeyError) as exc:
            encoded = self._encode([{'type': self.error_type, 'message': str(exc)}])
        except Exception:
            logging.getLogger(__name__).exception('Progress request failed: %s', self.request_id)
            encoded = self._encode([{'type': self.error_type, 'message': '작업을 완료하지 못했습니다. 다시 시도해 주세요.'}])
        for raw in encoded:
            self.signals.raw.emit(raw)

    def _encode(self, events):
        # Encode the whole batch before emitting, including the terminal outcome.
        return [json.dumps({**event, 'requested_path': self.path, 'request_id': self.request_id,
                           'request_done': index == len(events) - 1}, ensure_ascii=False, allow_nan=False)
                for index, event in enumerate(events)]


class DesktopBridge(QObject):
    event = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings('Drift Gate', 'Desktop')
        self.scan = None
        self.review = None
        self.scan_thread = None
        self.scan_worker = None
        self.review_worker = None
        self.progress_dirty = False
        self._draft_owner = uuid.uuid4().hex
        self._draft_sessions = {}
        self._draft_exports = {}
        self.progress_recovery_ready = False
        self.history = []  # Session-only: no hidden persistence of source diffs.
        # One thread keeps progress results in request order (save -> report).
        self.progress_pool = QThreadPool(self)
        self.progress_pool.setMaxThreadCount(1)
        self._progress_signals = _ProgressSignals(self)
        self._progress_signals.raw.connect(self.event)

    def _run_progress(self, path, work, error_type='progressError', request_id=''):
        self.progress_pool.start(ProgressTask(self._progress_signals, path, work, error_type, request_id))

    def emit(self, kind, **data):
        self.event.emit(json.dumps({'type': kind, **data}, ensure_ascii=False))

    def _results_key(self, path):
        digest = hashlib.sha256(str(Path(path).expanduser()).encode('utf-8')).hexdigest()[:16]
        return f'testResults/{digest}'

    def _progress_dir(self):
        return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)) / 'progress'

    def closeDraftSessions(self):
        for session in self._draft_sessions.values():
            try:
                if not session.close():
                    logging.getLogger(__name__).warning('Deferred draft lease cleanup: %s', session.lease)
            except OSError:
                logging.getLogger(__name__).exception('Could not clean up draft lease: %s', session.lease)
        self._draft_sessions.clear()

    def _progress_documents(self, path, directory, recovery_key=''):
        result = list_documents(path)
        result['baseline'] = load_baseline(path, directory)
        result.update(recovery_copy(repository_root(path), directory, result['baseline'], recovery_key))
        return result

    @Slot(str)
    @Slot(str, str)
    @Slot(str, str, str)
    def listProjectDocs(self, path, request_id="", recovery_key=""):
        directory = self._progress_dir()

        def work():
            return [('progressDocs', self._progress_documents(path, directory, recovery_key))]
        self._run_progress(path, work, request_id=request_id)

    @Slot(str, str)
    @Slot(str, str, str)
    def previewProgress(self, path, selected_json, request_id=""):
        self._run_progress(path, lambda: [
            ('progressPreview', extract_requirements(path, json.loads(selected_json)))], request_id=request_id)

    @Slot(str, str)
    @Slot(str, str, str)
    def saveProgress(self, path, payload_json, request_id=""):
        directory = self._progress_dir()

        def work():
            payload = json.loads(payload_json)
            baseline = save_baseline(path, directory, payload)
            warning = ''
            try:
                discard_draft(repository_root(path), directory, self._draft_owner)
                key, revision = payload.get('recovery_key'), payload.get('recovery_revision')
                if isinstance(key, str) and key and isinstance(revision, str) and revision:
                    discard_recovery(repository_root(path), directory, key, revision)
            except Exception:
                logging.getLogger(__name__).exception("Committed save draft cleanup failed")
                warning = '기준과 근거는 저장했습니다. 이전 초안 파일을 지우지 못했습니다. 다음 실행에서 오래된 초안이 보이면 삭제해 주세요.'
            events = [('progressSaved', {'baseline': baseline, 'warning': warning})]
            try:
                report = inspect_progress(path, directory, baseline=baseline)
                context = inspection_context(baseline)
                events.append(('progressReport', {'report': report, **context}))
                try:
                    history = record_snapshot(path, directory, report)
                except Exception:
                    logging.getLogger(__name__).exception('Committed save history recording failed')
                    history = {'snapshots': [], 'since_save': None,
                               'warning': '진행 이력 기록에 실패했습니다. 기존 이력 파일은 보존했습니다.'}
                    events[0][1]['warning'] += ' 기준과 근거는 저장했지만 이력 기록에 실패했습니다.'
                events.append(('progressHistory', {**history, **context}))
            except Exception:
                logging.getLogger(__name__).exception("Committed save inspection failed")
                events[0][1]['warning'] += ' 기준과 근거는 저장했지만 현황 재검사 또는 이력 기록에 실패했습니다. 다시 검사해 주세요.'
            return events
        self._run_progress(path, work, request_id=request_id)

    @Slot(str, str, str)
    def cacheProgressDraft(self, path, payload_json, request_id):
        directory = self._progress_dir()
        def work():
            if len(payload_json.encode('utf-8')) > MAX_DRAFT_BYTES:
                raise ValueError('편집 초안이 보관 상한을 넘었습니다.')
            root = repository_root(path)
            payload = json.loads(payload_json)
            exported = self._draft_exports.get(root)
            if exported is not None and exported['draft'] != payload:
                self._draft_exports.pop(root, None)
            key = (root, directory)
            if key not in self._draft_sessions:
                self._draft_sessions[key] = DraftSession(root, directory, self._draft_owner)
            cache_draft(root, directory, payload, self._draft_owner, self._draft_sessions[key])
            return [('progressDraftCached', {})]
        self._run_progress(path, work, error_type='progressDraftError', request_id=request_id)

    @Slot(str, str)
    @Slot(str, str, str)
    @Slot(str, str, str, str)
    def discardProgressDraft(self, path, request_id, recovery_key="", revision=""):
        directory = self._progress_dir()
        def work():
            if recovery_key:
                discard_recovery(repository_root(path), directory, recovery_key, revision)
            else:
                discard_draft(repository_root(path), directory, self._draft_owner)
            return [('progressDraftDiscarded', {}), ('progressDocs', self._progress_documents(path, directory))]
        self._run_progress(path, work, request_id=request_id)

    @Slot(str, str, str)
    def discardProgressDrafts(self, path, selections_json, request_id):
        directory = self._progress_dir()
        def work():
            discard_recoveries(repository_root(path), directory, json.loads(selections_json))
            return [('progressDraftDiscarded', {}), ('progressDocs', self._progress_documents(path, directory))]
        self._run_progress(path, work, request_id=request_id)

    @Slot(str, str, str)
    def exportProgressDraft(self, path, payload_json, request_id):
        filename, _ = QFileDialog.getSaveFileName(self.parent(), '편집 초안 내보내기',
                                                 str(Path(path) / 'progress-draft.json'), 'JSON (*.json)')
        if not filename:
            self.emit('progressDraftExportCancelled', requested_path=path, request_id=request_id, request_done=True)
            return
        def work():
            root, payload, target = repository_root(path), json.loads(payload_json), Path(filename)
            export_draft(root, payload, target)
            self._draft_exports[root] = {'draft': payload, 'file': target, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
            return [('progressDraftExported', {'file': filename})]
        self._run_progress(path, work, request_id=request_id)

    @Slot(str, str)
    def importProgressDraft(self, path, request_id):
        filename, _ = QFileDialog.getOpenFileName(self.parent(), '편집 초안 불러오기', str(Path(path)), 'JSON (*.json)')
        if not filename:
            self.emit('progressDraftImportCancelled', requested_path=path, request_id=request_id, request_done=True)
            return
        directory = self._progress_dir()
        def work():
            key = import_draft(repository_root(path), directory, Path(filename))
            result = self._progress_documents(path, directory, key)
            result['recovery_warning'] = '파일의 초안을 별도 사본으로 보관했습니다. 초안 복구를 눌러 내용을 검토해 주세요. 확정 기준은 바꾸지 않았습니다. ' + result.get('recovery_warning', '')
            return [('progressDocs', result)]
        self._run_progress(path, work, request_id=request_id)

    @Slot(str, str)
    def useLatestProgress(self, path, request_id):
        directory = self._progress_dir()
        def work():
            root = repository_root(path)
            exported = self._draft_exports.get(root)
            if exported is None or hashlib.sha256(exported['file'].read_bytes()).hexdigest() != exported['sha256']:
                raise ValueError('내보낸 초안 파일을 확인하지 못했습니다. 초안을 다시 내보낸 뒤 전환해 주세요.')
            baseline = load_baseline(path, directory)
            if baseline is None:
                raise ValueError('최신 기준을 찾지 못했습니다. 현재 편집은 유지했습니다.')
            warning = ''
            try:
                discard_draft(root, directory, self._draft_owner)
            except OSError:
                warning = '최신 기준을 불러왔지만 이전 초안 사본을 지우지 못했습니다.'
            self._draft_exports.pop(root, None)
            return [('progressLatestUsed', {'baseline': baseline, 'warning': warning})]
        self._run_progress(path, work, request_id=request_id)

    @Slot(str)
    @Slot(str, str)
    def inspectProgress(self, path, request_id=""):
        directory = self._progress_dir()
        remembered = str(self.settings.value(self._results_key(path), '') or '')

        def work():
            baseline = load_baseline(path, directory)
            if baseline is None:
                raise ValueError('기준 문서를 먼저 저장해 주세요.')
            anchor = capture_progress_history(path, directory)
            report = inspect_progress(path, directory, baseline=baseline)
            context = inspection_context(baseline)
            events = [('progressReport', {'report': report, **context}),
                      ('progressHistory', {**progress_history_view(path, directory, report, anchor=anchor), **context})]
            if remembered and Path(remembered).is_file():
                try:  # a file that vanished or went bad is skipped quietly; picking another replaces it
                    events.append(('progressTests', {**link_test_results(path, directory, remembered, baseline=baseline),
                                                     'remembered': True, **context}))
                except (ValueError, OSError):
                    pass
            return events
        self._run_progress(path, work, request_id=request_id)

    @Slot(str)
    @Slot(str, str)
    def checkProgressLinks(self, path, request_id=""):
        directory = self._progress_dir()
        def work():
            baseline = load_baseline(path, directory)
            if baseline is None:
                raise ValueError('기준 문서를 먼저 저장해 주세요.')
            return [('progressLinks', {**check_references(path, directory, baseline=baseline), **inspection_context(baseline)})]
        self._run_progress(path, work, request_id=request_id)

    @Slot(str)
    @Slot(str, str)
    def loadTestResults(self, path, request_id=""):
        try:
            root = repository_root(path)
        except (ValueError, OSError) as exc:
            self.emit('progressError', requested_path=path, request_id=request_id, request_done=True, message=str(exc))
            return
        filename, _ = QFileDialog.getOpenFileName(
            self.parent(), '테스트 결과 파일 선택', str(root), '테스트 결과 (*.xml *.json)')
        if not filename:
            self.emit("progressTestsCancelled", requested_path=path, request_id=request_id, request_done=True)
            return
        directory = self._progress_dir()
        self.settings.setValue(self._results_key(path), filename)  # re-read next time this project opens
        def work():
            baseline = load_baseline(path, directory)
            if baseline is None:
                raise ValueError('기준 문서를 먼저 저장해 주세요.')
            return [('progressTests', {**link_test_results(path, directory, filename, baseline=baseline), **inspection_context(baseline)})]
        self._run_progress(path, work, request_id=request_id)

    @Slot(bool)
    def setProgressDirty(self, dirty):
        self.progress_dirty = dirty

    @Slot(bool)
    def setProgressRecoveryReady(self, ready):
        self.progress_recovery_ready = ready

    @Slot(str)
    def forgetTestResults(self, path):
        self.settings.remove(self._results_key(path))

    @Slot(str, str)
    @Slot(str, str, str)
    def exportProgress(self, path, kind, request_id=""):
        if kind not in {'md', 'json'}:
            return
        directory = self._progress_dir()
        try:
            root = repository_root(path)
            policy = root / '.drift-gate.yml'
            policy_source = policy.read_text(encoding='utf-8') if policy.is_file() else ''
            suggested = default_report_path(root, 'progress', kind, policy_source)
        except (ValueError, OSError) as exc:
            self.emit('progressError', requested_path=path, request_id=request_id, request_done=True, message=str(exc))
            return
        filename, _ = QFileDialog.getSaveFileName(
            self.parent(), '현황 저장', str(suggested), f'{"Markdown" if kind == "md" else "JSON"} (*.{kind})')
        if not filename:
            return

        def work():
            anchor = capture_progress_history(root, directory)
            report = inspect_progress(root, directory)
            history = progress_history_view(root, directory, report, anchor=anchor)
            project = detect_project(root)
            identity = {'name': project.name, 'branch': project.branch,
                        'version': project.version, 'commit': project.commit}
            if kind == 'json':
                content = json.dumps({'schema': 1, 'project': identity, 'report': report, 'history': history},
                                     ensure_ascii=False, indent=2)
            else:
                content = render_markdown(report, identity, history)
            Path(filename).write_text(content, encoding='utf-8')
            return [('progressExported', {'file': filename})]
        self._run_progress(path, work, request_id=request_id)

    @Slot(str, str)
    @Slot(str, str, str)
    def suggestProgressEvidence(self, path, item_json, request_id=""):
        def work():
            item = json.loads(item_json)
            return [('progressEvidence', {'id': item['id'], 'candidates': evidence_candidates(path, item)})]
        self._run_progress(path, work, request_id=request_id)

    def _emit_scan_impact(self, scan, scan_at):
        """Tell the review screen which saved progress evidence this scan's changes touch."""
        directory = self._progress_dir()
        changes = [{'path': f.path, 'previous_path': f.previous_path, 'status': f.status}
                   for f in scan.files]
        repository = str(scan.repository)

        def work():
            try:
                impact = scan_impact(repository, directory, changes)
            except (ValueError, OSError, json.JSONDecodeError):
                return []  # a review scan must not raise progress errors
            if impact is None or not (impact['items'] or impact['documents']):
                return []
            return [('scanImpact', {**impact, 'scan_at': scan_at})]
        self._run_progress(repository, work)

    @Slot()
    def initialize(self):
        installed = {}
        for provider in ('codex', 'claude'):
            try:
                installed[provider] = find_cli(provider)
            except Exception:
                installed[provider] = ''
        self.emit('ready', repository=str(self.settings.value('repository', '')),
                  base=str(self.settings.value('base', 'HEAD')), installed=installed)

    @Slot()
    def chooseRepository(self):
        folder = QFileDialog.getExistingDirectory(self.parent(), 'Git 저장소 선택')
        if folder:
            self.emit('repository', path=folder)

    @Slot(str, str)
    def startScan(self, path, base):
        if self.scan_thread or self.review_worker:
            self.emit('error', message='현재 작업이 끝난 뒤 다시 실행해 주세요.')
            return
        self.scan = None
        self.review = None
        self.emit('scanning')
        self.scan_thread = QThread(self)
        self.scan_worker = ScanWorker(path, base)
        self.scan_worker.moveToThread(self.scan_thread)
        self.scan_thread.started.connect(self.scan_worker.run)
        self.scan_worker.finished.connect(self._scan_done)
        self.scan_worker.policy_missing.connect(self._policy_missing)
        self.scan_worker.failed.connect(self._scan_failed)
        self.scan_worker.finished.connect(self.scan_worker.deleteLater)
        self.scan_worker.failed.connect(self.scan_worker.deleteLater)
        self.scan_worker.finished.connect(self.scan_thread.quit)
        self.scan_worker.failed.connect(self.scan_thread.quit)
        self.scan_thread.finished.connect(self._scan_cleanup)
        self.scan_thread.start()

    @Slot(object)
    def _scan_done(self, scan):
        self.scan = scan
        self.settings.setValue('repository', str(scan.repository))
        self.settings.setValue('base', scan.base)
        payload = scan_payload(scan)
        self.history.insert(0, payload)
        self.history = self.history[:20]
        self.emit('scanned', scan=payload)
        self._emit_scan_impact(scan, payload['at'])

    @Slot(str)
    def _scan_failed(self, message):
        self.emit('error', message=message)

    @Slot(str)
    def _policy_missing(self, repository):
        self.emit('policyMissing', repository=repository)

    @Slot(str, str)
    def previewPolicy(self, path, preset):
        self._run_progress(path, lambda: [('policyPreview', preview_policy(path, preset))], 'error')

    @Slot(str, str)
    def createPolicy(self, path, preset):
        self._run_progress(path, lambda: [('policyCreated', create_policy(path, preset))], 'error')

    @Slot()
    def _scan_cleanup(self):
        self.scan_thread.deleteLater()
        self.scan_worker = self.scan_thread = None

    @Slot()
    def previewReview(self):
        if self.scan and not self.scan_thread:
            self.emit('preview', prompt=build_review_prompt(self.scan))

    @Slot(str, str)
    def startReview(self, provider, executable):
        if not self.scan or self.scan_thread or self.review_worker:
            return
        self.review = None
        self.emit('reviewing')
        self.review_worker = ReviewWorker(build_review_prompt(self.scan), provider, executable, self)
        self.review_worker.succeeded.connect(self._review_done)
        self.review_worker.failed.connect(self._review_failed)
        self.review_worker.finished.connect(self._review_cleanup)
        self.review_worker.start()

    @Slot(object)
    def _review_done(self, review):
        self.review = review
        self.emit('reviewed', review=review.to_dict())

    @Slot(str)
    def _review_failed(self, message):
        self.emit('reviewError', message=message)

    @Slot()
    def _review_cleanup(self):
        self.review_worker.deleteLater()
        self.review_worker = None

    @Slot()
    def cancelReview(self):
        if self.review_worker:
            self.review_worker.cancel.set()

    @Slot(str)
    def openDocument(self, relative):
        if not self.scan:
            return
        try:
            target = resolve_document(self.scan.repository, relative)
        except ValueError as exc:
            self.emit('error', message=str(exc))
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))):
            self.emit('error', message=f'기본 편집기로 열지 못했습니다: {relative}')

    @Slot(str)
    def exportReport(self, kind):
        if not self.scan or kind not in {'html', 'json'}:
            return
        filename, _ = QFileDialog.getSaveFileName(self.parent(), '결과 저장',
            str(default_report_path(self.scan.repository, 'drift-report', kind, self.scan.policy_source)),
            f'{kind.upper()} (*.{kind})')
        if not filename:
            return
        try:
            if kind == 'json':
                payload = self.scan.result.to_dict()
                if self.review:
                    payload['llm_review'] = self.review.to_dict()
                content = json.dumps(payload, ensure_ascii=False, indent=2)
            else:
                content = HtmlReporter().render(self.scan.result, policy_source=self.scan.policy_source)
                if self.review:
                    content = content.replace('</main>', review_html(self.review) + '</main>')
            Path(filename).write_text(content, encoding='utf-8')
            self.emit('saved', path=filename)
        except OSError as exc:
            self.emit('error', message=f'저장하지 못했습니다: {exc}')


class WebDesktopWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Cross Agent · Drift Gate')
        self.resize(1440, 920)
        self.setMinimumSize(960, 680)
        self.view = QWebEngineView(self)
        self.page = LocalPage(self.view)
        self.interceptor = LocalOnly(self)
        self.page.profile().setUrlRequestInterceptor(self.interceptor)
        self.view.setPage(self.page)
        self.channel = QWebChannel(self.page)
        self.bridge = DesktopBridge(self)
        self.channel.registerObject('desktop', self.bridge)
        self.page.setWebChannel(self.channel)
        self.setCentralWidget(self.view)
        self.view.load(QUrl.fromLocalFile(str((WEB_ROOT / 'index.html').resolve())))

    def closeEvent(self, event):
        if self.bridge.progress_dirty:
            recovery = ('보관 완료된 초안은 다음 실행에서 복구할 수 있습니다.'
                        if self.bridge.progress_recovery_ready else
                        '최신 초안의 보관 완료를 확인하지 못했습니다. 앱을 닫으면 최근 편집을 잃을 수 있습니다. 창을 닫지 말고 보관 완료를 기다리거나 기준과 근거를 저장해 주세요.')
            answer = QMessageBox.question(
                self, '저장 전 변경 사항',
                '현황에 확정하지 않은 변경이 있습니다. 앱을 닫을까요? ' + recovery,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        if self.bridge.scan_thread:
            QMessageBox.information(self, '검사 진행 중', '현재 검사가 끝난 뒤 앱을 닫아 주세요.')
            event.ignore()
            return
        if not self.bridge.progress_pool.waitForDone(3000):
            event.ignore()
            return
        if self.bridge.review_worker:
            self.bridge.cancelReview()
            if not self.bridge.review_worker.wait(2000):
                event.ignore()
                return
        self.bridge.closeDraftSessions()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('Cross Agent')
    app.setOrganizationName('Drift Gate')
    package_check = len(sys.argv) == 4 and sys.argv[1] == '--verify-package'
    if package_check:
        from drift_gate.desktop.package_check import prepare_check
        prepare_check(Path(sys.argv[3]).parent)
    if not (WEB_ROOT / 'index.html').is_file():
        if package_check:
            print(f'Missing bundled UI: {WEB_ROOT / "index.html"}', file=sys.stderr)
            sys.exit(1)
        QMessageBox.critical(None, '화면 빌드 필요', 'desktop-ui에서 npm ci 및 npm run build를 실행해 주세요.')
        return
    window = WebDesktopWindow()
    if package_check:
        from drift_gate.desktop.package_check import PackageCheck
        _package_check = PackageCheck(app, window, sys.argv[2], sys.argv[3])
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
