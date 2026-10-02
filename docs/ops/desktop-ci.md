# 데스크톱 앱 CI (`desktop-build.yml`)

`ver2` 브랜치에 `drift_gate/**`, `desktop-ui/**`, `packaging/**`, `pyproject.toml`, 워크플로 파일이 바뀐 push가 들어오면 실행됩니다. 수동 실행(`workflow_dispatch`)도 가능합니다.

## 무엇을 하는가

macOS Apple Silicon(`macos-latest`), macOS Intel(`macos-15-intel`), Windows(`windows-latest`) 세 곳에서 각각 다음을 순서대로 실행합니다. 한쪽이 실패해도 다른 쪽은 계속 실행합니다(`fail-fast: false`).

1. **React UI**: `desktop-ui`에서 `npm ci` → `npm test`(vitest) → `npm run build`. 빌드 결과는 `drift_gate/desktop/web`에 만들어지며 저장소에는 포함하지 않습니다.
2. **앱 설치·파서 준비**: `pip install -e ".[dev,desktop]" pyinstaller==6.22.3 zstandard==0.25.0` 후 `packaging/prepare_parsers.py`로 Python·TypeScript·TSX·JavaScript·Go·Java·Kotlin·Ruby 파서를 내려받아 `build/parser-libraries`에 준비합니다. 언어팩 버전·OS·아키텍처별 캐시를 쓰며 다운로드 실패는 두 번 재시도하고 최종 실패하면 빌드를 중단합니다. 검토한 네 플랫폼의 원본 해시를 `parser_hashes.json`에 고정하고 모든 파일을 비교한 뒤에만 파서를 로드합니다. 고정값 없는 버전·플랫폼 및 해시 불일치는 빌드를 중단합니다. 빌드에만 인터넷이 필요합니다.
3. **데스크톱 동작 검사**: 아래 테스트 파일만 실행합니다. 전체 테스트가 아니라 **데스크톱 앱과 프로젝트 현황이 쓰는 파일**로 범위를 제한했습니다.
   - `test_desktop_service.py`, `test_desktop_ui.py`, `test_desktop_web.py`, `test_subscription_review.py`
   - `test_progress_service.py`, `test_progress_drafts.py`, `test_progress_history.py`, `test_progress_report.py`
   - `test_doc_links.py`, `test_verification_records.py`, `test_policy_setup.py`, `test_report_naming.py`, `test_packaging.py`
4. **앱 빌드와 실제 오프라인 검사**: UI와 8개 파서, 원본 고정값 파일을 PyInstaller 설치본에 함께 넣습니다. macOS는 네이티브 파일 서명 후 `seal_parsers.py`로 설치본 해시를 기록하고 외부 번들만 다시 서명합니다. Windows는 패키징 후 설치본 해시를 기록합니다. 앱의 첫 문법 조회에서 원본 고정값과 실제 설치 파일 해시를 확인합니다. macOS Qt 프레임워크의 Versions 부모 디렉터리는 읽기 전용으로 두어 실행이 빈 가짜 버전 폴더를 만들지 못하게 합니다. 실제 오프라인 검사 직후에도 엄격한 중첩 서명 검사를 반복합니다. `packaging/verify_package.py`는 파서 포함 여부를 확인하고, 빈 사용자 파서 캐시와 OS의 송신 차단 상태에서 설치본을 실행합니다. Mac은 `sandbox-exec`, Windows는 앱과 Qt WebEngine 실행 파일에 임시 Windows Defender Firewall 규칙을 적용하며 검사 후 제거하고 Windows job 종료에서도 남은 CI 전용 규칙을 정리합니다. 방화벽 변경은 GitHub CI에서만 허용합니다. 실제 React 화면·QWebChannel 연결, 8개 언어의 `grammar+heuristic` 분석, API 문서 누락의 `warn` 판정까지 확인합니다. 연결 차단도 앱 안에서 확인하며, 화면·분석이 끝나지 않거나 휴리스틱으로 내려가면 실패합니다.
5. **배포 파일 만들기**:
   - macOS: 앱을 임시 서명(ad-hoc, 개발자 인증서 없음)한 뒤 `Applications` 바로가기가 든 **`.dmg`**를 만듭니다(`DriftGate-macOS-arm64.dmg`, `DriftGate-macOS-intel.dmg`). DMG 안의 앱에서도 새 빈 캐시와 네트워크 차단으로 같은 실제 검사를 반복합니다.
   - Windows: Inno Setup(`packaging/windows/DriftGate.iss`)으로 **`DriftGate-Windows-Setup.exe`** 설치 프로그램을, 설치 없이 쓰는 `DriftGate-Windows-portable.zip`도 만듭니다. CI에서 설치 프로그램을 조용히 설치해 설치된 앱에서 같은 오프라인 검사를 수행하고 제거합니다. 앱 설치는 현재 사용자 영역이며 관리자 권한이 필요 없지만, **CI 검증용 방화벽 규칙에는 관리자 권한이 필요합니다.**
