# Cross Agent 데스크톱 UI 개편

## 기준 화면과 실제 사용한 구성 요소

사용자가 제공한 [Cross Agent Desktop UI](https://claude.ai/artifact/8viDYBBjEcMRGt2LWmETuS)의 시작·리뷰·규칙·히스토리·설정 화면을 브라우저에서 확인했다. 배경 `#F6F4EF`, 사이드바 `#1E1D1B`, 강조 `#2F6F5E`, 카드 반경 12px을 반영했다. 브랜드 표기는 Cross Agent, 검사 엔진 표기는 Drift Gate로 구분한다.

[assistant-ui/tool-ui](https://github.com/assistant-ui/tool-ui)의 React 소스를 실제 복사해 사용했다. 원본 커밋은 `desktop-ui/tool-ui-provenance.json`, MIT 고지는 `desktop-ui/TOOL-UI-LICENSE.md`에 보존했다. 원본 저장소는 확인 시 archived 상태여서 런타임 CDN 연결 없이 고정된 소스와 lockfile을 사용한다.

| 원본 컴포넌트 | 앱에서 쓰이는 위치 | 실제 데이터/동작 |
|---|---|---|
| StatsDisplay | 검사 결과 요약 | 변경 파일, 평가 규칙, 조치 항목, 통과 규칙 |
| ProgressTracker | 규칙 검사 및 LLM 요청 중 | 실제 시작·완료·오류 이벤트 |
| OptionList | 설정·전송 확인 창 | ChatGPT / Claude 구독 CLI 선택 |
| ApprovalCard | LLM 전송 확인 | 직접 확인한 후 요청, 취소 시 전송 안 함 |
| CodeDiff | 코드 변경 근거 | Git unified diff, 파일 선택, 줄별 추가·삭제 |

Vite 대응 변경은 OptionList의 환경 변수 표기와 CodeDiff의 과거 Turbopack 전용 비공개 테마 레지스트리 제거다. 패치 전체에 Git 헤더가 있으면 그대로 전달하고, hunk만 있는 입력에는 헤더를 붙인다. 스타일은 애플리케이션 공통 토큰에서 덮어쓴다.

## 스킬 실행 범위

- **UI UX Pro Max**: 이전 디자인 시스템 생성·재검색을 수행했고, 이번에는 `keyboard focus modal --domain ux`, `loading error feedback --stack react`를 실제 실행했다. 사용자 시안의 명시적 디자인 토큰을 우선 적용했다. 키보드 포커스, 네이티브 dialog, 비동기 오류 안내, 영역별 오류 경계, reduced-motion 처리를 반영했다.
- **CC AI Toolkit**: 원본 커맨드 설치와 컴포넌트 조사까지 진행했다. 이번 입력은 Claude 아티팩트이며 Figma URL/Variables/MCP 입력이 아니므로 Figma 가져오기와 토큰 동기화를 실행했다고 주장하지 않는다. 사용자 시안을 기준으로 구현을 계속했으며 이 부분은 Figma 스킬 완료 실적이 아니다.

## 구조

```text
Qt 데스크톱 창
└─ 로컬 React 화면 (외부 CDN 없음)
   ├─ 사이드바: 리뷰 / 규칙 / 히스토리 / 설정
   ├─ 리뷰: 저장소 선택 → 규칙 검사 → 목록/근거/diff → LLM 추가 검토
   ├─ 규칙: 검사 시점 정책 원문
   ├─ 히스토리: 세션 내 최근 20개 검사 스냅샷
   └─ 설정: 구독 CLI 선택·경로·전송 범위
      ↕ Qt WebChannel
Python 검사 서비스 / 공식 Codex·Claude Code CLI / HTML·JSON 저장
```

Python 검사 서비스와 gate 판정 규칙은 유지한다. 화면의 직접 네트워크 요청과 외부 페이지 이동은 차단하고, 번들에 포함된 로컬 화면만 Python 연결을 사용한다. LLM 호출은 전송 미리보기의 확인 버튼으로 시작한다.

## 시안과 구분한 범위

- 히스토리는 **현재 앱 세션 내 기록**이다. 영구 저장·실제 운영 통계를 가장하지 않는다.
- 규칙 화면은 **검사 시점 원문 조회**다. 규칙 편집은 저장소 파일에서 진행한다.
- 트레이 상주, 자동 업데이트, API 키 보안 저장 UI, 개별 항목 무시는 이번 범위에 포함하지 않았다.
- 연결 방식은 공식 구독 CLI이며 API 키 입력 창을 임의로 추가하지 않았다. 기존 API 기반 CLI 사용은 그대로다.
- 브라우저 미리보기는 실제 파일 접근이 없다. 앱 연결 상태와 구분해 표시한다.
- 합성 사례 전용 `preview.html`은 개발 시각 검증용이며 배포 빌드의 시작 페이지에 포함하지 않는다.

## 검증

합성 Git 저장소에서 코드 `GET /members`, 문서 `GET /customers` 변경을 만들고 실제 데스크톱 버튼으로 검사했다. 규칙 엔진은 fail, 변경 파일 2개, 조치 항목 1개로 판정했다. 이는 UI 연결 검증이며 일반 정확도 측정이 아니다.

자동 검증: Python 562개, React 상호작용 5개 통과. TypeScript 빌드와 Ruff 주요 오류 검사를 통과했다. 실제 화면에서 검사·필터·diff·설정·전송 미리보기를 확인한다. [Windows·macOS 패키지 빌드](https://github.com/cres17/pr-convention-checker/actions/runs/36536161858)가 모두 통과했다. 실제 Windows 사용자 PC 실행은 아직 확인하지 않았다.

![실제 합성 저장소 검사 화면](../assets/cross-agent-desktop.png)
