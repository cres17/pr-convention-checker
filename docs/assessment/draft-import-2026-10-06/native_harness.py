"""Source Qt + built React checks. No installed-package or user-project claims."""
import json
import sys
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

workspace = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(workspace))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QFileDialog
from drift_gate.desktop.package_check import prepare_check
from drift_gate.desktop.web_app import WebDesktopWindow
from drift_gate.desktop.progress_drafts import export_draft, draft_file
from drift_gate.desktop.progress_service import extract_requirements, save_baseline, load_baseline
from drift_gate.tests.test_progress_service import project

output = Path(__file__).parent / 'native'
output.mkdir(parents=True, exist_ok=True)
with TemporaryDirectory(prefix='draft-import-native-') as directory:
    temporary = Path(directory)
    repo, data = project(temporary), temporary / 'data'
    original = save_baseline(repo, data, extract_requirements(repo, ['README.md']))
    draft = deepcopy(original)
    draft['edit_base'] = deepcopy(original)
    draft['requirements'][0].update(title='불러온 편집 — 저장 전 검토', implementation_status='partial',
                                   evidence={'path': 'src/login.py', 'line': 1.5, 'note': '입력 중'})
    exported, invalid = temporary / 'export.json', temporary / 'invalid.json'
    export_draft(repo, draft, exported)
    invalid.write_text('{"schema":1,"repository":"other","draft":{}}', encoding='utf-8')
    app = QApplication([])
    app.setApplicationName('Cross Agent')
    app.setOrganizationName('Drift Gate')
    prepare_check(temporary)
    window = WebDesktopWindow()
    window.resize(1440, 920)
    window.bridge._progress_dir = lambda: data
    window.bridge.settings.setValue('repository', str(repo))
    old_dialog = QFileDialog.getOpenFileName
    selections = iter(['', str(invalid), str(exported)])
    QFileDialog.getOpenFileName = lambda *args: (next(selections), '')
    state = {'stage': 'ready'}
    result = {'kind': 'macOS source Qt + built React + actual QWebChannel + temporary Git repository',
              'events': [], 'checks': {}}

    def finish(code=0, error=None):
        if error:
            result['error'] = str(error)
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        window.grab().save(str(output / 'finished.png'))
        app.exit(code)

    def script(code, then):
        window.page.runJavaScript(code, lambda value: then() if value else finish(1, 'UI action failed'))

    def click(label, then=lambda: None):
        script("(() => { const b = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === "
               + json.dumps(label) + "); if (!b || b.matches(':disabled')) return false; b.click(); return true; })()", then)

    def verify_recovered():
        script("""(() => {
            const line = document.querySelector('[data-field="evidence.line"]');
            const button = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === '초안 파일 불러오기');
            line?.scrollIntoView({block: 'center'});
            return line?.value === '1.5' && button?.disabled && document.body.innerText.includes('불러온 편집');
        })()""", lambda: QTimer.singleShot(200, capture_and_save))

    def capture_and_save():
        result['checks']['partial_input_recovered_and_import_disabled_while_dirty'] = True
        window.grab().save(str(output / 'recovered.png'))
        script("""(() => {
            const line = document.querySelector('[data-field="evidence.line"]');
            Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(line, '1');
            line.dispatchEvent(new Event('input', {bubbles: true}));
            return true;
        })()""", lambda: QTimer.singleShot(300, lambda: click('기준과 근거 저장')))

    def event(raw):
        value = json.loads(raw)
        kind, stage = value['type'], state['stage']
        result['events'].append({'type': kind, 'request_id': value.get('request_id'), 'request_done': value.get('request_done')})
        if kind == 'ready' and stage == 'ready':
            state['stage'] = 'documents'
            QTimer.singleShot(300, lambda: click('프로젝트 현황'))
        elif kind == 'progressDocs' and stage == 'documents':
            state['stage'] = 'cancel'
            QTimer.singleShot(300, lambda: click('초안 파일 불러오기'))
        elif kind == 'progressDraftImportCancelled' and stage == 'cancel':
            result['checks']['cancel_keeps_baseline'] = load_baseline(repo, data) == original
            state['stage'] = 'invalid'
            QTimer.singleShot(300, lambda: click('초안 파일 불러오기'))
        elif kind == 'progressError' and stage == 'invalid':
            result['checks']['wrong_repository_rejected_without_baseline_change'] = load_baseline(repo, data) == original and not list((data / 'drafts').glob('*.json'))
            state['stage'] = 'import'
            QTimer.singleShot(300, lambda: click('초안 파일 불러오기'))
        elif kind == 'progressDocs' and stage == 'import':
            checks = result['checks']
            checks['import_keeps_confirmed_baseline'] = value['baseline'] == original == load_baseline(repo, data)
            checks['import_stored_separately_and_selectable'] = value['recovery']['requirements'][0]['evidence']['line'] == 1.5 and not value['recovery_options'][0]['active']
            if not all(checks.values()):
                finish(1, checks)
                return
            result['copy_key'] = value['recovery_key']
            state['stage'] = 'save'
            QTimer.singleShot(350, lambda: capture_imported())
        elif kind == 'progressSaved' and stage == 'save':
            saved = load_baseline(repo, data)
            result['checks']['explicit_save_commits_imported_edit'] = saved['requirements'][0]['title'] == draft['requirements'][0]['title'] and (saved['requirements'][0]['evidence'] or {}).get('line') == 1
            result['checks']['source_backup_preserved_and_recovered_copy_removed'] = exported.is_file() and not (data / 'drafts' / result['copy_key']).exists()
            state['stage'] = 'done'
            QTimer.singleShot(1100, verify_no_revival)
        elif kind in ('progressError', 'progressDraftError'):
            finish(1, value)

    def capture_imported():
        window.grab().save(str(output / 'imported-copy.png'))
        click('초안 복구', lambda: QTimer.singleShot(300, verify_recovered))

    def verify_no_revival():
        result['checks']['saved_autosave_not_revived'] = not draft_file(repo, data, window.bridge._draft_owner).exists()
        finish(0 if all(result['checks'].values()) else 1)

    window.bridge.event.connect(event)
    QTimer.singleShot(30000, lambda: finish(1, 'Native check timed out'))
    window.show()
    code = app.exec()
    window.bridge.progress_pool.waitForDone(3000)
    window.bridge.closeDraftSessions()
    QFileDialog.getOpenFileName = old_dialog
    sys.exit(code)
