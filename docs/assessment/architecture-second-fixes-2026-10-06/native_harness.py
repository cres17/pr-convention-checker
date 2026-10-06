"""Temporary-source Qt/QWebChannel flow, not an installed-package claim."""
import json
import sys
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

workspace = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(workspace))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from drift_gate.desktop.package_check import prepare_check
from drift_gate.desktop.web_app import WebDesktopWindow
from drift_gate.desktop.progress_service import extract_requirements, save_baseline, load_baseline
from drift_gate.tests.test_progress_service import project

output = Path(__file__).parent / 'native'
output.mkdir(parents=True, exist_ok=True)
with TemporaryDirectory(prefix='archived-document-native-') as directory:
    temporary = Path(directory)
    repo, data = project(temporary), temporary / 'data'
    draft = extract_requirements(repo, ['README.md'])
    draft['requirements'][0].update(implementation_status='implemented',
        evidence={'path':'src/login.py','line':1,'note':'확인'},
        verification_status='verified', verification_note='수동 검증')
    original = save_baseline(repo, data, draft)
    originals = deepcopy(original['requirements'])
    (repo / 'README.md').rename(repo / 'PLAN.md')
    history = next(data.glob('*.json')).with_suffix('.history.json')
    history.write_text('{"schema":1,"snapshots":[{}]}', encoding='utf-8')
    original_history = history.read_bytes()
    app = QApplication([])
    app.setApplicationName('Cross Agent')
    app.setOrganizationName('Drift Gate')
    prepare_check(temporary)
    window = WebDesktopWindow()
    window.resize(1440, 980)
    window.bridge._progress_dir = lambda: data
    window.bridge.settings.setValue('repository', str(repo))
    state = {'stage':'ready'}
    result = {'kind':'macOS source Qt + built React + QWebChannel + temporary repository',
              'confirmation':'fixture replaces window.confirm with an affirmative answer',
              'checks':{}, 'events':[]}

    def finish(error=None):
        if state['stage'] == 'finished':
            return
        state['stage'] = 'finished'
        if error:
            result['error'] = str(error)
        window.grab().save(str(output / 'finished.png'))
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        app.exit(1 if error or not all(result['checks'].values()) else 0)

    def script(code, then):
        window.page.runJavaScript(code, lambda value: QTimer.singleShot(220, then) if value else finish('UI action failed'))

    def click(label, then=lambda: None):
        script("(() => { const b = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === "
               + json.dumps(label) + "); if (!b || b.matches(':disabled')) return false; b.click(); return true; })()", then)

    def archive():
        script("(() => { window.confirm = () => true; const b = document.querySelector('[aria-label=\"README.md 연결 해제하고 출처 보관\"]'); if(!b || b.disabled) return false; b.click(); return true; })()", select_new)

    def select_new():
        script("""(() => { const row = [...document.querySelectorAll('.progress-doc')].find(r => r.querySelector('input') && r.textContent.includes('PLAN.md'));
            const input = row?.querySelector('input'); if (!input || input.disabled) return false; input.click(); return true; })()""",
            lambda: click('기능 후보 추출'))

    def verify_ui():
        window.page.runJavaScript("""(() => JSON.stringify({ warning:document.body.innerText.includes('이력 비교는 사용할 수 없습니다'),
            overview:document.body.innerText.includes('구현 확인') && document.body.innerText.includes('재확인 필요'),
            archived:document.body.innerText.includes('README.md (참고)') }))()""", verified)

    def verified(value):
        value = json.loads(value) if isinstance(value, str) else value
        result['checks'].update({'history_warning_visible':bool(value and value.get('warning')),
                               'report_visible_after_save':bool(value and value.get('overview')),
                               'archived_document_visible':bool(value and value.get('archived')),
                               'bad_history_bytes_preserved':history.read_bytes() == original_history})
        finish()

    def event(raw):
        value = json.loads(raw)
        kind, stage = value['type'], state['stage']
        result['events'].append({'type':kind, 'request_done':value.get('request_done')})
        if kind == 'ready' and stage == 'ready':
            state['stage'] = 'documents'
            QTimer.singleShot(300, lambda: click('프로젝트 현황'))
        elif kind == 'progressDocs' and stage == 'documents':
            result['checks']['original_baseline_loaded'] = value['baseline'] == original
            state['stage'] = 'extract'
            QTimer.singleShot(350, lambda: click('기준 문서 변경', archive))
        elif kind == 'progressPreview' and stage == 'extract':
            state['stage'] = 'save'
            QTimer.singleShot(300, lambda: click('기준과 근거 저장'))
        elif kind == 'progressSaved' and stage == 'save':
            latest = load_baseline(repo, data)
            result['checks'].update({'saved_version_advanced':latest['version'] == 2,
                'old_goals_and_evidence_preserved':latest['requirements'][:2] == originals,
                'explicit_archive_saved':latest.get('archived_documents') == ['README.md'],
                'new_document_added':latest['documents'].get('PLAN.md') is not None})
            state['stage'] = 'history'
        elif kind == 'progressHistory' and stage == 'history':
            result['checks']['unavailable_history_event'] = bool(value.get('warning'))
            state['stage'] = 'verify'
            QTimer.singleShot(500, verify_ui)
        elif kind in ('progressError','progressDraftError'):
            finish(value)

    window.bridge.event.connect(event)
    QTimer.singleShot(25000, lambda: finish('Native flow timed out'))
    window.show()
    code = app.exec()
    window.bridge.progress_pool.waitForDone(3000)
    window.bridge.closeDraftSessions()
    sys.exit(code)
