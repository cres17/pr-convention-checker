# 데스크톱 앱 CI (`desktop-build.yml`)

`ver2` 브랜치에 `drift_gate/**`, `desktop-ui/**`, `pyproject.toml`, 워크플로 파일이 바뀐 push가 들어오면 실행됩니다. 수동 실행(`workflow_dispatch`)도 가능합니다.

## 무엇을 하는가

macOS Apple Silicon(`macos-latest`), macOS Intel(`macos-15-intel`), Windows(`windows-latest`) 세 곳에서 각각 다음을 순서대로 실행합니다. 한쪽이 실패해도 다른 쪽은 계속 실행합니다(`fail-fast: false`).

1. **React UI**: `desktop-ui`에서 `npm ci` → `npm test`(vitest) → `npm run build`. 빌드 결과는 `drift_gate/desktop/web`에 만들어지며 저장소에는 포함하지 않습니다.
2. **앱 설치**: `pip install -e ".[dev,desktop]" pyinstaller`.
3. **데스크톱 동작 검사**: 아래 테스트 파일만 실행합니다. 전체 테스트가 아니라 **데스크톱 앱과 프로젝트 현황이 쓰는 파일**로 범위를 제한했습니다.
   - `test_desktop_service.py`, `test_desktop_ui.py`, `test_desktop_web.py`, `test_subscription_review.py`
   - `test_progress_service.py`, `test_progress_history.py`, `test_progress_report.py`
   - `test_doc_links.py`, `test_verification_records.py`, `test_policy_setup.py`, `test_report_naming.py`
4. **앱 빌드와 확인**: PyInstaller로 `DriftGate` 앱을 만든 뒤 실행 파일과 번들된 UI가 있는지 확인하고, 앱을 화면 없이(offscreen) 12초간 실행해 시작 직후 종료하지 않는지 봅니다(`packaging/smoke_launch.py`).
5. **배포 파일 만들기**:
   - macOS: 앱을 임시 서명(ad-hoc, 개발자 인증서 없음)한 뒤 `Applications` 바로가기가 든 **`.dmg`**를 만듭니다(`DriftGate-macOS-arm64.dmg`, `DriftGate-macOS-intel.dmg`). 만든 `.dmg`를 마운트해 앱이 들어 있는지 확인합니다.
   - Windows: Inno Setup(`packaging/windows/DriftGate.iss`)으로 **`DriftGate-Windows-Setup.exe`** 설치 프로그램을, 설치 없이 쓰는 `DriftGate-Windows-portable.zip`도 만듭니다. CI에서 설치 프로그램을 조용히 설치해 앱이 시작되는지 확인하고 제거합니다. 설치는 기본적으로 현재 사용자 영역이라 관리자 권한이 필요 없습니다.
6. 결과를 아티팩트로 올립니다. 서명·공증은 하지 않습니다.

새 데스크톱 기능의 테스트 파일을 추가하면 **3번의 목록에도 추가해야** 두 OS에서 실행됩니다. 목록에 없는 파일은 이 워크플로에서 실행되지 않습니다.

## 푸시·PR 실행

`ver2`로 향하는 push와 pull request(위 경로가 바뀐 경우)에서 실행됩니다. 이 워크플로는 다른 워크플로가 재사용할 수도 있습니다(`workflow_call`). 권한은 읽기 전용(`contents: read`)입니다. 만든 파일은 아티팩트(`DriftGate-macOS-arm64`, `DriftGate-macOS-intel`, `DriftGate-Windows`)로 14일간 보관합니다. 빌드 뒤에는 실행 파일과 번들된 React UI(`drift_gate/desktop/web/index.html`)가 패키지 안에 있는지도 확인합니다.

## 릴리스 (`desktop-release.yml`)

데스크톱 앱 릴리스는 **`desktop-v*` 태그**를 씁니다. 기존 `v1`, `v1.0.0` 태그는 GitHub Action 배포용이라 겹치지 않게 분리했습니다.

```bash
git tag desktop-v0.2.0 && git push origin desktop-v0.2.0
```

