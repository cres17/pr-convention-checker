import json
import sys
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

workspace = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(workspace))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from drift_gate.desktop.package_check import prepare_check
from drift_gate.desktop.web_app import WebDesktopWindow
from drift_gate.desktop.progress_service import extract_requirements, save_baseline, load_baseline
from drift_gate.desktop.progress_drafts import cache_draft, draft_file
from drift_gate.tests.test_progress_service import project

output = workspace / 'docs/assessment/editor-concurrency-2026-10-02/local-recovery'
output.mkdir(parents=True, exist_ok=True)
with TemporaryDirectory(prefix='driftgate-recovery-native-') as temporary:
    root = Path(temporary)
    repo = project(root)
    data = root / 'data'
    base = save_baseline(repo, data, extract_requirements(repo, ['README.md']))
    for owner in ['a', 'c', 'b']:
        draft = deepcopy(base)
        draft['requirements'][0]['title'] = owner + ' 실행의 편집'
        cache_draft(repo, data, draft, owner * 32)
    selected = draft_file(repo, data, 'a' * 32)
    recovered = draft_file(repo, data, 'b' * 32)
    preserved = draft_file(repo, data, 'c' * 32)
    app = QApplication([])
    app.setApplicationName('Cross Agent')
    app.setOrganizationName('Drift Gate')
    prepare_check(root)
    window = WebDesktopWindow()
    window.bridge._progress_dir = lambda: data
    window.bridge.settings.setValue('repository', str(repo))
    status = {'stage': 'ready'}
    result = {'kind': 'source Qt + built React + real QWebChannel overloaded recovery APIs', 'events': []}

    def fail(reason):
        result['error'] = str(reason)
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        app.exit(1)

    def click(label, later=None):
        script = "(() => { const b = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === " + json.dumps(label) + "); if (!b || b.matches(':disabled')) return false; b.click(); return true; })()"
        window.page.runJavaScript(script, lambda success: later() if success and later else None if success else fail('Unavailable: ' + label))

    def choose():
        window.grab().save(str(output / 'recovery.png'))
        script = "(() => { const s = document.querySelector('[aria-label=\"복구할 초안\"]'); if (!s || s.options.length !== 3) return false; s.value = " + json.dumps(selected.name) + "; s.dispatchEvent(new Event('change',{bubbles:true})); return true; })()"
        window.page.runJavaScript(script, lambda success: None if success else fail('Recovery selector unavailable'))

    def finish():
        baseline = load_baseline(repo, data)
        if selected.exists() or recovered.exists() or not preserved.exists() or baseline['requirements'][0]['title'] != 'b 실행의 편집':
            fail('Recovery/discard/save removed the wrong copy')
            return
        result.update({'selected_copy_deleted': True, 'recovered_copy_committed_and_deleted': True,
                       'unselected_copy_preserved': True, 'saved_version': baseline['version']})
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        app.quit()

    def event(raw):
        value = json.loads(raw)
        result['events'].append(value)
        kind, stage = value['type'], status['stage']
        if kind == 'ready' and stage == 'ready':
            status['stage'] = 'choosing'
            QTimer.singleShot(300, lambda: click('프로젝트 현황'))
        elif kind == 'progressDocs' and stage == 'choosing':
            status['stage'] = 'selected'
            QTimer.singleShot(350, choose)
        elif kind == 'progressDocs' and stage == 'selected':
            if value.get('recovery_key') != selected.name:
                fail('Three-argument document request selected the wrong copy')
                return
            status['stage'] = 'deleted'
            QTimer.singleShot(250, lambda: click('보관된 초안 삭제'))
        elif kind == 'progressDocs' and stage == 'deleted':
            if len(value.get('recovery_options', [])) != 2 or value.get('recovery_key') != recovered.name:
                fail('Four-argument discard request removed the wrong copy')
                return
            status['stage'] = 'saving'
            QTimer.singleShot(250, lambda: click('초안 복구', lambda: QTimer.singleShot(200, lambda: click('기준과 근거 저장'))))
        elif kind == 'progressSaved' and stage == 'saving':
            status['stage'] = 'done'
            QTimer.singleShot(350, finish)
        elif kind in ['progressError', 'progressDraftError']:
            fail(value)

    window.bridge.event.connect(event)
    QTimer.singleShot(30000, lambda: fail('Recovery check timed out'))
    window.show()
    code = app.exec()
    window.bridge.progress_pool.waitForDone(3000)
    sys.exit(code)
