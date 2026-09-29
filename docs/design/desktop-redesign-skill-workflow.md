# 데스크톱 UI 전면 개편 — 스킬 실행 기록

## 요청과 현재 상태

사용자가 지정한 두 저장소의 스킬을 실제 사용한다. 기존 PySide6 데스크톱 앱과 구독 CLI 연결을 유지하며 UI를 다시 설계한다. 현재는 스킬 설치·요구사항 분석 단계이며, 화면 개편 완료 상태가 아니다.

## 1. UI UX Pro Max

- 원본: https://github.com/nextlevelbuilder/ui-ux-pro-max-skill
- 설치: `/Users/moon/.codex/skills/ui-ux-pro-max/SKILL.md`
- 실제 실행: `scripts/search.py 'developer review desktop dashboard' --design-system -p 'Drift Gate' -f markdown`
- 결과 검토: FAQ 랜딩 페이지 구조가 반환되어 데스크톱 검사 도구의 정보 구조로 채택하지 않음.
- 지침에 따른 한 번의 재검색: `scripts/search.py 'code review dashboard' --design-system -p 'Drift Gate' -f markdown`
- 결과 검토: Minimalism & Swiss Style과 대시보드용 타이포그래피는 적합. Hero + Features + CTA 랜딩 구조와 별점 리뷰용 골드 색상은 부적합하여 채택하지 않음. 전체 결과를 검증된 디자인 시스템으로 저장하지 않음.
- 별도 실제 검색: `scripts/search.py 'keyboard focus modal' --domain ux`
- 확인한 규칙: 모든 모달 조작 요소의 가시적인 키보드 포커스, 가려지지 않는 포커스.
- 읽은 검수 지침: `references/pro-rules.md`, `references/quick-reference.md`의 접근성·상호작용·성능 항목.
- PySide6는 이 스킬의 지원 스택 목록에 없으므로 React·웹 구현 지침을 PySide6용 검색 결과라고 표현하지 않는다.

## 2. CC AI Toolkit

- 원본: https://github.com/gaebalai/cc-ai-toolkit
- 확인한 커밋: `48fc3ed58c0f7d2a39ded6268cf440499fe3767d`
- 저장소 설치 지침대로 원본 커맨드를 `.claude/commands/`에 복사함.
- `figma-to-code.md`: Phase 1 정보 수집 시작. 필수 Figma URL(node-id 포함)을 사용자에게 요청함.
- `sync-design-tokens.md`: Figma Variables의 `.figma/Library.json`과 Figma MCP가 전제 조건. 원본 입력이 없으므로 동기화 실행 완료로 처리하지 않음.
- Figma 노드·변수·스크린샷을 임의로 만들어 취득했다고 주장하지 않는다.

## 기존 컴포넌트 조사

현재 앱은 React/Tailwind가 아니라 Python/PySide6이다. `/components/ui` 대신 실제 구현인 `drift_gate/desktop`을 조사했다.

- `DesktopWindow`: 저장소 입력, 비교 기준, 검사 실행, 요약, 판정 목록, 상세 근거, 저장.
- `ReviewDialog`: 구독 CLI 선택, 전송 자료 미리보기, LLM 요청·취소, 응답.
- `service.py`: 로컬 검사와 결과 스냅샷. UI 개편 중 유지할 로직.
- `subscription_review.py`: 로그인 확인, CLI 실행, 구조화 응답 검사. UI 개편 중 유지할 로직.

## 개편 시 해결할 문제

1. 현재 고정 사이드바는 안내 문장만 반복하고 넓은 공간을 차지한다. 실제 탐색 또는 작업 설정 영역으로 바꾼다.
2. 입력·상태·통계 카드가 세로 공간을 먼저 차지한다. 결과 목록과 근거가 주 영역이 되도록 정보 계층을 재배치한다.
3. 첫 실행, 검사 중, 통과, 차단, 오류, LLM 미연결·요청 중·완료를 구분한다.
4. 규칙 판정과 LLM 의견의 역할을 화면에서 구분하고 기존 gate 값을 바꾸지 않는다.
5. 색상만으로 판정을 전달하지 않고 텍스트 상태를 함께 제공한다.
6. 서체·색·간격을 공통 토큰으로 모으고 한국어 OS 기본 폰트 대체 경로를 둔다.
7. 최소 창 크기, 키보드 이동, 긴 경로·긴 근거, HTML·JSON 저장을 실제 검증한다.

## 다음 입력과 검증

Figma 화면 URL을 받으면 CC AI Toolkit의 신규/기존 컴포넌트 대조와 디자인 취득을 진행하고, 전체 컴포넌트 트리를 포함한 구현안을 만든다. 원본 스킬의 Figma 기반 구현 절차를 임의의 스타일 참고로 대체하지 않는다.

구현 후 빈 화면·실제 규칙 검사 결과·LLM 결과 화면을 캡처하고 기능 테스트와 패키지 실행을 확인한다. 두 스킬의 실제 실행 단계와 수행하지 못한 단계를 구분해 보고한다.

## 2026-09-29 후속 구현

사용자가 Figma 대신 Claude 아티팩트와 tool-ui 사용을 지정했다. 해당 화면을 직접 확인하고 React/Qt 통합으로 구현했다. Figma 스킬의 필수 입력은 여전히 없으므로 실행 범위는 위와 같다. 후속 구현·검증은 [tool-ui 통합 기록](tool-ui-integration-2026-09-29.md)에 있다.
