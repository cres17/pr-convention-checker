"""Source Qt + built UI checks against disposable Git repositories."""
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
from drift_gate.desktop.web_app import DesktopBridge, WebDesktopWindow
from drift_gate.desktop.progress_service import extract_requirements, save_baseline, load_baseline
from drift_gate.desktop.progress_drafts import cache_draft, draft_file
from drift_gate.tests.test_progress_service import project

mode = sys.argv[1]
assert mode in ('recovery', 'overflow')
output = Path(__file__).parent / ('native-' + mode)
output.mkdir(parents=True, exist_ok=True)
with TemporaryDirectory(prefix='draft-management-native-') as directory:
    temporary = Path(directory)
    repo = project(temporary)
    data = temporary / 'data'
    original = save_baseline(repo, data, extract_requirements(repo, ['README.md']))
    app = QApplication([])
    app.setApplicationName('Cross Agent')
    app.setOrganizationName('Drift Gate')
    prepare_check(temporary)
    window = WebDesktopWindow()
    window.resize(1440, 920)
    window.bridge._progress_dir = lambda: data
    window.bridge.settings.setValue('repository', str(repo))
    peer = DesktopBridge()
    peer._progress_dir = lambda: data
    exported = temporary / 'export.json'
    old_dialog = QFileDialog.getSaveFileName
    QFileDialog.getSaveFileName = lambda *args: (str(exported), '')
    status = {'stage': 'ready'}
    result = {'mode': mode, 'kind': 'source Qt + built React + actual QWebChannel + local persistence', 'events': []}
    if mode == 'recovery':
        for owner in ('a' * 32, 'b' * 32):
            cache_draft(repo, data, original, owner)
        peer.cacheProgressDraft(str(repo), json.dumps(original), 'peer')
        assert peer.progress_pool.waitForDone(3000)

    def fail(reason):
        result['error'] = str(reason)
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        app.exit(1)

    def script(code, then=None):
        window.page.runJavaScript(code, lambda success: (then() if then else None) if success else fail('UI action failed'))

    def click(label, then=None):
        script("(() => { const b = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === " + json.dumps(label) + "); if (!b || b.matches(':disabled')) return false; b.click(); return true; })()", then)

    def finish():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        window.grab().save(str(output / 'finished.png'))
        app.quit()

    def recovery_actions():
        script("""(() => {
          const buttons = [...document.querySelectorAll('button')];
          const recover = buttons.find(b => b.textContent.trim() === '초안 복구');
          const remove = buttons.find(b => b.textContent.trim() === '보관된 초안 삭제');
          const live = document.querySelector('[aria-label="정리할 초안 1"]');
          if (!recover?.matches(':disabled') || !remove?.matches(':disabled') || !live?.disabled) return false;
          document.querySelector('details').open = true;
          document.querySelector('[aria-label="정리할 초안 2"]').click();
          document.querySelector('[aria-label="정리할 초안 3"]').click();
          return true;
        })()""", lambda: QTimer.singleShot(300, capture_cleanup))

    def capture_cleanup():
        window.grab().save(str(output / 'active-and-cleanup.png'))
        click('선택한 초안 2개 삭제')

    def create_conflict():
        latest = deepcopy(original)
        latest['requirements'] += [dict(deepcopy(original['requirements'][0]), id=f'peer-{index}', title=f'다른 새 기능 {index}') for index in range(118)]
        save_baseline(repo, data, latest)
        click('직접 추가', lambda: QTimer.singleShot(200, lambda: click('기준과 근거 저장')))

    def verify_overflow():
        window.grab().save(str(output / 'overflow.png'))
        script("""(() => { const b = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === '내 편집을 폐기하고 최신 기준 사용'); return !!b?.matches(':disabled') && document.body.innerText.includes('상한을 넘습니다'); })()""",
               lambda: click('내 초안 파일로 내보내기'))

    def event(raw):
        value = json.loads(raw)
        kind, stage = value['type'], status['stage']
        result['events'].append({'type': kind, 'request_id': value.get('request_id'), 'request_done': value.get('request_done')})
        if kind == 'ready' and stage == 'ready':
            status['stage'] = 'documents'
            QTimer.singleShot(300, lambda: click('프로젝트 현황'))
        elif kind == 'progressDocs' and stage == 'documents':
            if mode == 'recovery':
                options = value['recovery_options']
                if len(options) != 3 or not options[0]['active']:
                    fail('Native listing did not distinguish the running app')
                    return
                status['stage'] = 'cleaning'
                QTimer.singleShot(350, recovery_actions)
            else:
                status['stage'] = 'conflict'
                QTimer.singleShot(350, create_conflict)
        elif mode == 'recovery' and kind == 'progressDocs' and stage == 'cleaning':
            if len(value['recovery_options']) != 1 or not draft_file(repo, data, peer._draft_owner).is_file():
                fail('Bulk cleanup removed the running app copy')
                return
            result['selected_inactive_copies_deleted_only'] = True
            peer.closeDraftSessions()
            status['stage'] = 'closed'
            QTimer.singleShot(250, lambda: click('초안 목록 새로고침'))
        elif mode == 'recovery' and kind == 'progressDocs' and stage == 'closed':
            if value['recovery_options'][0]['active']:
                fail('Ended app lease is still active')
                return
            result['closed_app_becomes_recoverable'] = True
            status['stage'] = 'saving'
            QTimer.singleShot(250, lambda: click('초안 복구', lambda: QTimer.singleShot(200, lambda: click('기준과 근거 저장'))))
        elif mode == 'recovery' and kind == 'progressSaved' and stage == 'saving':
            result['recovered_copy_saved_and_removed'] = not draft_file(repo, data, peer._draft_owner).exists()
            if not result['recovered_copy_saved_and_removed']:
                fail('Recovered copy cleanup failed')
            else:
                QTimer.singleShot(250, finish)
        elif mode == 'overflow' and kind == 'progressError' and stage == 'conflict' and value.get('current_baseline'):
            status['stage'] = 'exporting'
            QTimer.singleShot(300, verify_overflow)
        elif mode == 'overflow' and kind == 'progressDraftExported' and stage == 'exporting':
            payload = json.loads(exported.read_text(encoding='utf-8'))
            if len(payload['draft']['requirements']) != 3 or 'edit_base' not in payload['draft']:
                fail('Export lost local edits or merge ancestry')
                return
            result['local_draft_and_ancestry_exported'] = True
            status['stage'] = 'latest'
            QTimer.singleShot(200, lambda: click('내 편집을 폐기하고 최신 기준 사용'))
        elif mode == 'overflow' and kind == 'progressLatestUsed' and stage == 'latest':
            if len(value['baseline']['requirements']) != 120 or value['baseline'] != load_baseline(repo, data):
                fail('Latest transition used the wrong baseline')
                return
            result['latest_baseline_used'] = True
            status['stage'] = 'done'
            QTimer.singleShot(1000, lambda: verify_no_revival())
        elif kind in ('progressError', 'progressDraftError'):
            fail(value)

    def verify_no_revival():
        result['old_autosave_not_revived'] = not draft_file(repo, data, window.bridge._draft_owner).exists()
        if not result['old_autosave_not_revived']:
            fail('Discarded autosave was revived')
        else:
            finish()

    window.bridge.event.connect(event)
    QTimer.singleShot(30000, lambda: fail('Native check timed out'))
    window.show()
    code = app.exec()
    for bridge in (window.bridge, peer):
        bridge.progress_pool.waitForDone(3000)
        bridge.closeDraftSessions()
    QFileDialog.getSaveFileName = old_dialog
    sys.exit(code)
