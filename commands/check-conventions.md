# /check-conventions

팀 컨벤션 문서(CLAUDE.md, SKILLS.md 등)를 기준으로 PR 또는 현재 브랜치의 변경사항이
정의된 규칙을 지키는지 자동으로 분석합니다.

> CodeRabbit·ESLint와 달리 **이 레포에 문서화된 팀 고유의 패턴과 설계 규칙**을 체크합니다.

---

## 인자 파싱

`$ARGUMENTS`를 확인합니다.

- 숫자만 있는 경우 (예: `42`) → GitHub PR 번호로 처리합니다.
- 브랜치명 또는 SHA (예: `main`, `develop`, `abc1234`) → base ref로 사용합니다.
- 비어 있으면 → base를 `main`으로 사용합니다.

---

## Step 1 — 설정 파일 로드

`.convention-checker.yml`이 존재하면 읽습니다.
없으면 아래 기본값을 사용합니다.

```
convention_files:
  - CLAUDE.md
  - SKILLS.md
  - .claude/instructions.md
  - docs/conventions.md

exclude_paths:
  - "**/*.test.ts"
  - "**/*.test.js"
  - "**/*.spec.ts"
  - "**/*.spec.js"
  - "**/*.test.tsx"
  - "**/*.snap"
  - ".github/**"
  - "dist/**"
  - "build/**"
  - "node_modules/**"
  - "**/*.lock"
  - "**/*-lock.json"
  - "**/*.min.js"
  - "**/*.min.css"

severity_map:
  blocker:
    - "must"
    - "반드시"
    - "절대"
    - "금지"
    - "never"
    - "always"
    - "항상"
  major:
    - "should"
    - "권장"
    - "필요"
    - "required"
  nit:
    - "prefer"
    - "가급적"
    - "권고"
    - "optional"
```

---

## Step 2 — 컨벤션 파일 수집

설정의 `convention_files` 목록을 순서대로 확인합니다.

각 경로에 대해 파일이 존재하면 읽습니다. 존재하지 않으면 조용히 건너뜁니다.

읽어들인 모든 컨벤션 파일의 내용을 하나로 합칩니다.
파일별로 `<!-- source: CLAUDE.md -->` 형태의 구분자를 앞에 붙여 출처를 추적합니다.

**토큰 최적화 — 컨벤션 캐시 추출:**
합쳐진 컨벤션 텍스트에서 규칙성이 높은 섹션만 추출합니다.

추출 기준 (다음 패턴이 포함된 단락/섹션을 우선 포함):
- 명령형 동사로 시작하는 항목: "Use", "Avoid", "Never", "Always", "사용하라", "하지 말 것", "반드시"
- 불릿 리스트(`- `, `* `) 형태의 규칙 목록
- "## 컨벤션", "## 규칙", "## Rules", "## Conventions", "## Guidelines" 헤딩의 하위 내용
- 코드 블록이 없고 서술형으로 된 섹션 (배경, 히스토리, 예시 설명은 제외)

추출 후 전체 컨벤션이 4,000 토큰(약 16,000자)을 초과하면 헤딩 단위로 요약합니다:
- 각 섹션의 첫 번째 불릿/문장만 남깁니다.
- 코드 예시는 잘라냅니다.

컨벤션 파일을 하나도 찾지 못했으면 다음 메시지를 출력하고 종료합니다:

```
⚠️  컨벤션 파일을 찾을 수 없습니다.
레포 루트에 CLAUDE.md 또는 SKILLS.md를 작성하거나,
.convention-checker.yml의 convention_files 경로를 확인하세요.
```

---

## Step 3 — Diff 수집

### 경우 A: PR 번호가 주어진 경우

GitHub MCP 서버가 사용 가능하면 MCP 도구로 PR diff를 가져옵니다:
- `get_pull_request` 로 PR 메타데이터 (title, body, base branch) 확인
- `get_pull_request_files` 로 변경 파일 목록과 각 파일의 patch 수집

GitHub MCP 서버가 없으면 `gh` CLI로 폴백합니다:
```
gh pr diff <PR번호>
gh pr view <PR번호> --json files,title,body
```

### 경우 B: 브랜치/SHA 또는 기본값

```
git diff <base>...HEAD
```

변경된 파일 목록도 함께 수집합니다:
```
git diff --name-only <base>...HEAD
```

---

## Step 4 — Diff 전처리 (토큰 최적화)

