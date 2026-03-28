# drift-gate

PR 변경 파일 목록과 diff를 받아 팀 계약 문서(spec/contract/runbook/CHANGELOG/.env.example 등)와의
정합성을 점검하고, 누락된 산출물을 심각도별로 분류해 출력하는 분석 스킬.

`/drift-gate:review` 커맨드와 GitHub Actions에서 동일하게 사용됩니다.

---

## 입력 형식

이 스킬은 다음 입력을 전제로 합니다:

1. **변경 파일 목록** (`changed_files[]`)
   - `path`: 파일 경로
   - `status`: `added` / `modified` / `deleted` / `renamed`
   - `patch`: diff 내용 (없을 수 있음)
   - `renamed`이면 `previous_path`도 포함됨

2. **정책 파일** (`.drift-gate.yml`)
   - `rules[]`: 각 규칙의 when/require/severity/message 구성
   - `gate`: CI 실패 기준
   - `ignore_paths`: 평가 제외 경로
   - 파일이 없으면 내장 기본 정책을 사용합니다

---

## Step 1 — 정책 파일 로드

`.drift-gate.yml`을 읽습니다. 없으면 기본 정책을 사용합니다.

정책 로드 시 아래 조건을 검증합니다:

- 각 규칙에 `require.groups`가 존재하지 않으면 **정책 로드 실패**로 처리하고 즉시 종료합니다:

```
❌ 정책 파일 오류: rule '<id>'에 require.groups가 없습니다.
   require.groups는 최소 1개 이상의 묶음을 정의해야 합니다.
```

- `ignore_paths`에 매칭되는 파일은 모든 규칙 평가에서 제외합니다.

---

## Step 2 — 변경 유형 분류

`changed_files[]`의 경로를 아래 기준으로 분류합니다. 복수 유형 동시 적용 가능합니다.

### 분류 기준 (경로 규칙 우선)

| 유형 | 트리거 경로 |
|------|------------|
| `api-surface` | `src/routes/**`, `openapi/**`, `proto/**`, `src/controllers/**` |
| `db-schema` | `db/migrations/**`, `prisma/schema.prisma`, `sql/**`, `**/schema.sql` |
| `env-config` | `.env`, `.env.local`, `.env.production`, `config/**`, `src/config/**`, `**/settings.py` |
| `workflow-ci` | `.github/workflows/**`, `Dockerfile*`, `infra/**`, `terraform/**` |
| `auth-permission` | `**/auth/**`, `**/middleware/auth*`, `**/rbac/**`, `**/permissions/**` |
| `docs-only` | 아래 별도 조건 참고 |
| `test-only` | 아래 별도 조건 참고 |

### docs-only / test-only 단독 분류 조건

`docs-only`와 `test-only`는 **보조 라벨이 아닙니다**. 아래 조건을 완전히 만족할 때만 해당됩니다.

- `docs-only`: **모든** 변경 파일이 `docs/**`, `**/*.md`, `**/*.rst` 패턴에만 해당할 때
- `test-only`: **모든** 변경 파일이 `tests/**`, `**/*.test.*`, `**/*.spec.*` 패턴에만 해당할 때

코드/설정/인프라 파일이 1개라도 포함되면 `docs-only`, `test-only`로 분류하지 않습니다.

`docs-only` 또는 `test-only`로 분류된 PR은 drift 규칙 평가를 수행하지 않고 통과 처리합니다.

### 파일 상태별 처리 규칙

- `deleted`: 요구 산출물이 삭제된 경우, 해당 규칙 위반 가능성을 **우선** 검토합니다.
  예) `CHANGELOG.md`가 `all_changed`에 있고 status가 `deleted`면 즉시 위반으로 판정합니다.
- `renamed`: rename 전후 경로를 **모두** 고려해 규칙을 평가합니다.
  `when`은 이전/이후 경로 중 하나라도 매칭되면 활성화합니다.
  `require`는 이후 경로 기준으로 평가합니다.
- `modified`: patch가 비어 있어도 changed path 자체는 규칙 판정에 사용합니다.

