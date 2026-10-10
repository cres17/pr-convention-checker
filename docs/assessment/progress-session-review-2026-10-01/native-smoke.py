import json
import subprocess
import sys
from pathlib import Path

import tempfile
PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT))
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from drift_gate.desktop.progress_service import extract_requirements, save_baseline, inspect_progress, link_test_results
from drift_gate.desktop.web_app import WebDesktopWindow

root = Path(tempfile.mkdtemp(prefix="driftgate-session-review-"))
root.mkdir(exist_ok=True)
repo = root / "repo"
repo.mkdir(exist_ok=True)
subprocess.run(["git", "init", "-q", str(repo)], check=True)
(repo / "README.md").write_text("# 목표\n- [ ] 결제\n- [ ] 알림\n- [ ] 로그인\n", encoding="utf-8")
(repo / "past.md").write_text("# 과거 결과\n- [ ] 과거 기능\n", encoding="utf-8")
(repo / "src").mkdir(exist_ok=True)
for name in ("pay", "login"):
    (repo / f"src/{name}.py").write_text(f"def {name}():\n    return True\n", encoding="utf-8")
draft = extract_requirements(repo, ["README.md", "past.md"])
draft["document_kinds"]["past.md"] = "past"
for index, name in ((0, "pay"), (2, "login"), (3, "pay")):
    draft["requirements"][index].update(implementation_status="implemented",
        evidence={"path": f"src/{name}.py", "line": 1, "note": "함수 확인"},
        verification_status="verified", verification_note="직접 검증")
for index, pattern in enumerate(("test_pay_typo", "test_alert_typo", "test_login", "test_past_typo")):
    draft["requirements"][index]["test_patterns"] = [pattern]
initial_saved = save_baseline(repo, root / "state", draft)
results_file = root / "results.xml"
results_file.write_text('<testsuite><testcase name="test_login"/><testcase name="test_pay_req-' + draft["requirements"][0]["id"][:8] + '"/><testcase name="test_past_req-' + draft["requirements"][3]["id"][:8] + '"/></testsuite>', encoding="utf-8")
assert draft["requirements"][3]["id"] not in link_test_results(repo, root / "state", results_file)["items"]
(repo / "src/pay.py").write_text("def pay():\n    return False\n", encoding="utf-8")
report = inspect_progress(repo, root / "state")
assert report["total"] == 3 and report["counts"]["unknown"] == 2 and report["counts"]["excluded"] == 1
app = QApplication([])
window = WebDesktopWindow()
window.resize(1200, 900)
window.bridge.settings = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
window.bridge.settings.setValue("repository", str(repo))
window.bridge._progress_dir = lambda: root / "state"
window.bridge.settings.setValue(window.bridge._results_key(str(repo)), str(results_file))
QFileDialog.getOpenFileName = lambda *args: ("", "")
cancel_messages = []
wire_events = []
def remember_event(raw):
    value = json.loads(raw)
    cancel_messages.append(value["type"])
    wire_events.append(value)
    (root / "wire-events.json").write_text(json.dumps(wire_events, ensure_ascii=False, indent=2), encoding="utf-8")
window.bridge.event.connect(remember_event)
window.show()
stage = 0
tries = 0
card_index = 0
card_names = ["완료 확인 1개 보기", "구현 확인 1개 보기", "근거 없음 1개 보기", "재확인 필요 1개 보기"]
card_lists = [["로그인"], ["로그인"], ["알림"], ["결제"]]
result = {}
snapshot = """(() => ({text:document.body.innerText,
  cards:Array.from(document.querySelectorAll('.progress-stat')).map(b=>({
    name:b.getAttribute('aria-label'),pressed:b.getAttribute('aria-pressed'),
    x:b.getBoundingClientRect().x,y:b.getBoundingClientRect().y})),
  list:Array.from(document.querySelectorAll('.progress-list .progress-row strong')).map(b=>b.innerText.trim()),
  diffReady:document.querySelector('diffs-container')?.shadowRoot?.textContent?.includes('members') || false,
  title:document.querySelector('[data-field="title"]')?.value,
  next:document.querySelector('.progress-next')?.textContent,
  filter:document.querySelector('.progress-toolbar select')?.value,
  search:document.querySelector('input[placeholder="기능명·조건"]')?.value,
  saveDisabled:Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()==='기준과 근거 저장')?.disabled,
  overflow:document.documentElement.scrollWidth>innerWidth}))()"""

def js(code):
    window.page.runJavaScript("(() => {" + code + "})()")

def click(name):
    js("document.querySelector('button[aria-label=" + json.dumps(name) + "]')?.click()")

def inspect():
    window.page.runJavaScript("JSON.stringify(" + snapshot + ")", lambda raw: received(json.loads(raw) if raw else {}))

