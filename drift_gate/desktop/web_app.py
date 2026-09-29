"""Local React surface hosted by Qt; only trusted bundled UI gets a bridge."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSettings, QStandardPaths, QThread, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox

from drift_gate.desktop.app import ScanWorker
from drift_gate.desktop.service import resolve_document
from drift_gate.desktop.review_dialog import ReviewWorker, review_html
from drift_gate.desktop.subscription_review import build_review_prompt, find_cli
from drift_gate.adapters.report_naming import default_report_path, detect_project
from drift_gate.desktop.progress_report import render_markdown
from drift_gate.reporters.html import HtmlReporter
from drift_gate.desktop.progress_service import (
    BaselineError, check_references, evidence_candidates, extract_requirements, inspect_progress,
    list_documents, load_baseline, repository_root, save_baseline, scan_impact,
)

WEB_ROOT = Path(__file__).parent / 'web'


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
    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        return url.scheme() == 'file' and Path(url.toLocalFile()).resolve().is_relative_to(WEB_ROOT.resolve())


class _ProgressSignals(QObject):
    raw = Signal(str)


class ProgressTask(QRunnable):
    """Runs one project-progress request off the UI thread and emits ready-made events."""

    def __init__(self, signals, path, work):
        super().__init__()
        self.signals, self.path, self.work = signals, path, work

    def run(self):
        try:
            events = [{'type': kind, 'requested_path': self.path, **data} for kind, data in self.work()]
        except BaselineError as exc:
            events = [{'type': 'progressError', 'requested_path': self.path,
                       'message': str(exc), 'errors': exc.errors}]
        except (ValueError, OSError, json.JSONDecodeError, KeyError) as exc:
            events = [{'type': 'progressError', 'requested_path': self.path, 'message': str(exc)}]
        for event in events:
            self.signals.raw.emit(json.dumps(event, ensure_ascii=False))


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
        self.history = []  # Session-only: no hidden persistence of source diffs.
        # One thread keeps progress results in request order (save -> report).
        self.progress_pool = QThreadPool(self)
        self.progress_pool.setMaxThreadCount(1)
        self._progress_signals = _ProgressSignals(self)
        self._progress_signals.raw.connect(self.event)

    def _run_progress(self, path, work):
        self.progress_pool.start(ProgressTask(self._progress_signals, path, work))

    def emit(self, kind, **data):
        self.event.emit(json.dumps({'type': kind, **data}, ensure_ascii=False))

    def _progress_dir(self):
        return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)) / 'progress'

    @Slot(str)
    def listProjectDocs(self, path):
        directory = self._progress_dir()

        def work():
            result = list_documents(path)
            result['baseline'] = load_baseline(path, directory)
            return [('progressDocs', result)]
        self._run_progress(path, work)

    @Slot(str, str)
    def previewProgress(self, path, selected_json):
        self._run_progress(path, lambda: [
            ('progressPreview', extract_requirements(path, json.loads(selected_json)))])

    @Slot(str, str)
    def saveProgress(self, path, payload_json):
        directory = self._progress_dir()

        def work():
            baseline = save_baseline(path, directory, json.loads(payload_json))
            return [('progressSaved', {'baseline': baseline}),
                    ('progressReport', {'report': inspect_progress(path, directory)})]
        self._run_progress(path, work)

    @Slot(str)
    def inspectProgress(self, path):
        directory = self._progress_dir()
        self._run_progress(path, lambda: [
            ('progressReport', {'report': inspect_progress(path, directory)})])

    @Slot(str)
    def checkProgressLinks(self, path):
        directory = self._progress_dir()
        self._run_progress(path, lambda: [('progressLinks', check_references(path, directory))])

    @Slot(str, str)
    def exportProgress(self, path, kind):
        if kind not in {'md', 'json'}:
            return
        directory = self._progress_dir()
        try:
            root = repository_root(path)
            policy = root / '.drift-gate.yml'
            policy_source = policy.read_text(encoding='utf-8') if policy.is_file() else ''
            suggested = default_report_path(root, 'progress', kind, policy_source)
        except (ValueError, OSError) as exc:
            self.emit('progressError', requested_path=path, message=str(exc))
            return
        filename, _ = QFileDialog.getSaveFileName(
            self.parent(), '현황 저장', str(suggested), f'{"Markdown" if kind == "md" else "JSON"} (*.{kind})')
        if not filename:
            return

        def work():
            report = inspect_progress(root, directory)
            project = detect_project(root)
            identity = {'name': project.name, 'branch': project.branch,
                        'version': project.version, 'commit': project.commit}
            if kind == 'json':
                content = json.dumps({'schema': 1, 'project': identity, 'report': report},
                                     ensure_ascii=False, indent=2)
            else:
                content = render_markdown(report, identity)
            Path(filename).write_text(content, encoding='utf-8')
            return [('progressExported', {'file': filename})]
        self._run_progress(path, work)

    @Slot(str, str)
    def suggestProgressEvidence(self, path, item_json):
        def work():
            item = json.loads(item_json)
            return [('progressEvidence', {'id': item['id'], 'candidates': evidence_candidates(path, item)})]
        self._run_progress(path, work)

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
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('Cross Agent')
    app.setOrganizationName('Drift Gate')
    if not (WEB_ROOT / 'index.html').is_file():
        QMessageBox.critical(None, '화면 빌드 필요', 'desktop-ui에서 npm ci 및 npm run build를 실행해 주세요.')
        return
    window = WebDesktopWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