또는 Actions 탭에서 **Desktop release**를 수동 실행하고 태그를 입력합니다(`dry_run`을 켜면 릴리스 없이 빌드·검사·파일 준비까지만 확인합니다).

1. 빌드 전에 태그 형식(`desktop-vX.Y.Z` 또는 `-rc.1` 같은 접미사)을 확인합니다. 릴리스가 이미 있으면 빌드·업로드를 생략합니다. 게시할 때 생성되는 태그의 push로 중복 빌드되는 것을 막습니다.
2. `desktop-build.yml`을 호출해 두 OS에서 테스트와 빌드를 실행합니다. 실패하면 릴리스를 만들지 않습니다. 업로드 직전에 중복 여부를 한 번 더 확인합니다.
3. `.dmg` 2개, Windows `Setup.exe`, 포터블 zip과 `SHA256SUMS.txt`를 모아 **초안(draft) 릴리스**로 만듭니다. 초안이라 Releases 페이지에서 내용을 확인하고 직접 게시해야 공개됩니다. 수동 실행으로 만든 경우 태그는 게시할 때 그 실행의 커밋에 생성됩니다.

빌드 결과의 성격:

- macOS는 CPU마다 별도 파일입니다. `macos-latest`(Apple Silicon, arm64)에서 만든 `.dmg`는 Intel Mac에서, `macos-15-intel`에서 만든 `.dmg`는 Apple Silicon에서 쓰지 않습니다(Intel 빌드는 Rosetta로 돌아갈 수 있으나 검증하지 않았습니다). 하나로 합친 universal 빌드는 아닙니다.
- **서명·공증을 하지 않았습니다.** macOS는 Gatekeeper, Windows는 SmartScreen 경고가 나옵니다. 서명하려면 Apple Developer 인증서와 Windows 코드 서명 인증서를 저장소 시크릿으로 등록하고 워크플로에 서명 단계를 추가해야 합니다. 현재는 없습니다.
- 자동 업데이트는 없습니다. Windows 설치 프로그램은 같은 앱 ID로 만들어져 새 버전을 덮어 설치하면 업그레이드됩니다.

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

- 이 워크플로는 테스트 통과, 앱 실행 시작, DMG 생성·마운트, Windows 설치 프로그램의 설치·실행 시작·제거 단계를 확인합니다. 전체 기능, 자동 업데이트, 공식 코드 서명·Apple 공증, 실제 사용자 PC에서의 실행은 검증하지 않습니다. Windows 제거 단계는 제거 프로그램 실행까지 확인하며, 모든 파일·설정의 제거 여부를 별도로 비교하지는 않습니다.


## 2026-10-01 게시한 설치 파일

현재 공개 미리보기는 [desktop-v1.0.1-preview.20261001](https://github.com/cres17/pr-convention-checker/releases/tag/desktop-v1.0.1-preview.20261001)이다. 제품 커밋은 `6445879`이며, [릴리스 워크플로 36804667492](https://github.com/cres17/pr-convention-checker/actions/runs/36804667492)의 세 플랫폼 빌드와 게시 준비가 성공했다. 각 플랫폼에서 화면 27개·데스크톱 126개 검사를 통과하고 패키지 실행 시작을 확인했다. DMG 두 개의 마운트와 Windows 설치·실행 시작·제거도 통과했다.

문서 종류와 V5·V6·V7, 현황 편집 보존 수정이 포함됐다. 과거 1.0.0 미리보기는 그대로 보존하며 README의 고정 다운로드 링크는 1.0.1로 갱신했다. 일반 CI는 Qt 없이 9개 OS·Python 조합에서 각각 646개 통과·3개 건너뜀이다. 전체 Qt 포함 로컬 검사는 668개로 검사 환경과 범위가 다르다.

Benchmark는 수동 실행도 지원한다. Action 릴리스의 평가 보고서 첨부에는 `contents: write`가 필요하며, 데스크톱 릴리스는 설치 파일과 체크섬만 제공하고 평가 원본은 Actions 아티팩트·문서에 둔다.
