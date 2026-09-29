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

## 푸시·PR 실행

`ver2`로 향하는 push와 pull request(위 경로가 바뀐 경우)에서 실행됩니다. 이 워크플로는 다른 워크플로가 재사용할 수도 있습니다(`workflow_call`). 권한은 읽기 전용(`contents: read`)입니다. 만든 앱은 아티팩트(`DriftGate-macOS`, `DriftGate-Windows`)로 14일간 보관합니다. 빌드 뒤에는 실행 파일과 번들된 React UI(`drift_gate/desktop/web/index.html`)가 패키지 안에 있는지도 확인합니다.

## 릴리스 (`desktop-release.yml`)

데스크톱 앱 릴리스는 **`desktop-v*` 태그**를 씁니다. 기존 `v1`, `v1.0.0` 태그는 GitHub Action 배포용이라 겹치지 않게 분리했습니다.

```bash
git tag desktop-v0.2.0 && git push origin desktop-v0.2.0
```

또는 Actions 탭에서 **Desktop release**를 수동 실행하고 태그를 입력합니다(`dry_run`을 켜면 릴리스 없이 빌드·검사·파일 준비까지만 확인합니다).

1. `desktop-build.yml`을 그대로 호출해 두 OS에서 테스트와 빌드를 실행합니다. 실패하면 릴리스를 만들지 않습니다.
2. 태그 형식(`desktop-vX.Y.Z` 또는 `-rc.1` 같은 접미사)과 같은 태그의 릴리스가 이미 없는지 확인합니다.
3. 두 앱의 zip과 `SHA256SUMS.txt`를 모아 **초안(draft) 릴리스**로 만듭니다. 초안이라 Releases 페이지에서 내용을 확인하고 직접 게시해야 공개됩니다. 수동 실행으로 만든 경우 태그는 게시할 때 그 실행의 커밋에 생성됩니다.

빌드 결과의 성격:

- macOS 빌드는 `macos-latest` 러너(Apple Silicon, arm64)에서 만들어 **Intel Mac에서는 실행되지 않습니다**.
- **서명·공증을 하지 않았습니다.** macOS는 Gatekeeper, Windows는 SmartScreen 경고가 나옵니다. 서명하려면 Apple Developer 인증서와 Windows 코드 서명 인증서를 저장소 시크릿으로 등록하고 워크플로에 서명 단계를 추가해야 합니다. 현재는 없습니다.
- 자동 업데이트와 설치 프로그램(`.msi`, `.dmg`)은 없습니다. zip을 풀어 실행합니다.

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
