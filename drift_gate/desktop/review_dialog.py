"""Explicit data preview and subscription CLI review UI."""
import html
import threading

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTabWidget,
    QTextBrowser, QVBoxLayout,
)

from drift_gate.desktop.subscription_review import (
    PROVIDERS, VERDICTS, build_review_prompt, review_with_subscription,
)


def review_html(review) -> str:
    esc = html.escape
    sections = [f"<h2>LLM 판정 · {esc(VERDICTS[review.verdict])}</h2>",
                f"<p>{esc(PROVIDERS[review.provider])}</p>",
                f"<p>{esc(review.summary)}</p>",
                "<p>LLM 검토 의견입니다. 규칙에 따른 통과·실패는 바꾸지 않습니다.</p>"]
    for finding in review.findings:
        sections.append(f"<h3>{esc(finding['rule_id'])}</h3><p>{esc(finding['reason'])}</p>"
                        f"<p><b>수정 제안</b> · {esc(finding['suggestion'])}</p>")
    if review.limitations:
        sections.append("<h3>확인 범위와 한계</h3><ul>" + "".join(
            f"<li>{esc(item)}</li>" for item in review.limitations) + "</ul>")
    return "".join(sections)


class ReviewWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, prompt, provider, executable, parent=None):
        super().__init__(parent)
        self.prompt, self.provider, self.executable = prompt, provider, executable
        self.cancel = threading.Event()

    def run(self):
        try:
            self.succeeded.emit(review_with_subscription(
                self.prompt, self.provider, executable=self.executable, cancel=self.cancel))
        except Exception as exc:
            self.failed.emit(str(exc))


class ReviewDialog(QDialog):
    def __init__(self, scan, review=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LLM 추가 판정")
        self.resize(840, 690)
        self.review = review
        self.worker = None
        self.prompt = build_review_prompt(scan)
        layout = QVBoxLayout(self)
        title = QLabel(f"규칙 판정: {scan.result.result.upper()}  ·  기준: {scan.base}")
        layout.addWidget(title)
        note = QLabel("공식 CLI에 로그인한 구독 계정으로 검토합니다. 요청하면 아래 코드·문서 자료가 선택한 서비스로 전송되고 구독 사용량을 소비합니다.")
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        self.provider = QComboBox()
        for key, name in PROVIDERS.items():
            self.provider.addItem(name, key)
        if review is not None:
            self.provider.setCurrentIndex(self.provider.findData(review.provider))
        row.addWidget(self.provider, 1)
        help_button = QPushButton("설치·로그인 안내")
        help_button.clicked.connect(self._help)
        row.addWidget(help_button)
        layout.addLayout(row)
        path_row = QHBoxLayout()
        self.executable = QLineEdit()
        self.executable.setPlaceholderText("CLI 실행 파일 경로 (비워 두면 자동 검색)")
        path_row.addWidget(self.executable, 1)
        self.browse = QPushButton("실행 파일 선택")
        self.browse.clicked.connect(self._browse)
        path_row.addWidget(self.browse)
        layout.addLayout(path_row)
        self.tabs = QTabWidget()
        self.preview = QPlainTextEdit(self.prompt)
        self.preview.setReadOnly(True)
        self.tabs.addTab(self.preview, "보낼 내용 확인")
        self.output = QTextBrowser()
        self.tabs.addTab(self.output, "LLM 판정")
        if review is not None:
            self.output.setHtml(review_html(review))
            self.tabs.setCurrentIndex(1)
        layout.addWidget(self.tabs, 1)
        self.status = QLabel("이 검사에서 받은 LLM 판정입니다. 다시 요청하면 구독 사용량을 소비합니다."
                             if review is not None else "아직 요청하지 않았습니다. 보낼 내용을 확인한 뒤 요청하세요.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        copy = QPushButton("질문 복사")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.prompt))
        actions.addWidget(copy)
        actions.addStretch()
        self.request = QPushButton("LLM 판정 요청")
        self.request.setObjectName("primary")
        self.request.clicked.connect(self._start)
        actions.addWidget(self.request)
        self.stop = QPushButton("중지")
        self.stop.setEnabled(False)
        self.stop.clicked.connect(self._stop)
        actions.addWidget(self.stop)
        close = QPushButton("닫기")
        close.clicked.connect(self.reject)
        actions.addWidget(close)
        layout.addLayout(actions)

    def _help(self):
        QMessageBox.information(self, "구독 계정 연결", (
            "ChatGPT: Codex CLI 설치 후 터미널에서 codex login\n"
            "Claude: Claude Code 설치 후 터미널에서 claude auth login\n\n"
            "서비스의 공식 로그인 화면에서 직접 로그인하세요. 앱은 토큰을 읽거나 저장하지 않습니다.\n"
            "구독별 CLI 이용 가능 여부와 사용 한도가 적용됩니다. API 로그인 상태는 구독 연결로 처리하지 않습니다.\n\n"
            "Codex 설치: https://developers.openai.com/codex/cli/\n"
            "Claude Code 설치: https://code.claude.com/docs/en/setup\n\n"
            "CLI 없이 쓰려면 질문을 복사해 ChatGPT나 Claude 채팅에 붙여넣을 수 있습니다."
        ))

    def _browse(self):
        filename, _ = QFileDialog.getOpenFileName(self, "공식 CLI 실행 파일 선택")
        if filename:
            self.executable.setText(filename)

    def _start(self):
        if self.worker is not None:
            return
        self.review = None
        self.output.clear()
        self.status.setText("구독 로그인 확인 후 LLM 판정을 요청합니다…")
        self.request.setEnabled(False)
        self.provider.setEnabled(False)
        self.executable.setEnabled(False)
        self.browse.setEnabled(False)
        self.stop.setEnabled(True)
        self.worker = ReviewWorker(self.prompt, self.provider.currentData(), self.executable.text().strip(), self)
        self.worker.succeeded.connect(self._success)
        self.worker.failed.connect(self._failure)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def _success(self, review):
        self.review = review
        self.output.setHtml(review_html(review))
        self.tabs.setCurrentIndex(1)
        self.status.setText("LLM 판정을 받았습니다. 규칙 판정과 함께 검토해 주세요.")

    def _failure(self, message):
        self.status.setText(message)

    def _finished(self):
        self.worker.deleteLater()
        self.worker = None
        for widget in (self.request, self.provider, self.executable, self.browse):
            widget.setEnabled(True)
        self.stop.setEnabled(False)

    def _stop(self):
        if self.worker:
            self.worker.cancel.set()
            self.status.setText("요청을 중지하고 있습니다…")

    def reject(self):
        self._stop()
        if self.worker is not None and not self.worker.wait(2000):
            return
        super().reject()

    def closeEvent(self, event):
        self._stop()
        if self.worker is not None and not self.worker.wait(2000):
            event.ignore()
            return
        super().closeEvent(event)
