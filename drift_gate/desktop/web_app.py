"""Local React surface hosted by Qt; only trusted bundled UI gets a bridge."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QStandardPaths, QThread, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox

from drift_gate.desktop.app import ScanWorker
from drift_gate.desktop.review_dialog import ReviewWorker, review_html
from drift_gate.desktop.subscription_review import build_review_prompt, find_cli
from drift_gate.reporters.html import HtmlReporter
from drift_gate.desktop.progress_service import (
    evidence_candidates, extract_requirements, inspect_progress,
    list_documents, load_baseline, save_baseline,
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

    def emit(self, kind, **data):
        self.event.emit(json.dumps({'type': kind, **data}, ensure_ascii=False))

    def _progress_dir(self):
        return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)) / 'progress'

    @Slot(str)
    def listProjectDocs(self, path):
        try:
            result = list_documents(path)
            result['baseline'] = load_baseline(path, self._progress_dir())
            self.emit('progressDocs', requested_path=path, **result)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            self.emit('progressError', requested_path=path, message=str(exc))

    @Slot(str, str)
    def previewProgress(self, path, selected_json):
        try:
            self.emit('progressPreview', requested_path=path,
                      **extract_requirements(path, json.loads(selected_json)))
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            self.emit('progressError', requested_path=path, message=str(exc))

    @Slot(str, str)
    def saveProgress(self, path, payload_json):
        try:
            baseline = save_baseline(path, self._progress_dir(), json.loads(payload_json))
            self.emit('progressSaved', requested_path=path, baseline=baseline)
            self.emit('progressReport', requested_path=path,
                      report=inspect_progress(path, self._progress_dir()))
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            self.emit('progressError', requested_path=path, message=str(exc))

    @Slot(str)
    def inspectProgress(self, path):
        try:
            self.emit('progressReport', requested_path=path,
                      report=inspect_progress(path, self._progress_dir()))
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            self.emit('progressError', requested_path=path, message=str(exc))

    @Slot(str, str)
    def suggestProgressEvidence(self, path, item_json):
        try:
            item = json.loads(item_json)
            self.emit('progressEvidence', requested_path=path, id=item['id'],
                      candidates=evidence_candidates(path, item))
        except (ValueError, OSError, json.JSONDecodeError, KeyError) as exc:
            self.emit('progressError', requested_path=path, message=str(exc))

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
    def exportReport(self, kind):
        if not self.scan or kind not in {'html', 'json'}:
            return
        filename, _ = QFileDialog.getSaveFileName(self.parent(), '결과 저장',
            str(self.scan.repository / f'drift-gate-report.{kind}'), f'{kind.upper()} (*.{kind})')
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
