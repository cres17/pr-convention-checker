"""Diagnostic entrypoint: render the real UI and run the real bridge offline."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
import socket
import sys
import subprocess

from PySide6.QtCore import QObject, QSettings, QTimer

from drift_gate.adapters.grammar_resources import bundled_grammar_directory
from drift_gate.desktop.resources import WEB_ROOT
from drift_gate.desktop.package_check_contract import validate_phase, validate_phases


def prepare_check(directory):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(directory / "settings"))


def network_probe():
    blocked = []
    for host in ("1.1.1.1", "140.82.112.3"):
        try:
            with socket.create_connection((host, 443), timeout=2):
                raise RuntimeError(f"Offline verification could reach {host}:443")
        except OSError as exc:
            blocked.append({"host": host, "error": str(exc), "errno": exc.errno})
    return blocked


class PackageCheck(QObject):
    def __init__(self, app, window, repository, output):
        super().__init__(window)
        self.app, self.window = app, window
        self.repository, self.output = repository, Path(output)
        challenge = os.environ.get("DRIFT_GATE_PACKAGE_CHECK_ID", "")
        if not re.fullmatch(r"[0-9a-f]{32}", challenge):
            raise RuntimeError("Package verification requires a fresh runner challenge")
        self.identity = {"run_id": challenge, "repository": str(Path(repository).resolve())}
        self.seen_run_ids = set()
        self.scan = None
        self.started = False
        self.finished = False
        self.phase = 'grammar'
        self.hardening = []
        self.last_scan = None
        self.network = network_probe()
        window.bridge.event.connect(self.on_bridge_event)
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(lambda: self.fail("UI/bridge/analysis did not complete in 45 seconds"))
        self.timeout.start(45000)

    def fail(self, reason):
        if self.finished:
            return
        self.finished = True
        self.output.write_text(json.dumps({"error": reason}), encoding="utf-8")
        self.app.exit(1)

    def on_bridge_event(self, raw):
        event = json.loads(raw)
        if event["type"] == "ready" and not self.started:
            self.started = True
            # A ready event must come from the bundled React UI's QWebChannel.
            self.window.bridge.startScan(self.repository, "HEAD")
        elif event["type"] == "scanned":
            self.last_scan = event['scan']
            if self.phase == 'grammar':
                self.scan = event["scan"]
            QTimer.singleShot(200, self.finish)
        elif event["type"] in {"error", "policyMissing"}:
            self.fail(str(event))

    def finish(self):
        if self.finished:
            return
        if self.window.bridge.scan_thread or self.window.bridge.progress_pool.activeThreadCount():
            QTimer.singleShot(100, self.finish)
            return
        try:
            if self.last_scan.get('repository') != self.identity['repository']:
                raise RuntimeError('Scan belongs to a different fixture repository')
            result = self.last_scan['result']
            run_id = validate_phase(self.phase, result, self.seen_run_ids)
        except (RuntimeError, KeyError, TypeError) as exc:
            self.fail(str(exc))
            return
        self.seen_run_ids.add(run_id)
        if self.phase != 'grammar':
            self.hardening.append({'case': self.phase, 'result': result})
        if self.phase in ('grammar', 'signature'):
            try:
                self.prepare_next_scan()
            except Exception as exc:
                self.fail(f'Could not prepare packaged regression: {exc}')
            return
        self.window.page.runJavaScript("document.body.innerText", self.rendered)

    def prepare_next_scan(self):
        root = Path(self.repository)
        def git(*args):
            subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)
        if self.phase == 'grammar':
            policy = root / '.drift-gate.yml'
            policy.write_text(policy.read_text().replace("any_changed: ['src/**']", "any_changed: ['src/**']\n      min_change_intensity: impl-only"))
            (root / 'src/api.py').write_text('def api(a,\n        b=1,\n):\n    return a\n')
        git('add', '.')
        git('-c', 'user.name=Packaged regression', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', self.phase)
        if self.phase == 'grammar':
            file = root / 'src/api.py'
            file.write_text(file.read_text().replace('        b=1,', '        *extra,\n        b=1,\n        **options,'))
            self.phase = 'signature'
        else:
            (root / 'docs').mkdir(exist_ok=True)
            git('mv', 'src/api.py', 'docs/api.py')
            self.phase = 'rename'
        self.window.bridge.startScan(self.repository, 'HEAD')

    def rendered(self, text):
        if not text or "검사" not in text:
            self.fail("Bundled UI did not render")
            return
        result = {"frozen": bool(getattr(sys, "frozen", False)), "ui": str(WEB_ROOT),
                  "ui_text": text, "bridge_ready": self.started, "network_probes": self.network,
                  "grammar_directory": str(bundled_grammar_directory()), "scan": self.scan}
        result['verification'] = self.identity
        result['hardening_checks'] = self.hardening
        try:
            from drift_gate.desktop.package_git_check import run_git_controls, validate_git_controls
            result['git_object_checks'] = run_git_controls()
            validate_git_controls(result['git_object_checks'])
        except Exception as exc:
            self.fail(f'Packaged Git object controls failed: {exc}')
            return
        try:
            validate_phases(result)
        except RuntimeError as exc:
            self.fail(str(exc))
            return
        self.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        self.window.grab().save(str(self.output.with_suffix(".png")))
        self.finished = True
        self.timeout.stop()
        self.app.exit(0)