### 분류 신뢰도 (confidence)

- `high`: 경로 규칙에 명확하게 대응됨
- `medium`: 경계 파일이거나 복수 유형, renamed 파일, 와일드카드 교차 패턴
- `low`: 분류 유형이 `other`이거나 인식 불가능한 경로

`medium` 또는 `low` 신뢰도 항목은 결과에 포함하되 Markdown에 `[추정]` 라벨을 붙입니다.

---

## Step 3 — 규칙 평가

각 규칙에 대해 순서대로 평가합니다.

### 활성화 조건

`when.any_changed`에 해당하는 경로 중 하나라도 변경 파일 목록에 포함되면 규칙이 활성화됩니다.

### 통과 조건

활성화된 규칙은 `require.groups`의 **모든 묶음**을 만족해야 통과합니다.

묶음 충족 기준:
- `any_changed`: 묶음 안의 경로 중 **하나라도** `changed_files`에 포함되면 충족
- `all_changed`: 묶음 안의 경로가 **모두** `changed_files`에 포함되어야 충족
  (단, `deleted` 상태 파일은 충족으로 보지 않습니다)

**묶음 하나라도 불충족이면 해당 규칙은 위반입니다.**

### drift-ignore 처리

PR description에 아래 형식이 있으면 해당 규칙을 평가에서 제외합니다:

```
drift-ignore: <rule-id>
reason: <이유>
```

심각도별 처리 규칙:

| 심각도 | reason 있음 | reason 없음 |
|--------|------------|------------|
| BLOCKER / MAJOR | `skipped_rules`에 기록 후 규칙 생략 | **`rejected_ignores`에 기록, 규칙은 정상 평가** |
| MINOR / NIT | `skipped_rules`에 기록 후 규칙 생략 | `skipped_rules`에 기록 후 규칙 생략 (reason 선택) |

`rejected_ignores`에 기록된 항목은 JSON 출력에 포함되며, 해당 위반은 `violations`에 그대로 남습니다.

---

## Step 4 — 출력

출력은 반드시 **Markdown 요약**과 **JSON 결과** 두 가지를 생성합니다.

### Markdown 위반 항목 형식

```
[SEVERITY] <rule-id>  ← confidence=low면 [SEVERITY][추정]
  변경 유형: <api-surface | db-schema | env-config | workflow-ci | auth-permission>
  트리거 파일:
    - path/to/file.ts  (modified)
  불충족 묶음:
    - "<그룹 name>": docs/spec.md, docs/api/** 중 변경 없음
    - "<그룹 name>": CHANGELOG.md 미변경
  왜 필요한가: <policy message 또는 LLM 생성 근거>
  체크리스트:
    - [ ] ...
    - [ ] ...
  무시하려면:
    drift-ignore: <rule-id>
    reason: <why>
```

### JSON 결과 형식

`drift_gate_report.json`으로 저장되며 다음 스키마를 따릅니다.

```json
{
  "summary": {
    "blocker": 1,
    "major": 1,
    "minor": 0,
    "nit": 0,
    "gate_decision": "fail"
  },
  "result": "fail",
  "change_types": ["api-surface", "db-schema"],
  "violations": [
    {
      "rule_id": "api-contract-sync",
      "severity": "BLOCKER",
      "confidence": "high",
      "change_types": ["api-surface"],
      "change_type": "api-surface",
      "message": "API surface changed without synced contract/docs",
      "trigger_files": [
        { "path": "src/routes/users.ts", "status": "modified", "previous_path": null, "patch": "..." }
      ],
      "unsatisfied_groups": [
        {
          "name": "API 계약 문서",
          "required": ["docs/spec.md", "docs/api/**"],
          "type": "any_changed"
        },
        {
          "name": "릴리즈 공지",
          "required": ["CHANGELOG.md"],
          "type": "all_changed"
        }
      ],
      "checklist": [
        "관련 spec/API 문서를 변경 내용에 맞게 업데이트",
        "CHANGELOG.md에 변경 항목 추가"
      ],
      "ignored": false
    }
  ],
  "skipped_rules": [
    {
      "rule_id": "workflow-ops-doc",
      "severity": "MINOR",
      "reason": "dev-only infra change",
      "message": "CI/infra changed without ops documentation update"
    }
  ],
  "rejected_ignores": [
    {
      "rule_id": "schema-migration-proof",
      "severity": "MAJOR",
      "message": "DB schema changed without migration note or integration test"
    }
  ],
  "gate": { "fail_on_blocker": true, "fail_on_major_count": 2 },
  "policy_file": ".drift-gate.yml"
}
```

