# convention-check

PR diff와 컨벤션 문서를 받아 위반 항목을 심각도별로 분류하고 출력하는 분석 스킬.
`/check-conventions` 커맨드에서 호출되며, GitHub Actions 모드에서도 동일하게 사용됩니다.

---

## 입력 형식

이 스킬은 다음 두 가지 입력을 전제로 합니다:

1. **컨벤션 문서** (추출·압축된 텍스트)
   - 출처 파일명이 `<!-- source: FILENAME -->` 주석으로 앞에 표시됨
   - 규칙이 명시된 섹션과 불릿 항목으로 구성됨

2. **전처리된 diff**
   - `+`/`-` 줄만 의미 있는 변경사항
   - `convention-ignore` 마킹된 줄은 이미 제거됨
   - 파일 헤더: `diff --git a/path b/path` 또는 `--- a/path` / `+++ b/path`

---

## 분석 원칙

### 무엇을 체크하는가

컨벤션 문서에 **명시적으로 기술된 규칙**만 체크합니다.

체크 대상:
- 특정 패턴 사용/미사용 강제 ("Error는 Result 타입으로 처리할 것")
- 네이밍 규칙 ("API 라우트는 /api/v1/ 접두사")
- 아키텍처 패턴 ("서비스 레이어를 통해서만 DB 접근")
- 금지 패턴 ("console.log 사용 금지")
- 필수 포함 요소 ("외부 호출에는 retry 로직 포함")

체크 비대상:
- 컨벤션 문서에 없는 일반적인 코드 품질
- "이렇게 하면 더 좋다"는 범용 조언
- 리팩토링 제안
- 테스트 커버리지 (컨벤션 문서에 명시된 경우 제외)

### 신뢰도 (confidence)

각 지적 항목에 신뢰도를 부여합니다:

- `high`: 컨벤션 문서의 규칙과 diff 코드가 명확하게 대응됨
- `medium`: 대응되지만 맥락이 제한적이거나 규칙 적용 범위가 불명확함
- `low`: 컨벤션 해석이 필요하거나, 의도적 예외일 가능성이 있음

`low` 신뢰도 항목은 결과에 포함하되 `[추정]` 라벨을 붙입니다.

---

## 출력 형식

### 위반 항목 형식

각 위반 항목은 다음 형식으로 출력합니다:

```
[SEVERITY] path/to/file.ts:LINE_NUMBER
  컨벤션: "<관련 규칙 원문>" (출처 파일:섹션 또는 줄번호)
  발견: <실제 코드 또는 상황 설명>
  제안: <어떻게 수정하면 규칙을 준수하는지>
```

라인 번호를 특정할 수 없으면 줄번호를 생략합니다.
제안이 명확하지 않은 경우 제안 줄도 생략할 수 있습니다.

`low` 신뢰도이면 SEVERITY 뒤에 `[추정]`을 추가합니다:
```
[MINOR][추정] path/to/file.ts:88
```

### 심각도 정의

```
BLOCKER  — 반드시 수정 후 머지. 컨벤션 문서의 강제 규칙 위반.
MAJOR    — 권고 규칙 위반. 팀 논의 후 머지 또는 수정 필요.
MINOR    — 경미한 위반 또는 개선 여지. 이번 PR에서 처리하거나 Follow-up 이슈 생성.
NIT      — 스타일·선호 차원. 지적이지만 블로킹하지 않음.
```

### 전체 출력 예시

```
## PR 컨벤션 체크 결과

[BLOCKER] src/api/users.ts:45
  컨벤션: "API 라우트는 반드시 /api/v1/ 접두사를 사용할 것" (CLAUDE.md › API 규칙)
  발견: `POST /users/create` — /api/v1/ 접두사 없음
  제안: `POST /api/v1/users` 형태로 변경

[MAJOR] src/services/payment.ts:88
  컨벤션: "외부 서비스 호출은 retry 로직을 포함해야 한다" (SKILLS.md › 외부 의존성)
  발견: `await stripe.charges.create(...)` — retry 없이 단순 await
  제안: retry 유틸리티로 감싸거나 exponential backoff 적용

[MINOR][추정] src/utils/logger.ts:12
  컨벤션: "로깅은 구조화된 JSON 형식을 사용할 것" (CLAUDE.md › 로깅)
  발견: `console.log('결제 완료:', amount)` — 구조화되지 않은 로그
  제안: `logger.info({ event: 'payment_complete', amount })` 형태로 변경

[NIT] src/components/UserCard.tsx:5
  컨벤션: "컴포넌트 파일명은 PascalCase를 사용할 것" (CLAUDE.md › 네이밍)
  발견: 파일명은 적절하나 내부 helper 함수가 `formatuser`로 camelCase 미준수
  제안: `formatUser`로 수정

---
📊 요약: BLOCKER 1개 · MAJOR 1개 · MINOR 1개 · NIT 1개
🔖 분석 기준: CLAUDE.md, SKILLS.md
📂 분석한 파일: 8개 (제외 3개)
```

---

## GitHub Actions 모드 출력

GitHub Actions에서 실행될 때는 PR 코멘트용 Markdown을 출력합니다.

코멘트 상단에 마커를 포함해야 합니다 (중복 게시 방지용):
```html
<!-- convention-checker-v1 -->
```

전체 코멘트 형식:

```markdown
<!-- convention-checker-v1 -->
## 🔍 PR 컨벤션 체크 결과

> 분석 기준: `CLAUDE.md`, `SKILLS.md` | 분석한 파일: N개

### 🚫 BLOCKER (N)
...

### ⚠️ MAJOR (N)
...

### 💬 MINOR (N)
...

### 🔧 NIT (N)
...

---
<details>
<summary>ℹ️ 이 체크에 대해</summary>

이 코멘트는 팀 컨벤션 문서를 기준으로 자동 생성됩니다.
특정 지적이 잘못되었다면 해당 줄에 `// convention-ignore` 주석을 추가하세요.
더 자세한 내용은 [PR Convention Checker](https://github.com/your-repo/pr-convention-checker)를 참고하세요.

</details>
```

BLOCKER가 0개면 상단에 ✅ 배지를 표시합니다:
```markdown
✅ **컨벤션 이슈 없음** — 모든 규칙을 준수합니다.
```

BLOCKER가 1개 이상이면:
```markdown
🚫 **머지 전 수정 필요** — BLOCKER N개가 발견되었습니다.
```

---

## 오탐(False Positive) 처리 가이드

이 스킬을 사용하는 Claude는 다음 상황에서 신중하게 판단해야 합니다:

1. **컨벤션이 모호한 경우**: "가능하면 함수형으로 작성한다"처럼 강제성이 없으면 MINOR 이하로만 지적합니다.

2. **예외가 명시된 경우**: 컨벤션 문서에 "다만 X 상황에서는 예외"가 있으면 해당 상황인지 확인합니다.

3. **테스트·스토리·픽스처 파일**: 컨벤션이 "프로덕션 코드"를 대상으로 한다면 테스트 파일은 제외합니다.

4. **이미 존재하는 패턴 수정**: diff에서 기존 위반 코드를 수정하는 `+` 줄이 완전히 컨벤션을 따르지 않더라도 방향이 올바르면 NIT로만 처리합니다.

5. **컨텍스트 부족**: 파일 전체를 볼 수 없어 판단이 어려울 때는 `low` 신뢰도를 부여합니다.
