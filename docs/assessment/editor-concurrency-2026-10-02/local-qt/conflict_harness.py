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
from drift_gate.tests.test_progress_service import project

output = workspace / 'docs/assessment/editor-concurrency-2026-10-02/local-qt'
output.mkdir(parents=True, exist_ok=True)
with TemporaryDirectory(prefix='driftgate-editor-native-') as temporary:
    root = Path(temporary)
    repo = project(root)
    data = root / 'data'
    original = save_baseline(repo, data, extract_requirements(repo, ['README.md']))
    app = QApplication([])
    app.setApplicationName('Cross Agent')
    app.setOrganizationName('Drift Gate')
    prepare_check(root)
    window = WebDesktopWindow()
    window.bridge._progress_dir = lambda: data
    window.bridge.settings.setValue('repository', str(repo))
    events = []
    stage = 'ready'
    result = {'kind': 'source Qt + built React + actual QWebChannel + real local persistence'}

    def fail(reason):
        result['error'] = str(reason)
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        app.exit(1)

    def click(label, later=None):
        script = "(() => { const b = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === " + json.dumps(label) + "); if (!b || b.matches(':disabled')) return false; b.click(); return true; })()"
        window.page.runJavaScript(script, lambda success: later() if success and later else None if success else fail('Button unavailable: ' + label))

    def edit():
        other = deepcopy(original)
        other['requirements'][0]['title'] = '다른 창에서 저장한 제목'
        other['requirements'][1]['area'] = '다른 창에서 수정한 영역'
        save_baseline(repo, data, other)
        script = "(() => { const input = document.querySelector('[data-field=title]'); if (!input || input.matches(':disabled')) return false; Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, '내가 편집한 제목'); input.dispatchEvent(new Event('input', {bubbles:true})); return true; })()"
        window.page.runJavaScript(script, lambda success: QTimer.singleShot(200, lambda: click('기준과 근거 저장')) if success else fail('Editor unavailable'))

    def conflict_text(text):
        if '같은 부분을 다르게 편집한 변경 1개' not in text:
            fail('Conflict choices were not rendered: ' + text)
            return
        result['conflict_ui'] = text
        window.grab().save(str(output / 'conflict.png'))
        click('겹치는 변경은 내 편집으로 합치기', lambda: QTimer.singleShot(200, lambda: click('기준과 근거 저장')))

    def finish(text):
        saved = load_baseline(repo, data)
        if saved['version'] != 3 or saved['requirements'][0]['title'] != '내가 편집한 제목' or saved['requirements'][1]['area'] != '다른 창에서 수정한 영역':
            fail('Merged save lost an edit')
            return
        result.update({'saved_version': saved['version'], 'both_edits_preserved': True, 'saved_ui': text, 'events': events})
        window.grab().save(str(output / 'saved.png'))
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        app.quit()

    def event(raw):
        global stage
        value = json.loads(raw)
        events.append(value)
        if value['type'] == 'ready' and stage == 'ready':
            stage = 'documents'
            QTimer.singleShot(300, lambda: click('프로젝트 현황'))
        elif value['type'] == 'progressDocs' and stage == 'documents':
            stage = 'editing'
            QTimer.singleShot(350, edit)
        elif value['type'] == 'progressError' and stage == 'editing':
            if 'current_baseline' not in value:
                fail(value)
                return
            stage = 'conflict'
            QTimer.singleShot(350, lambda: window.page.runJavaScript('document.body.innerText', conflict_text))
        elif value['type'] == 'progressSaved' and stage == 'conflict':
            stage = 'saved'
            QTimer.singleShot(500, lambda: window.page.runJavaScript('document.body.innerText', finish))

    window.bridge.event.connect(event)
    QTimer.singleShot(30000, lambda: fail('Native review timed out'))
    window.show()
    status = app.exec()
    window.bridge.progress_pool.waitForDone(3000)
    sys.exit(status)