**필드 설명:**

| 필드 | 설명 |
|------|------|
| `summary.gate_decision` | `pass` / `warn` / `fail` — CI 최종 판정 |
| `violations[].confidence` | `high` / `medium` / `low` — 경로 패턴 매칭 신뢰도. `high` 외에는 Markdown에 `[추정]` 표시 |
| `violations[].change_types` | 트리거 파일의 분류된 변경 유형 배열 |
| `violations[].change_type` | 대표 변경 유형 (단수, `change_types[0]`) |
| `violations[].checklist` | 불충족 묶음 이름 기반 결정론적 체크리스트. Claude API가 보강 가능 |
| `skipped_rules` | drift-ignore가 적용된 규칙 (rule_id, severity, reason, message) |
| `rejected_ignores` | reason 없이 BLOCKER/MAJOR drift-ignore를 시도한 목록. 해당 규칙은 violations에 그대로 존재 |

### 전체 Markdown 출력 예시 (로컬 모드)

```
## Drift Gate 분석 결과

[BLOCKER] api-contract-sync
  변경 유형: api-surface
  트리거 파일:
    - src/routes/users.ts  (modified)
    - openapi/users.yaml   (modified)
  불충족 묶음:
    - "API 계약 문서": docs/spec.md, docs/api/** 중 변경 없음
    - "릴리즈 공지": CHANGELOG.md 미변경
  왜 필요한가: API surface 변경 시 계약 문서와 릴리즈 공지가 동기화되어야 합니다.
  체크리스트:
    - [ ] docs/spec.md에 변경된 엔드포인트 반영
    - [ ] CHANGELOG.md에 변경 항목 추가
    - [ ] 클라이언트팀에 breaking change 여부 공지
  무시하려면:
    drift-ignore: api-contract-sync
    reason: internal refactor only, no externally visible contract change

[MAJOR] schema-migration-proof
  변경 유형: db-schema
  트리거 파일:
    - prisma/schema.prisma  (modified)
    - db/migrations/0012_add_user_role.sql  (added)
  불충족 묶음:
    - "운영 문서": docs/runbook/**, docs/migration-notes/** 중 변경 없음
    - "검증 흔적": tests/integration/**, tests/e2e/** 중 변경 없음
  왜 필요한가: DB 스키마 변경 시 rollback plan과 integration test가 필요합니다.
  체크리스트:
    - [ ] docs/runbook/migration-0012.md 작성 (rollback 절차 포함)
    - [ ] integration test 추가 또는 기존 업데이트
  무시하려면:
    drift-ignore: schema-migration-proof
    reason: <why>

---
📊 요약: BLOCKER 1개 · MAJOR 1개 · MINOR 0개 · NIT 0개
🔖 정책 파일: .drift-gate.yml
📂 변경 파일: 4개 | 유형: api-surface, db-schema
⚙️  CI 판정: FAIL (BLOCKER 1개)
```

---

## GitHub Actions 모드 출력

PR 코멘트용 Markdown을 생성합니다. 중복 게시 방지 마커를 반드시 포함합니다:

```html
<!-- drift-gate-v1 -->
```

전체 코멘트 형식:

