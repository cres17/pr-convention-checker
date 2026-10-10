"""Controlled ordering and malformed-input audit using real Qt workers, no window."""
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from drift_gate.desktop.web_app import DesktopBridge
from drift_gate.desktop.progress_service import extract_requirements, save_baseline, inspect_progress
from reproduce import make_repo


def main():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix='driftgate-bridge-audit-') as temporary:
        directory = Path(temporary).resolve()
        root = make_repo(directory / 'repo')
        state = directory / 'state'
        bridge = DesktopBridge()
        bridge._progress_dir = lambda: state
        messages = []
        bridge.event.connect(lambda raw: messages.append(json.loads(raw)))
        draft = extract_requirements(root, ['README.md'])
        saved = save_baseline(root, state, draft)
        malformed = directory / 'results.json'
        malformed.write_text('{"testResults":[{"name":"test","assertionResults":1}]}')
        settings_key = bridge._results_key(str(root))
        # Temporary project hash only; remove this entry before returning.
        try:
            with patch('drift_gate.desktop.web_app.QFileDialog.getOpenFileName', return_value=(str(malformed), '')):
                bridge.loadTestResults(str(root), 'bad-results')
                assert bridge.progress_pool.waitForDone(10000)
                app.processEvents()
            assert not messages
            malformed_result = {'worker_finished': True, 'terminal_events': len(messages)}
        finally:
            bridge.settings.remove(settings_key)

        def concurrent_save_then_inspect(path, directory):
            second = json.loads(json.dumps(saved))
            second['requirements'][0]['title'] = 'Other editor'
            newer = save_baseline(path, directory, second)
            assert newer['version'] == 2
            return inspect_progress(path, directory)
        with patch('drift_gate.desktop.web_app.inspect_progress', side_effect=concurrent_save_then_inspect):
            bridge.saveProgress(str(root), json.dumps(saved), 'save-first')
            assert bridge.progress_pool.waitForDone(10000)
            app.processEvents()
        versions = {event['type']: event.get('baseline', event.get('report', {})).get('version') for event in messages}
        assert versions['progressSaved'] == 1 and versions['progressReport'] == 2
        history = next(event for event in messages if event['type'] == 'progressHistory')
        assert history['snapshots'][0]['version'] == 2
        bridge.closeDraftSessions()
        print(json.dumps({'malformed_results': malformed_result, 'interleaved_save': {
            'saved_version': 1, 'reported_version': 2, 'history_version': 2,
            'ordering': 'another writer commits between save_baseline and inspect_progress'}}, indent=2))


if __name__ == '__main__':
    main()
