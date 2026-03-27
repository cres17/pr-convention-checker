# /drift-gate:review

`.drift-gate.yml` 정책을 기준으로 현재 브랜치 또는 PR의 변경사항이
팀 계약 문서(spec/runbook/CHANGELOG/.env.example 등)와 동기화되어 있는지 로컬에서 사전 점검합니다.

PR을 올리기 전에 실행해 누락 문서를 미리 발견하고 수정할 수 있습니다.

---

## 인자 파싱

`$ARGUMENTS`를 확인합니다:

- 숫자 (예: `42`) → GitHub PR 번호로 처리
- 브랜치명 또는 SHA (예: `main`, `feat/login`) → base ref로 사용
- 비어 있으면 → base를 `main`으로 사용

---

## Step 1 — 정책 파일 로드

레포 루트에서 `.drift-gate.yml`을 읽습니다.

파일이 없으면 아래 메시지를 출력하고 종료합니다:

```
⚠️  .drift-gate.yml이 없습니다.
레포 루트에 정책 파일을 추가하면 drift 검사를 시작할 수 있습니다.
참고: https://github.com/cres17/pr-convention-checker#configuration
```

정책 로드 후 각 규칙의 `require.groups` 존재 여부를 검증합니다.
`require.groups`가 없는 규칙이 있으면:

```
❌ 정책 오류: rule '<id>'에 require.groups가 없습니다.
   require.groups는 최소 1개 이상의 묶음을 정의해야 합니다.
```

---

## Step 2 — 변경 파일 수집

### PR 번호가 주어진 경우

GitHub MCP 서버가 사용 가능하면 MCP 도구를 우선 사용합니다:
- `get_pull_request_files`: 변경 파일 목록 (path, status, patch)
- `get_pull_request`: PR description (drift-ignore 파싱용)

GitHub MCP 서버가 없으면 `gh` CLI로 폴백합니다:
```bash
gh pr view <PR번호> --json files,body
```

### 브랜치/SHA 또는 기본값

```bash
git diff --name-status <base>...HEAD
```

---

## Step 3 — drift-ignore 파싱

PR description 또는 최근 커밋 메시지에서 아래 패턴을 검색합니다:

```
drift-ignore: <rule-id>
reason: <이유>
```

찾은 rule-id는 평가에서 제외합니다.
`reason:`이 없으면 경고를 표시합니다:

```
⚠️  drift-ignore 'api-contract-sync' — reason 없음. 감사 추적을 위해 reason 추가를 권장합니다.
```

---

## Step 4 — 변경 유형 분류

변경 파일 경로를 아래 기준으로 분류합니다.

| 유형 | 트리거 경로 |
|------|------------|
| `api-surface` | `src/routes/**`, `openapi/**`, `proto/**`, `src/controllers/**` |
| `db-schema` | `db/migrations/**`, `prisma/schema.prisma`, `sql/**` |
| `env-config` | `.env*`, `config/**`, `src/config/**` |
| `workflow-ci` | `.github/workflows/**`, `Dockerfile*`, `infra/**`, `terraform/**` |
| `auth-permission` | `**/auth/**`, `**/rbac/**`, `**/permissions/**` |

**docs-only / test-only 판정:**
- 모든 변경 파일이 문서(`docs/**`, `**/*.md`) 패턴에만 해당 → `docs-only` → 드리프트 평가 생략
- 모든 변경 파일이 테스트(`tests/**`, `**/*.test.*`) 패턴에만 해당 → `test-only` → 드리프트 평가 생략

코드/설정/인프라 파일이 1개라도 포함되면 `docs-only`, `test-only`로 분류하지 않습니다.

**파일 상태별 처리:**
- `deleted`: 요구 산출물이 삭제된 경우 해당 규칙 위반 가능성을 우선 검토
- `renamed`: rename 전후 경로를 모두 고려해 `when` 매칭, `require`는 이후 경로 기준
- `modified`: patch가 없어도 경로 자체로 규칙 판정

---

## Step 5 — 규칙 평가

각 규칙을 순서대로 평가합니다.

**활성화:** `when.any_changed` 중 하나라도 변경 파일에 포함되면 활성화

**통과 조건:** 활성화된 규칙은 `require.groups`의 **모든 묶음**을 만족해야 통과
- `any_changed`: 묶음 내 경로 중 하나라도 변경(삭제 제외)되면 충족
- `all_changed`: 묶음 내 경로가 모두 변경(삭제 제외)되어야 충족

묶음 하나라도 불충족이면 해당 규칙은 위반입니다.

---

## Step 6 — 결과 출력

`skills/drift-gate.md`에 정의된 형식으로 결과를 출력합니다.

### 위반 없음

```
✅ Drift Gate 통과

정책: .drift-gate.yml
변경 파일: N개 | 유형: api-surface, db-schema
위반 없음 — 계약 문서가 동기화되어 있습니다.
```

### 위반 있음

각 위반 항목을 아래 형식으로 출력합니다:

```
[SEVERITY] <rule-id>
  변경 유형: <유형>
  트리거 파일:
    - path/to/file  (status)
  불충족 묶음:
    - "<그룹명>": <required 경로들> — 변경 없음
  왜 필요한가: <근거>
  체크리스트:
    - [ ] ...
  무시하려면:
    drift-ignore: <rule-id>
    reason: <이유>
```

결과 마지막에 요약을 추가합니다:

```
---
📊 요약: BLOCKER N개 · MAJOR N개 · MINOR N개 · NIT N개
🔖 정책: .drift-gate.yml
📂 변경 파일: N개 | 유형: <유형 목록>
⚙️  CI 판정: FAIL / WARN / PASS
```

### JSON 출력 요청 시

`$ARGUMENTS`에 `--json`이 포함되면 Markdown 대신 JSON을 출력합니다:

```json
{
  "summary": { "blocker": 1, "major": 0, "minor": 0, "nit": 0, "passed": false },
  "result": "fail",
  "change_types": ["api-surface"],
  "violations": [...]
}
```
