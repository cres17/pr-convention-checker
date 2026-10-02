"""Run each phase in a fresh process with one shared isolated app-data folder."""
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT))
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from drift_gate.desktop.progress_drafts import recovery_copy
from drift_gate.desktop.progress_service import extract_requirements, load_baseline, save_baseline
from drift_gate.desktop.web_app import WebDesktopWindow

phase, raw_root = sys.argv[1:]
root = Path(raw_root)
root.mkdir(parents=True, exist_ok=True)
repo = root / 'repo'
data_dir = root / 'state'
if phase == 'edit':
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    (repo / 'README.md').write_text('# 목표\n- [ ] 로그인\n', encoding='utf-8')
    save_baseline(repo, data_dir, extract_requirements(repo, ['README.md']))
app = QApplication([])
window = WebDesktopWindow()
window.resize(1200, 900)
window.bridge.settings = QSettings(str(root / 'settings.ini'), QSettings.Format.IniFormat)
window.bridge.settings.setValue('repository', str(repo))
window.bridge._progress_dir = lambda: data_dir
QMessageBox.question = lambda *args: QMessageBox.StandardButton.Yes
window.show()
steps = 0
tries = 0
snapshot = """JSON.stringify({text:document.body.innerText,
  title:document.querySelector('[data-field="title"]')?.value,
  pending:!!Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()==='초안 복구'),
  saveDisabled:Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()==='기준과 근거 저장')?.disabled})"""

def js(code):
    window.page.runJavaScript('(() => {' + code + '})()')


def click(text):
    js("Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()===" + json.dumps(text) + ")?.click()")


def done():
    (root / f'{phase}.json').write_text(json.dumps({'phase': phase, 'pid': os.getpid(), 'passed': True}, indent=2))
    print(f'Qt fresh-process {phase} passed', flush=True)
    window.close()
    app.quit()


def inspect():
    window.page.runJavaScript(snapshot, received)


def received(raw):
    global steps, tries
    tries += 1
    try:
        state = json.loads(raw) if raw else {}
        text = state.get('text', '')
        assert '현황 응답 형식이 올바르지 않습니다' not in text
        if tries > 200:
            raise AssertionError(f'{phase} timeout at {steps}: {state}')
        if steps == 0 and '데스크톱 연결됨' in text:
            click('프로젝트 현황')
            steps = 1
        elif steps == 1 and state.get('title') is not None:
            if phase == 'edit':
                assert state['title'] == '로그인'
                js("const input=document.querySelector('[data-field=\"title\"]'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'재시작 복구 편집'); input.dispatchEvent(new Event('input',{bubbles:true}));")
                steps = 2
            elif phase == 'recover':
                assert state['title'] == '로그인' and state['pending']
                assert load_baseline(repo, data_dir)['version'] == 1
                window.grab().save(str(root / 'recovery-prompt.png'))
                click('초안 복구')
                steps = 2
            else:
                assert state['title'] == '재시작 복구 편집' and not state['pending']
                assert recovery_copy(repo, data_dir, load_baseline(repo, data_dir)) == {}
                done()
                return
        elif steps == 2 and state.get('title') == '재시작 복구 편집' and '이 기기에 보관했습니다' in text:
            assert load_baseline(repo, data_dir)['version'] == 1
            if phase == 'edit':
                assert recovery_copy(repo, data_dir, None)['recovery']['requirements'][0]['title'] == '재시작 복구 편집'
                done()
                return
            window.grab().save(str(root / 'recovered-draft.png'))
            click('기준과 근거 저장')
            steps = 3
        elif steps == 3 and not window.bridge.progress_dirty and not state.get('saveDisabled'):
            assert load_baseline(repo, data_dir)['version'] == 2
            assert recovery_copy(repo, data_dir, None) == {}
            done()
            return
        QTimer.singleShot(150, inspect)
    except BaseException as exc:
        (root / 'failure.txt').write_text(str(exc))
        print(repr(exc), flush=True)
        app.exit(1)

QTimer.singleShot(200, inspect)
sys.exit(app.exec())