수집한 diff에서 다음 항목을 제거합니다:

1. **제외 경로 필터**: 설정의 `exclude_paths` glob 패턴에 매칭되는 파일의 diff 전체를 제거합니다.

2. **바이너리/생성 파일 제거**: 다음 패턴으로 시작하는 diff 섹션을 제거합니다:
   - `Binary files`
   - `new file mode` + 내용 없음
   - `index ` 줄만 있는 섹션

3. **컨텍스트 축소**: 각 파일 diff에서 실제 변경 줄(`+`/`-`로 시작)만 남기고,
   컨텍스트 줄(변경 없는 줄)은 변경 줄 앞뒤 2줄만 남깁니다.

   단, 파일당 변경 줄이 200줄을 초과하면 처음 200줄 + `... (N줄 생략)` 표시를 합니다.

4. **민감 정보 제거**: 다음 패턴이 포함된 줄은 `[REDACTED]`로 대체합니다:
   - `password`, `secret`, `api_key`, `apikey`, `token` (값이 할당된 줄)
   - `.env` 파일 전체

처리 후 diff가 비어 있으면:
```
ℹ️  분석할 변경사항이 없습니다. (모든 파일이 제외 패턴에 해당하거나 변경사항이 없습니다.)
```

---

## Step 5 — convention-ignore 처리

전처리된 diff를 줄 단위로 검토합니다.

다음 패턴이 포함된 줄(`+` 추가 줄 기준) 또는 그 직전 줄에
`convention-ignore` 지시어가 있으면 해당 줄은 분석에서 제외합니다:

```
// convention-ignore
# convention-ignore
/* convention-ignore */
<!-- convention-ignore -->
convention-ignore: <이유>
```

블록 단위로 무시하려면:
```
// convention-ignore-start
...무시할 코드 블록...
// convention-ignore-end
```

이렇게 마킹된 범위의 모든 줄은 분석 대상에서 제외합니다.
제외된 줄이 있으면 결과 하단에 요약합니다:

```
💬 convention-ignore로 건너뛴 항목: N개
```

---

## Step 6 — 컨벤션 분석

다음 지시로 분석을 수행합니다:

**분석 지시:**

아래 "컨벤션 문서"와 "PR diff"를 대조합니다.

diff에서 추가(`+`)된 코드가 컨벤션 문서에 명시된 규칙을 위반하는지 확인합니다.
삭제(`-`)된 코드는 기존 위반 사항을 제거하는 것이므로 지적 대상이 아닙니다.

**심각도 판단 기준:**
- `BLOCKER`: 컨벤션 문서에서 "must", "반드시", "절대", "금지", "never", "always", "항상" 같은 강한 의무 표현으로 명시된 규칙 위반
- `MAJOR`: "should", "권장", "필요", "required" 등 권고 표현의 규칙 위반
- `MINOR`: 명확히 위반이지만 경미한 경우, 또는 개선 여지가 있는 경우
- `NIT`: "prefer", "가급적", "권고" 등 선호 표현, 또는 스타일 차원의 미준수

**지적 금지 사항 (오탐 방지):**
- 컨벤션 문서에 명시되지 않은 일반적인 코드 품질 문제는 지적하지 않습니다.
- "이렇게 하면 더 낫다"는 범용 조언은 하지 않습니다.
- 컨벤션 문서가 모호하거나 해당 코드에 적용 가능한지 불명확한 경우,
  지적하되 신뢰도(confidence)를 `low`로 표시합니다.
- 테스트 파일, 타입 정의 파일에는 적용 범위가 명시된 컨벤션만 적용합니다.

분석할 때 `skills/convention-check.md`의 출력 형식을 따릅니다.

---

## Step 7 — 결과 출력

`skills/convention-check.md`에 정의된 형식으로 결과를 출력합니다.

결과가 없는 경우 (위반 없음):
```
✅ 컨벤션 체크 통과

분석 기준: CLAUDE.md, SKILLS.md
분석한 파일: N개
위반 항목: 없음

이 PR은 문서화된 팀 컨벤션을 준수합니다.
```

위반이 있는 경우 `skills/convention-check.md` 형식으로 출력하고,
마지막에 요약을 추가합니다:

```
---
📊 요약: BLOCKER N개 · MAJOR N개 · MINOR N개 · NIT N개
🔖 분석 기준: <읽은 컨벤션 파일 목록>
📂 분석한 파일: N개 (제외 N개)
```
