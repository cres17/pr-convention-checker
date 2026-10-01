# 초안 복구 검증 원본

기준 커밋 `637fe13` 이후 수정, Python 3.11.15·PySide6 6.11.2·macOS Qt offscreen.

- `results.json`: 검사 수·린트 전후·릴리스 태그.
- `lint-before.log`: 전체 F 35건(테스트 28건 + 코드 7건). 이후 같은 범위는 0건.
- `python-all.log`, `ui-final.log`, `build-final.log`, `lint-after.log`: 검사 결과.
- `native-restart.py`: 실제 Qt 앱을 새 프로세스로 실행하는 입력.
- `native.log`, `native-edit.json`, `native-recover.json`, `native-confirm.json`: 3개 서로 다른 PID와 각 단계의 성공 결과.

현재 UI를 빌드한 뒤 같은 임시 폴더를 전달해 순서대로 실행한다. `edit`에서 생성하므로 처음에는 존재하지 않는 폴더를 선택한다. 실제 사용자 설정·저장소는 사용하지 않는다.

```bash
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu python docs/assessment/progress-draft-recovery-2026-10-01/native-restart.py edit /tmp/driftgate-restart-check
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu python docs/assessment/progress-draft-recovery-2026-10-01/native-restart.py recover /tmp/driftgate-restart-check
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu python docs/assessment/progress-draft-recovery-2026-10-01/native-restart.py confirm /tmp/driftgate-restart-check
```
