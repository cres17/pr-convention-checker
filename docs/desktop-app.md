# Drift Gate 데스크톱 앱

명령어 없이 **로컬 Git 저장소를 선택하고 규칙별 판정을 읽는** 첫 버전입니다. Windows와 macOS에서 같은 화면을 사용합니다. 기존 Python 정책 엔진을 그대로 호출하므로 CLI 및 GitHub Actions와 판정 기준이 같습니다.

## 사용 흐름

1. `.drift-gate.yml`이 있는 Git 저장소 폴더를 선택합니다.
2. 비교 기준을 입력합니다. `HEAD`는 마지막 커밋 이후의 작업 트리 변경, `main`은 해당 브랜치 이후의 변경을 비교합니다.
3. **검사 시작**을 누르고 통과·경고·실패와 규칙별 근거를 확인합니다. 필요한 경우 HTML 또는 JSON 보고서를 저장합니다.

검사 자체는 읽기 전용입니다. 새로 만든 파일은 Git에 추가해야 diff에 포함됩니다. 현재 화면은 **로컬 저장소 검사**를 지원합니다. GitHub PR 검사는 기존 CLI나 Action을 사용하세요.

## 실행

Python 3.10 이상과 Git이 필요합니다. 프로젝트 루트에서 다음을 실행합니다.

```bash
python -m pip install -e '.[desktop]'
drift-gate-desktop
```

Windows PowerShell에서도 설치 명령은 같으며, Python 실행 명령이 `py`라면 `py -m pip install -e '.[desktop]'`를 사용합니다. 정책 파일이 없다면 먼저 `drift-gate init --preset api`로 만들고 프로젝트 경로에 맞게 수정하세요.

## 독립 실행 앱 만들기

[Desktop app build](../.github/workflows/desktop-build.yml) 워크플로를 수동 실행하면 운영체제별 압축 파일을 CI 실행 결과의 아티팩트로 보관합니다. macOS 아티팩트는 `.app`, Windows 아티팩트는 `.exe`와 필요한 파일이 든 폴더입니다. 각 운영체제에서 별도로 빌드합니다. 실행 대상 컴퓨터에도 **Git은 설치되어 있어야** 합니다.

로컬에서 빌드할 때는 다음 명령을 사용할 수 있습니다.

```bash
python -m pip install -e '.[desktop]' pyinstaller
pyinstaller --noconfirm --clean --windowed --onedir --name DriftGate --collect-all tree_sitter_language_pack drift_gate/desktop/app.py
```

현재 macOS에서는 앱 번들 생성과 실행 시작을 확인했습니다. Windows 패키지의 실행 및 서명·공증, 설치 프로그램, 자동 업데이트는 아직 검증하지 않았습니다. 서명되지 않은 개발 빌드는 OS 보안 안내가 표시될 수 있습니다.

## 화면에서 읽는 방법

상단은 **현재 판정과 비교 기준**, 가운데는 **변경 파일·평가된 규칙·차단 항목**입니다. 아래 목록의 각 규칙을 선택하면 변경 파일, 필요한 문서, 엔진 근거를 볼 수 있습니다. `통과`는 **설정된 정책을 이 입력에서 충족했다**는 뜻이며 코드와 문서의 모든 의미가 같다는 보장은 아닙니다.
