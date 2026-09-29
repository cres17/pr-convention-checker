"""A focused, read-only desktop view of local Drift Gate checks."""

import html
import json
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QPushButton, QSplitter,
    QTextBrowser, QVBoxLayout, QWidget,
)

from drift_gate.adapters.report_naming import default_report_path
from drift_gate.desktop.service import DesktopScan, scan_repository
from drift_gate.desktop.review_dialog import ReviewDialog, review_html
from drift_gate.desktop.subscription_review import VERDICTS
from drift_gate.reporters.html import HtmlReporter


STYLES = """
QWidget { background: #F5F7F9; color: #192B36; font-family: 'Apple SD Gothic Neo',
    'Malgun Gothic', 'Noto Sans CJK KR', sans-serif; font-size: 13px; }
QLabel { background: transparent; }
QFrame#sidebar { background: #173C45; border: 0; }
QFrame#sidebar QLabel { color: #D8E9E8; background: transparent; }
QFrame#panel, QFrame#statusPanel, QFrame#metric, QFrame#detailPanel {
    background: #FFFFFF; border: 1px solid #DCE5E7; border-radius: 14px; }
QLabel#title { font-size: 28px; font-weight: 750; color: #18313B; }
QLabel#sectionTitle { font-size: 18px; font-weight: 700; }
QLabel#muted { color: #607680; }
QLabel#metricValue { font-size: 24px; font-weight: 750; }
QLabel#statusTitle { font-size: 21px; font-weight: 750; }
QLineEdit { background: #FFFFFF; border: 1px solid #CAD8DC; border-radius: 8px;
    padding: 9px 11px; min-height: 20px; selection-background-color: #176C73; }
QLineEdit:focus { border: 2px solid #176C73; }
QPushButton { background: #FFFFFF; border: 1px solid #CAD8DC; border-radius: 8px;
    padding: 10px 15px; font-weight: 650; }
QPushButton:hover { background: #ECF5F4; border-color: #176C73; }
QPushButton:disabled { color: #93A2A9; background: #F0F3F4; }
QPushButton#primary { background: #176C73; color: #FFFFFF; border: 0; padding: 11px 23px; }
QPushButton#primary:hover { background: #125961; }
QListWidget { background: #FFFFFF; border: 0; outline: 0; }
QListWidget::item { padding: 13px 12px; border-bottom: 1px solid #EDF1F2; }
QListWidget::item:selected { background: #E3F2F0; color: #123D43; }
QTextBrowser { background: #FFFFFF; border: 0; padding: 13px; }
"""

STATUS = {
    "fail": ("조치가 필요한 항목이 있습니다", "문서 또는 정책 요구사항을 확인해 주세요.", "#B43F35"),
    "warn": ("검사는 완료됐고, 확인할 항목이 있습니다", "경고와 판정 근거를 확인해 주세요.", "#9A6A13"),
    "pass": ("설정된 규칙을 통과했습니다", "아래에서 규칙별 판정 근거를 확인할 수 있습니다.", "#176C73"),
}
DECISION = {"pass": "통과", "fail": "조치 필요", "skipped": "제외", "unmatched": "대상 아님", "rejected-ignore": "예외 거절"}


class ScanWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, path: str, base: str):
        super().__init__()
        self.path = path
        self.base = base

    @Slot()
    def run(self):
        try:
            self.finished.emit(scan_repository(self.path, self.base))
        except Exception as exc:
            self.failed.emit(str(exc))


def _label(text: str, name: str = "") -> QLabel:
    item = QLabel(text)
    if name:
        item.setObjectName(name)
    item.setWordWrap(True)
    return item


def _panel(name: str = "panel") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName(name)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(10)
    return frame, layout


