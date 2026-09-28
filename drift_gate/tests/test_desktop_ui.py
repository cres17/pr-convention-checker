"""Small offscreen checks for the optional desktop interface."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from drift_gate.desktop.app import DesktopWindow, _detail_html


def test_window_has_clear_initial_action():
    app = QApplication.instance() or QApplication([])
    window = DesktopWindow()
    try:
        assert window.scan_button.text() == "검사 시작"
        assert not window.export_button.isEnabled()
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
