# 데스크톱 앱 CI (`desktop-build.yml`)

`ver2` 브랜치에 `drift_gate/**`, `desktop-ui/**`, `pyproject.toml`, 워크플로 파일이 바뀐 push가 들어오면 실행됩니다. 수동 실행(`workflow_dispatch`)도 가능합니다.

## 무엇을 하는가

macOS(`macos-latest`)와 Windows(`windows-latest`) 두 곳에서 각각 다음을 순서대로 실행합니다. 한쪽이 실패해도 다른 쪽은 계속 실행합니다(`fail-fast: false`).

1. **React UI**: `desktop-ui`에서 `npm ci` → `npm test`(vitest) → `npm run build`. 빌드 결과는 `drift_gate/desktop/web`에 만들어지며 저장소에는 포함하지 않습니다.
2. **앱 설치**: `pip install -e ".[dev,desktop]" pyinstaller`.
3. **데스크톱 동작 검사**: 아래 테스트 파일만 실행합니다. 전체 테스트가 아니라 **데스크톱 앱과 프로젝트 현황이 쓰는 파일**로 범위를 제한했습니다.
   - `test_desktop_service.py`, `test_desktop_ui.py`, `test_desktop_web.py`, `test_subscription_review.py`
   - `test_progress_service.py`, `test_progress_history.py`, `test_progress_report.py`
   - `test_doc_links.py`, `test_verification_records.py`, `test_policy_setup.py`, `test_report_naming.py`
4. **앱 빌드**: PyInstaller로 `DriftGate` 앱을 만들고 macOS는 `.zip`(ditto), Windows는 `.zip`(Compress-Archive)으로 묶어 아티팩트로 올립니다. 서명·공증은 하지 않습니다.

새 데스크톱 기능의 테스트 파일을 추가하면 **3번의 목록에도 추가해야** 두 OS에서 실행됩니다. 목록에 없는 파일은 이 워크플로에서 실행되지 않습니다.

## 로컬에서 같은 검사를 실행하려면

```bash
pip install -e '.[dev,desktop]'
cd desktop-ui && npm ci && npx tsc --noEmit && npx vitest run && npm run build && cd ..
QT_QPA_PLATFORM=offscreen python -m pytest -q drift_gate/tests/test_desktop_service.py \
  drift_gate/tests/test_desktop_ui.py drift_gate/tests/test_desktop_web.py \
  drift_gate/tests/test_subscription_review.py drift_gate/tests/test_progress_service.py \
  drift_gate/tests/test_progress_history.py drift_gate/tests/test_progress_report.py \
  drift_gate/tests/test_doc_links.py drift_gate/tests/test_verification_records.py \
  drift_gate/tests/test_policy_setup.py drift_gate/tests/test_report_naming.py
```

Linux 컨테이너에서 `libEGL.so.1`을 찾지 못해 Qt WebEngine 테스트가 실패하면 `apt-get update` 후 `apt-get install libegl1`을 실행합니다(패키지 목록이 오래되면 설치가 404로 실패할 수 있습니다). `QT_QPA_PLATFORM=offscreen`이면 화면 없이 실행됩니다.

## 알려진 한계

- 이 워크플로는 앱이 **시작되고 테스트가 통과하는 것**까지만 확인합니다. 설치 프로그램, 자동 업데이트, 서명·공증, 실제 사용자 PC에서의 실행은 검증하지 않습니다.
- Windows와 macOS에서 새로 추가한 테스트가 통과하는지는 이 워크플로를 실행해 봐야 알 수 있습니다.