def received(data):
    global stage, tries, card_index
    tries += 1
    try:
        text = data.get("text", "") if data else ""
        if stage == 0 and "데스크톱 연결됨" in text:
            js("Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()==='프로젝트 현황')?.click()")
            stage = 1
        elif stage == 1 and any(c["name"] == "재확인 필요 1개 보기" for c in data["cards"]) and "자동 검증 기록" in text:
            assert len(data["list"]) == 3
            click(card_names[card_index])
            stage = 2
        elif stage == 2 and data["list"] == card_lists[card_index]:
            card = next(c for c in data["cards"] if c["name"] == card_names[card_index])
            assert card["pressed"] == "true"
            click(card_names[card_index])
            stage = 3
        elif stage == 3 and data["filter"] == "all" and len(data["list"]) == 3:
            assert all(c["pressed"] == "false" for c in data["cards"])
            card_index += 1
            if card_index < len(card_names):
                click(card_names[card_index])
                stage = 2
            else:
                window.grab().save(str(root / "cards-released.png"))
                js("const el=document.querySelector('.progress-toolbar select');Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(el,'excluded');el.dispatchEvent(new Event('change',{bubbles:true}));")
                stage = 4
        elif stage == 4 and data["list"] == ["과거 기능"] and "현재 목표 집계에서 제외" in (data.get("next") or ""):
            assert "자동 검증 기록" not in text
            assert "저장소의 테스트 파일에서 찾지 못한 이름" not in text
            assert "다음: 코드 근거 확인" not in text
            assert "현재 목표 범위 밖이므로 테스트 힌트와 결과 연결을 적용하지 않습니다" in text
            js("document.querySelector('.progress-workspace')?.scrollIntoView()")
            stage = 5
        elif stage == 5:
            js("Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()==='테스트 결과 불러오기')?.click()")
            stage = 6
        elif stage == 6 and "읽는 중…" not in text and "progressTestsCancelled" in cancel_messages:
            assert window.bridge.settings.value(window.bridge._results_key(str(repo))) == str(results_file)
            assert "results.xml" in text
            assert data["saveDisabled"] is False
            window.grab().save(str(root / "excluded-item.png"))
            js("const el=document.querySelector('[data-field=\"title\"]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,'과거 기능 편집 보존');el.dispatchEvent(new Event('input',{bubbles:true}));")
            stage = 7
        elif stage == 7 and data.get("title") == "과거 기능 편집 보존" and window.bridge.progress_dirty:
            previous_question = QMessageBox.question
            QMessageBox.question = lambda *args: QMessageBox.StandardButton.No
            window.close()
            QMessageBox.question = previous_question
            assert window.isVisible(), "native close did not protect unsaved progress"
            js("Array.from(document.querySelectorAll('nav button')).find(b=>b.textContent.trim()==='규칙')?.click()")
            stage = 8
        elif stage == 8 and "현황에 저장하지 않은 변경" in text:
            js("Array.from(document.querySelectorAll('nav button')).find(b=>b.textContent.trim()==='프로젝트 현황')?.click()")
            stage = 9
        elif stage == 9 and "과거 기능 편집 보존" in text:
            assert data.get("title") == "과거 기능 편집 보존"
            assert window.bridge.progress_dirty
            window.grab().save(str(root / "session-preserved.png"))
            js("Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()==='기준과 근거 저장')?.click()")
            stage = 10
        elif stage == 10 and not window.bridge.progress_dirty and f"요구사항 v{initial_saved['version'] + 1}" in text:
            assert data.get("title") == "과거 기능 편집 보존"
            assert "응답 형식이 올바르지" not in text
            assert data["saveDisabled"] is False
            result.update({"passed": True, "cards_toggled": 4, "excluded_links": False, "excluded_hints": False,
                "test_picker_cancelled_without_lock": True, "page_navigation_preserves_unsaved_title": True,
                "native_close_cancel_protects_edit": True, "native_dirty_cleared_after_save": True,
                "saved_version": initial_saved["version"] + 1})
            fixture = json.loads((PROJECT / "desktop-ui/src/preview-fixture.json").read_text(encoding="utf-8"))
            window.bridge.emit("scanned", scan=fixture)
            js("Array.from(document.querySelectorAll('nav button')).find(b=>b.textContent.trim()==='리뷰')?.click()")
            stage = 11
        elif stage == 11 and data.get("diffReady"):
            assert "이 화면을 표시하지 못했습니다" not in text
            assert "응답 형식이 올바르지" not in text
            result["lazy_diff_renders_in_qt"] = True
            window.grab().save(str(root / "lazy-diff.png"))
            (root / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print("Qt session smoke passed: edit/navigation/close/save and lazy rich diff all work")
            app.quit()
            return
        if tries > 100:
            raise AssertionError(f"UI timeout at stage {stage}: {data}")
    except Exception as exc:
        print(f"stage {stage}: {exc!r}; data={data}", file=sys.stderr)
        app.exit(1)
        return
    QTimer.singleShot(250, inspect)

QTimer.singleShot(750, inspect)
sys.exit(app.exec())