```markdown
<!-- drift-gate-v1 -->
## 🔍 Drift Gate 분석 결과

> 정책: `.drift-gate.yml` | 변경 파일: N개 | 유형: api-surface, db-schema

### 🚫 BLOCKER (1)

**[api-contract-sync]** API surface changed without synced contract/docs

| 트리거 파일 | `src/routes/users.ts` (modified), `openapi/users.yaml` (modified) |
|---|---|
| 불충족: API 계약 문서 | `docs/spec.md`, `docs/api/**` 중 변경 없음 |
| 불충족: 릴리즈 공지 | `CHANGELOG.md` 미변경 |

**체크리스트**
- [ ] docs/spec.md에 변경 내용 반영
- [ ] CHANGELOG.md 업데이트

> `drift-ignore: api-contract-sync` + `reason:` 을 PR description에 추가하면 이 규칙을 건너뜁니다.

---

### ⚠️ MAJOR (N)
...

### 💬 MINOR (N)
...

---
<details>
<summary>ℹ️ 이 체크에 대해</summary>

이 코멘트는 팀 계약 문서와 코드 변경의 정합성을 자동으로 점검합니다.
규칙을 무시하려면 PR description에 아래를 추가하세요:

```
drift-ignore: <rule-id>
reason: <이유>
```

자세한 내용은 [Spec/Contract Drift Gate](https://github.com/cres17/pr-convention-checker)를 참고하세요.
</details>
```

BLOCKER 0개일 때:
```markdown
✅ **계약 문서 동기화 완료** — 모든 정책 규칙을 통과합니다.
```

BLOCKER 1개 이상일 때:
```markdown
🚫 **머지 전 수정 필요** — BLOCKER N개. 계약 문서를 동기화하세요.
```

---

## CI 게이트 판정 로직

```
docs-only 또는 test-only PR                 → result=pass, exit 0 (드리프트 평가 생략)
BLOCKER/MAJOR drift-ignore + reason 없음    → rejected_ignores 기록, 규칙은 정상 평가 유지
BLOCKER ≥ 1 && fail_on_blocker=true        → result=fail, exit 1
MAJOR ≥ fail_on_major_count (기본 2)       → result=fail, exit 1
MAJOR ≥ 1 또는 MINOR ≥ 1                  → result=warn, exit 0 (PR 코멘트만)
위반 없음                                  → result=pass, exit 0, ✅ 코멘트 게시
```

**BLOCKER/MAJOR drift-ignore reason 정책:**
- `reason:`이 있으면 → 규칙이 `skipped_rules`로 이동 (violations에서 제외)
- `reason:`이 없으면 → `rejected_ignores`에 기록되지만 규칙은 **violations에 유지**. CI는 위반 심각도에 따라 정상 판정.

게이트 기준은 `.drift-gate.yml`의 `gate:` 섹션으로 오버라이드합니다:

```yaml
gate:
  fail_on_blocker: true
  fail_on_major_count: 2
```

---

## 오탐(False Positive) 처리 가이드

1. **docs-only / test-only**: 모든 변경이 문서 또는 테스트 파일이면 drift 평가를 수행하지 않습니다.

2. **내부 구현 전용 변경**: 외부 API 계약에 영향을 주지 않는 리팩토링이라면 `api-surface`로
   분류하지 않습니다. 판단이 모호하면 `[추정]` 처리합니다.

3. **삭제 파일이 요구 산출물인 경우**: `deleted` 상태 파일은 `all_changed` 충족으로 보지 않습니다.
   단, `any_changed`에서 다른 파일이 충족하면 해당 묶음은 통과합니다.

4. **rename 후 경로가 require에 없는 경우**: rename 이후 경로로 re-evaluate하고,
   기존 경로와 매칭이 달라지면 `[추정]`으로 처리합니다.

5. **정책 파일 없음 / 문서 부재**: `.drift-gate.yml`이 없고 추적할 계약 문서도 없으면
   분석을 스킵하고 아래 안내를 출력합니다:

```
⚠️  .drift-gate.yml이 없습니다.
레포 루트에 정책 파일을 추가하면 팀 규칙 기반 drift 검사를 시작할 수 있습니다.
템플릿: https://github.com/cres17/pr-convention-checker#configuration
```
