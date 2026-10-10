# 최신 작업 트리 설치본 검증

2026-10-06. 운영 코드와 첫 번째·두 번째 리뷰 수정이 함께 들어간 작업 트리를 새로 빌드했다. 이전 설치본이나 소스 앱을 재사용하지 않았다. 소스 해시는 `local-validation.json`에 있다.

로컬 macOS arm64에서 세 경로 모두 통과했다.

1. PyInstaller 6.22.3으로 만든 frozen `.app`.
2. 새 DMG를 읽기 전용으로 마운트한 앱.
3. DMG의 앱을 임시 설치 위치로 복사한 뒤 실행한 앱. 기존 `/Applications` 설치는 교체하지 않았다.

각 경로에서 별도의 빈 캐시와 외부 통신 차단을 사용했다. 실제 렌더링된 UI, QWebChannel, 문서 누락 정책 warn, Python/TypeScript/TSX/JavaScript/Go/Java/Kotlin/Ruby의 `grammar+heuristic` 분석 8개, 앱 안에서 외부 IP 접속 차단 2개, 파서 캐시 파일 0개를 확인했다. 설치 후에도 deep/strict 코드 서명 검증을 통과했다. 서명은 ad-hoc이며 Developer ID 서명·공증이나 Gatekeeper의 다운로드 설치 허용을 검증한 것은 아니다.

검사 입력은 합성 Git 저장소다. 실제 PR 판정 정확도나 이번 편집 기능 전부의 설치본 E2E 시험을 뜻하지 않는다. 편집 기능의 macOS 소스 앱 10개 확인은 `architecture-second-fixes-2026-10-06` 자료와 구분한다.

`offline-*/result.json`은 앱이 실제로 만든 검사 결과이고, `bundled-grammars.json`은 번들 라이브러리 해시다. DMG·앱·빌드 로그는 Git 이력에 넣지 않고 로컬 `build/review-package-2026-10-06/`에 보관한다.

원격 검증은 이 자료를 포함한 커밋을 ver2에 푸시한 뒤 CI와 Desktop app build를 기다리고, 같은 소스 커밋의 세 플랫폼 `Offline-check-*` 산출물을 내려받아 결과 JSON을 점검하는 단계다. 해당 실행 URL과 완료 결과는 이 대화의 최종 보고 및 GitHub Actions에서 확인한다. 소스와 같은 커밋의 빌드·검사 결과인지 반드시 확인한다.
