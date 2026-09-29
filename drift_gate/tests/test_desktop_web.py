"""Bridge contract checks; no model calls or real user repository mutations."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
pytest.importorskip('PySide6.QtWebEngineWidgets')
from PySide6.QtWidgets import QApplication
from drift_gate.desktop.web_app import DesktopBridge, scan_payload
from drift_gate.tests.test_subscription_review import scan, response
from drift_gate.desktop.subscription_review import parse_review


def test_payload_uses_engine_result_without_reclassification():
    value = scan()
    payload = scan_payload(value)
    assert payload['result'] == value.result.to_dict()
    assert payload['policy'] == value.policy_source
    assert payload['files'] == []


def test_bridge_keeps_llm_separate_and_exports(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    bridge = DesktopBridge()
    bridge.scan = scan()
    bridge.review = parse_review(response('fail'), 'codex')
    target = tmp_path / 'report.json'
    monkeypatch.setattr('drift_gate.desktop.web_app.QFileDialog.getSaveFileName',lambda *args: (str(target),''))
    bridge.exportReport('json')
    data = json.loads(target.read_text())
    assert data['result'] == 'pass'
    assert data['llm_review']['verdict'] == 'fail'


def test_bridge_does_not_start_llm_without_scan():
    app = QApplication.instance() or QApplication([])
    bridge = DesktopBridge()
    bridge.startReview('codex', '')
    assert bridge.review_worker is None