def _detail_html(decision: dict) -> str:
    escape = lambda value: html.escape(str(value or ""))
    summary = {
        "fail": "필요한 문서 조건이 충족되지 않았습니다.",
        "pass": "필요한 문서 조건이 충족되었습니다.",
        "unmatched": "이번 변경에 해당하는 코드가 없습니다.",
        "skipped": "이번 검사에서 제외된 규칙입니다.",
        "rejected-ignore": "요청한 예외가 허용되지 않았습니다.",
    }.get(decision.get("status"), "판정 근거를 확인해 주세요.")
    groups = decision.get("unsatisfied_groups", [])
    satisfied = decision.get("satisfied_groups", [])
    sections = [
        f"<h2 style='color:#18313B'>{escape(decision.get('rule_id'))}</h2>",
        f"<p><b>판정</b> · {escape(DECISION.get(decision.get('status'), decision.get('status')))}</p>",
        f"<p>{escape(summary)}</p>",
    ]
    triggers = decision.get("trigger_files", [])
    if triggers:
        sections.append("<h3>변경된 코드</h3><ul>" + "".join(f"<li>{escape(path)}</li>" for path in triggers) + "</ul>")
    if groups:
        sections.append("<h3>확인하거나 수정할 문서</h3>")
        for group in groups:
            paths = ", ".join(group.get("required", []))
            evidence = group.get("evidence", "")
            sections.append(f"<p><b>{escape(group.get('name'))}</b><br>{escape(paths)}<br>{escape(evidence)}</p>")
    if satisfied:
        sections.append("<h3>충족된 조건</h3><ul>" + "".join(
            f"<li>{escape(group.get('name'))}: {escape(group.get('evidence'))}</li>" for group in satisfied
        ) + "</ul>")
    if decision.get("reason"):
        sections.append(f"<p style='color:#607680'><b>엔진 근거</b> · {escape(decision['reason'])}</p>")
    return "<div style='font-size:14px;line-height:1.55;color:#344B55'>" + "".join(sections) + "</div>"


class DesktopWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Drift Gate · 로컬 검사")
        self.resize(1180, 850)
        self.setMinimumSize(900, 620)
        self._settings = QSettings("Drift Gate", "Desktop")
        self._scan: DesktopScan | None = None
        self._llm_review = None
        self._thread: QThread | None = None
        self._worker: ScanWorker | None = None
        self._build()

    def _build(self):
        root = QWidget()
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(238)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(24, 34, 24, 28)
        side.setSpacing(14)
        brand = _label("DG  /  DRIFT GATE")
        brand.setStyleSheet("font-size: 16px; font-weight: 800; letter-spacing: 1px; color: white;")
        side.addWidget(brand)
        side.addWidget(_label("코드와 문서의 변경을\n한 화면에서 점검합니다."))
        side.addSpacing(28)
        for number, title, description in (
            ("01", "저장소 선택", "정책이 있는 Git 폴더"),
            ("02", "변경 검사", "기준 커밋과 현재 파일 비교"),
            ("03", "결과 확인", "규칙별 근거와 필요한 문서"),
        ):
            item = _label(f"{number}   {title}\n        {description}")
            item.setStyleSheet("line-height: 1.5; padding: 10px 0; color: #D8E9E8;")
            side.addWidget(item)
        side.addStretch()
        side.addWidget(_label("로컬 검사 · 읽기 전용\nPR 검사는 GitHub Actions에서 실행"))
        row.addWidget(sidebar)

        content = QWidget()
        main = QVBoxLayout(content)
        main.setContentsMargins(30, 24, 30, 24)
        main.setSpacing(14)
        main.addWidget(_label("로컬 변경 검사", "title"))
        main.addWidget(_label("코드 변경에 맞는 문서가 준비됐는지 확인하세요. 검사는 파일을 수정하지 않습니다.", "muted"))

        inputs, inputs_layout = _panel()
        inputs_layout.addWidget(_label("검사할 저장소", "sectionTitle"))
        source_row = QHBoxLayout()
        self.path_input = QLineEdit(str(self._settings.value("repository", "")))
        self.path_input.setPlaceholderText("Git 저장소 폴더를 선택하세요")
        self.path_input.setAccessibleName("검사할 저장소 경로")
        source_row.addWidget(self.path_input, 1)
        browse = QPushButton("폴더 선택")
        browse.clicked.connect(self._browse)
        source_row.addWidget(browse)
        inputs_layout.addLayout(source_row)
        base_row = QHBoxLayout()
        base_row.addWidget(_label("비교 기준"))
        self.base_input = QLineEdit(str(self._settings.value("base", "HEAD")))
        self.base_input.setPlaceholderText("HEAD")
        self.base_input.setToolTip("HEAD는 마지막 커밋 이후 변경, main은 main 이후 변경을 확인합니다.")
        self.base_input.setAccessibleName("비교 기준 커밋 또는 브랜치")
        self.base_input.setMaximumWidth(170)
        base_row.addWidget(self.base_input)
        base_row.addWidget(_label("HEAD: 커밋 전 변경  ·  main: 브랜치 전체 변경", "muted"), 1)
        self.scan_button = QPushButton("검사 시작")
        self.scan_button.setObjectName("primary")
        self.scan_button.clicked.connect(self._start_scan)
        base_row.addWidget(self.scan_button)
        inputs_layout.addLayout(base_row)
        inputs_layout.addWidget(_label("Git에 추가하지 않은 새 파일은 검사에 포함되지 않습니다.", "muted"))
        main.addWidget(inputs)

        status_panel, status_layout = _panel("statusPanel")
        self.status_title = _label("저장소를 선택하면 검사를 시작할 수 있습니다", "statusTitle")
        self.status_description = _label(".drift-gate.yml이 있는 저장소와 비교 기준을 입력해 주세요.", "muted")
        status_layout.addWidget(self.status_title)
        status_layout.addWidget(self.status_description)
        main.addWidget(status_panel)

        metrics = QHBoxLayout()
        self.metric_labels = {}
        for key, title in (("files", "변경 파일"), ("rules", "평가된 규칙"), ("blockers", "차단 항목")):
            frame, layout = _panel("metric")
            layout.addWidget(_label(title, "muted"))
            value = _label("—", "metricValue")
            layout.addWidget(value)
            self.metric_labels[key] = value
            metrics.addWidget(frame)
        main.addLayout(metrics)

        heading = QHBoxLayout()
        heading.addWidget(_label("규칙별 판정", "sectionTitle"), 1)
        self.policy_button = QPushButton("정책 파일 열기")
        self.policy_button.setEnabled(False)
        self.policy_button.clicked.connect(self._open_policy)
        heading.addWidget(self.policy_button)
        self.llm_button = QPushButton("LLM 추가 판정")
        self.llm_button.setEnabled(False)
        self.llm_button.clicked.connect(self._review_with_llm)
        heading.addWidget(self.llm_button)
        self.export_button = QPushButton("결과 저장")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export)
        heading.addWidget(self.export_button)
        main.addLayout(heading)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        list_panel, list_layout = _panel("detailPanel")
        list_layout.addWidget(_label("판정 목록", "muted"))
        self.decisions = QListWidget()
        self.decisions.setAccessibleName("규칙별 판정 목록")
        self.decisions.currentItemChanged.connect(self._show_decision)
        list_layout.addWidget(self.decisions)
        splitter.addWidget(list_panel)
        detail_panel, detail_layout = _panel("detailPanel")
        detail_layout.addWidget(_label("판정 근거", "muted"))
        self.detail = QTextBrowser()
        self.detail.setHtml("<p style='color:#607680'>검사 후 규칙을 선택하면 변경 파일과 필요한 문서를 볼 수 있습니다.</p>")
        detail_layout.addWidget(self.detail)
        splitter.addWidget(detail_panel)
        splitter.setSizes([330, 560])
        main.addWidget(splitter, 1)
        row.addWidget(content, 1)
        self.setCentralWidget(root)
        self.setStyleSheet(STYLES)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "검사할 Git 저장소 선택", self.path_input.text())
        if folder:
            self.path_input.setText(folder)

    def _start_scan(self):
        if self._thread is not None:
            return
        self._scan = None
        self._llm_review = None
        self.llm_button.setEnabled(False)
        self.llm_button.setText("LLM 추가 판정")
        self.policy_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.decisions.clear()
        self.detail.setHtml("<p>검사 결과를 기다리고 있습니다.</p>")
        for value in self.metric_labels.values():
            value.setText("—")
        self.scan_button.setEnabled(False)
        self.scan_button.setText("검사 중…")
        self.status_title.setText("변경 사항을 검사하고 있습니다")
        self.status_description.setText("정책과 코드 변경을 확인하는 동안 잠시 기다려 주세요.")
        self._thread = QThread(self)
        self._worker = ScanWorker(self.path_input.text(), self.base_input.text())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._show_result)
        self._worker.failed.connect(self._show_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._reset_worker)
        self._thread.start()

    def _reset_worker(self):
        self._thread = None
        self._worker = None
        self.scan_button.setEnabled(True)
        self.scan_button.setText("다시 검사")

    def _show_error(self, message: str):
        self.status_title.setText("검사를 시작할 수 없습니다")
        self.status_title.setStyleSheet("color: #B43F35;")
        self.status_description.setText(message)

    def _show_result(self, scan: DesktopScan):
        self._scan = scan
        self._settings.setValue("repository", str(scan.repository))
        self._settings.setValue("base", scan.base)
        self.path_input.setText(str(scan.repository))
        result = scan.result
        if scan.changed_file_count == 0:
            title, description, color = ("변경 파일이 없습니다", "비교 기준 이후 Git이 추적하는 변경 파일이 없습니다.", "#607680")
        elif result.skip:
            title, description, color = ("이번 변경은 검사 대상에서 제외됐습니다", "문서 또는 테스트만 변경됐는지 확인해 주세요.", "#607680")
        else:
            title, description, color = STATUS.get(result.result, STATUS["pass"])
        self.status_title.setText(title)
        self.status_title.setStyleSheet(f"color: {color};")
        self.status_description.setText(f"{description}  ·  기준: {scan.base}")
        self.metric_labels["files"].setText(str(scan.changed_file_count))
        self.metric_labels["rules"].setText(str(len(result.rule_decisions)))
        self.metric_labels["blockers"].setText(str(result.blocker_count))
        self.policy_button.setEnabled(True)
        self.export_button.setEnabled(True)
        self.llm_button.setEnabled(scan.changed_file_count > 0)
        self.decisions.clear()
        for decision in result.rule_decisions:
            data = decision.to_dict()
            item = QListWidgetItem(f"{DECISION.get(data['status'], data['status'])}   ·   {data['rule_id']}")
            item.setData(Qt.ItemDataRole.UserRole, data)
            self.decisions.addItem(item)
        if self.decisions.count():
            self.decisions.setCurrentRow(0)
        else:
            message = "평가된 규칙이 없습니다. 변경 파일과 정책의 경로 조건을 확인해 주세요."
            self.detail.setHtml(f"<p>{html.escape(message)}</p>")

    def closeEvent(self, event):
        if self._thread is not None and self._thread.isRunning():
            self._thread.wait()
        super().closeEvent(event)

    def _show_decision(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None):
        if current is not None:
            self.detail.setHtml(_detail_html(current.data(Qt.ItemDataRole.UserRole)))

    def _open_policy(self):
        if self._scan:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._scan.repository / ".drift-gate.yml")))

    def _review_with_llm(self):
        if self._scan is None:
            return
        dialog = ReviewDialog(self._scan, self._llm_review, self)
        dialog.exec()
        self._llm_review = dialog.review
        self.llm_button.setText(
            f"LLM: {VERDICTS[self._llm_review.verdict]}" if self._llm_review else "LLM 추가 판정")

    def _export(self):
        if not self._scan:
            return
        filename, selected_filter = QFileDialog.getSaveFileName(
            self, "검사 결과 저장", str(default_report_path(self._scan.repository, "drift-report", "html", self._scan.policy_source)),
            "HTML 보고서 (*.html);;JSON 데이터 (*.json)",
        )
        if not filename:
            return
        target = Path(filename)
        try:
            if "JSON" in selected_filter or target.suffix.lower() == ".json":
                data = self._scan.result.to_dict()
                if self._llm_review is not None:
                    data["llm_review"] = self._llm_review.to_dict()
                target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                report = HtmlReporter().render(self._scan.result, policy_source=self._scan.policy_source)
                if self._llm_review is not None:
                    report = report.replace("</main>", "<section class='card'>" + review_html(self._llm_review) + "</section></main>")
                target.write_text(report, encoding="utf-8")
        except OSError as exc:
            self._show_error(f"결과를 저장하지 못했습니다: {exc}")


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Drift Gate")
    app.setOrganizationName("Drift Gate")
    app.setStyle("Fusion")
    window = DesktopWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
