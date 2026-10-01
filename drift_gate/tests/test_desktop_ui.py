"""Small offscreen checks for the optional desktop interface."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from drift_gate.desktop.app import DesktopWindow, _detail_html


def test_window_has_clear_initial_action():
    _app = QApplication.instance() or QApplication([])
    window = DesktopWindow()
    try:
        assert window.scan_button.text() == "검사 시작"
        assert not window.export_button.isEnabled()
        assert not window.llm_button.isEnabled()
        assert "저장소" in window.status_title.text()
    finally:
        window.close()


def test_rule_detail_escapes_repository_content():
    rendered = _detail_html({
        "rule_id": "<script>alert(1)</script>",
        "status": "fail",
        "reason": "<b>source</b>",
        "trigger_files": ["src/<img src=x>.py"],
        "unsatisfied_groups": [],
        "satisfied_groups": [],
    })
    assert "<script>" not in rendered
    assert "<img src=x>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_llm_dialog_does_not_send_until_requested(monkeypatch):
    from drift_gate.desktop.review_dialog import ReviewDialog
    from drift_gate.tests.test_subscription_review import scan
    _app = QApplication.instance() or QApplication([])
    calls = []
    monkeypatch.setattr("drift_gate.desktop.review_dialog.review_with_subscription", lambda *a, **k: calls.append(a))
    dialog = ReviewDialog(scan())
    try:
        assert dialog.worker is None
        assert calls == []
        assert "검사 자료" in dialog.preview.toPlainText()
    finally:
        dialog.close()


@pytest.mark.parametrize("suffix", ["json", "html"])
def test_export_keeps_gate_separate_from_llm(tmp_path, monkeypatch, suffix):
    import json
    from drift_gate.desktop.subscription_review import parse_review
    from drift_gate.tests.test_subscription_review import response, scan
    _app = QApplication.instance() or QApplication([])
    window = DesktopWindow()
    window._scan = scan()
    window._llm_review = parse_review(response("fail"), "claude")
    target = tmp_path / f"report.{suffix}"
    monkeypatch.setattr("drift_gate.desktop.app.QFileDialog.getSaveFileName",
                        lambda *args: (str(target), suffix.upper()))
    try:
        window._export()
        content = target.read_text(encoding="utf-8")
        if suffix == "json":
            data = json.loads(content)
            assert data["result"] == "pass"
            assert data["llm_review"]["verdict"] == "fail"
        else:
            assert "LLM 판정" in content
            assert "문서 확인 필요" in content
        assert window._scan.result.result == "pass"
    finally:
        window.close()