6. 설치 파일과 `Offline-check-*` 검증 아티팩트를 올립니다. 후자는 결과 JSON·화면 캡처·앱 로그·파서 목록을 포함하며 실패한 실행도 남깁니다. 공식 인증서 서명·공증은 하지 않습니다.

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
  drift_gate/tests/test_progress_drafts.py \
  drift_gate/tests/test_progress_history.py drift_gate/tests/test_progress_report.py \
  drift_gate/tests/test_doc_links.py drift_gate/tests/test_verification_records.py \
  drift_gate/tests/test_policy_setup.py drift_gate/tests/test_report_naming.py \
  drift_gate/tests/test_packaging.py
```

Linux 컨테이너에서 `libEGL.so.1`을 찾지 못해 Qt WebEngine 테스트가 실패하면 `apt-get update` 후 `apt-get install libegl1`을 실행합니다(패키지 목록이 오래되면 설치가 404로 실패할 수 있습니다). `QT_QPA_PLATFORM=offscreen`이면 화면 없이 실행됩니다.

## 알려진 한계

- 이 워크플로는 고정 합성 저장소의 화면 로드·8개 언어 문법 분석·문서 누락 판정과 DMG·설치 프로그램에서의 동일 동작을 확인합니다. 전체 기능, 실제 프로젝트 판정 정확도, 자동 업데이트, 공식 코드 서명·Apple 공증, 실제 사용자 PC의 모든 환경은 검증하지 않습니다. Windows 제거 단계는 제거 프로그램 실행까지 확인하며, 모든 파일·설정의 제거 여부를 별도로 비교하지는 않습니다.


## 2026-10-01 1.0.2 미리보기

이 공개본의 기존 검사는 프로세스 생존만 확인했다. 후속 확인에서 화면 파일 경로 불일치와 언어별 파서 미포함을 발견했다. 위의 강화한 검사는 다음 빌드부터 적용하며 기존 공개 설치 파일을 자동으로 교체하지 않는다. [수정과 오프라인 검증](../review/offline-packaged-analysis-2026-10-01.md)을 참고한다.

현재 공개본은 [desktop-v1.0.2-preview.20261001](https://github.com/cres17/pr-convention-checker/releases/tag/desktop-v1.0.2-preview.20261001), 제품 소스 `916c4ba`다. [릴리스 실행 36832261072](https://github.com/cres17/pr-convention-checker/actions/runs/36832261072)의 세 플랫폼에서 화면 77개·데스크톱 151개 검사, 앱 실행, 두 DMG 마운트와 Windows 설치·실행·제거가 성공했다. 초안에서 네 설치 파일을 전체 다운로드해 체크섬·GitHub digest와 대조하고, 게시 후 공개 주소의 HTTP 200·크기를 확인했다. [검증 원본](../assessment/progress-draft-recovery-2026-10-01/release-downloads.json)을 보존한다. 일반 CI는 9개 조합에서 각각 664개 통과·3개 건너뜀이며 Qt 포함 로컬 693개와 범위가 다르다. CI는 이제 Ruff `E9,F` 전체를 검사한다.

## 2026-10-01 게시한 설치 파일

이전 1.0.1 미리보기는 [desktop-v1.0.1-preview.20261001](https://github.com/cres17/pr-convention-checker/releases/tag/desktop-v1.0.1-preview.20261001)이다. 제품 커밋은 `6445879`이며, [릴리스 워크플로 36804667492](https://github.com/cres17/pr-convention-checker/actions/runs/36804667492)의 세 플랫폼 빌드와 게시 준비가 성공했다. 각 플랫폼에서 화면 27개·데스크톱 126개 검사를 통과하고 패키지 실행 시작을 확인했다. DMG 두 개의 마운트와 Windows 설치·실행 시작·제거도 통과했다.

문서 종류와 V5·V6·V7, 현황 편집 보존 수정이 포함됐다. 과거 1.0.0 미리보기는 그대로 보존하며 README의 고정 다운로드 링크는 1.0.1로 갱신했다. 일반 CI는 Qt 없이 9개 OS·Python 조합에서 각각 646개 통과·3개 건너뜀이다. 전체 Qt 포함 로컬 검사는 668개로 검사 환경과 범위가 다르다.

Benchmark는 수동 실행도 지원한다. Action 릴리스의 평가 보고서 첨부에는 `contents: write`가 필요하며, 데스크톱 릴리스는 설치 파일과 체크섬만 제공하고 평가 원본은 Actions 아티팩트·문서에 둔다.

기존 공개 태그로 수정 워크플로를 실행한 [36805844364](https://github.com/cres17/pr-convention-checker/actions/runs/36805844364)는 사전 검사만 실행하고 앱 빌드·업로드 없이 성공했다. [Benchmark 36805846668](https://github.com/cres17/pr-convention-checker/actions/runs/36805846668)도 성공했다. Action 릴리스의 실제 보고서 업로드는 이 수동 검증에 포함되지 않는다.

## 파서 버전 변경 시

`Collect parser hash candidates` 워크플로는 macOS 두 CPU·Windows·Linux에서 원본 파일을 로드하지 않고 해시 후보를 만듭니다. `ver2`의 수집 스크립트 또는 워크플로 변경으로 실행합니다. 후보가 고정값을 자동 갱신하지 않으며, 기존 기록과 대조·검토 후 `drift_gate/adapters/parser_hashes.json`의 버전·플랫폼별 값을 명시적으로 변경합니다. [2026-10-02 검토 기록](../review/parser-integrity-2026-10-02.md)에 신뢰 범위와 출처를 기록했습니다.
