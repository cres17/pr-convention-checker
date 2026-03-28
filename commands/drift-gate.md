# /drift-gate:review

`.drift-gate.yml` 정책 기준으로 현재 브랜치/PR 변경분이 팀 계약 문서와 동기화되어 있는지 로컬 사전 점검.

---

## 인자 파싱

`$ARGUMENTS` 확인:
- 숫자 → GitHub PR 번호
- 브랜치명/SHA → base ref
- 비어 있음 → base=`main`
- `--json` 포함 → JSON 출력

---

## Step 1 — 정책 파일 로드

레포 루트 `.drift-gate.yml` 로드. 없으면:
```
⚠️ .drift-gate.yml 없음. https://github.com/cres17/pr-convention-checker#configuration
```

각 규칙의 `require.groups` 검증 — 없으면 즉시 종료:
```
❌ 정책 오류: rule '<id>'에 require.groups 없음
```

---

## Step 2 — 변경 파일 수집

### PR 번호 지정 시

GitHub MCP 서버 우선:
- `get_pull_request_files` — 전체 파일 목록 (페이지 처리 내부 수행)
- `get_pull_request` — PR description (drift-ignore 파싱용)

MCP 없으면 `gh` CLI 폴백:
```bash
gh pr view <PR번호> --json files,body
```
`gh`는 내부적으로 페이지네이션을 처리하므로 파일 수 제한 없음.

### 브랜치/기본값

```bash
git diff --name-status <base>...HEAD
```

> **대형 PR**: MCP와 `gh` CLI 모두 100개 이상 파일을 완전히 수집함.

---

## Step 3 — drift-ignore 파싱

PR description 또는 최근 커밋 메시지에서 파싱:
```
drift-ignore: <rule-id>
reason: <이유>
```

심각도별 처리:

| 심각도 | reason 있음 | reason 없음 |
|--------|------------|------------|
| BLOCKER / MAJOR | 규칙 생략 (`skipped`) | **거부 — 규칙 정상 평가 유지** (`rejected`) |
| MINOR / NIT | 규칙 생략 | 규칙 생략 (reason 선택) |

BLOCKER/MAJOR를 reason 없이 ignore하면 `rejected_ignores`에 기록되고 해당 위반은 violations에 남음.

---

## Step 4 — 변경 유형 분류

| 유형 | 트리거 경로 |
|------|------------|
| `api-surface` | `src/routes/**`, `openapi/**`, `proto/**`, `src/controllers/**` |
| `db-schema` | `db/migrations/**`, `prisma/schema.prisma`, `sql/**` |
| `env-config` | `.env*`, `config/**`, `src/config/**` |
| `workflow-ci` | `.github/workflows/**`, `Dockerfile*`, `infra/**`, `terraform/**` |
| `auth-permission` | `**/auth/**`, `**/rbac/**`, `**/permissions/**` |

**단독 분류 조건:**
- `docs-only`: 모든 파일이 `docs/**`, `**/*.md`, `**/*.rst`만 → 드리프트 평가 생략
- `test-only`: 모든 파일이 `tests/**`, `**/*.test.*`, `**/*.spec.*`만 → 생략

코드/설정 파일 1개라도 포함 시 위 분류 적용 안 됨.

**파일 상태 처리:**
- `deleted`: 요구 산출물 삭제 → 즉시 위반 검토
- `renamed`: when=이전+이후 경로 중 하나 매칭, require=이후 경로 기준
- `modified`: patch 없어도 경로로 판정

---

## Step 5 — 규칙 평가

**활성화:** `when.any_changed` 중 하나라도 변경 파일에 포함

**통과 조건:** `require.groups` 모든 묶음 충족 필요
- `any_changed`: 묶음 내 경로 하나라도 변경(삭제 제외) → 충족
- `all_changed`: 묶음 내 경로 전부 변경(삭제 제외) → 충족

묶음 하나라도 불충족 → 해당 규칙 위반.

---

## Step 6 — 결과 출력

`skills/drift-gate.md` 형식으로 출력.

### 위반 없음
```
✅ Drift Gate 통과
정책: .drift-gate.yml | 변경 파일: N개 | 유형: api-surface, db-schema
위반 없음 — 계약 문서 동기화 완료.
```

### 위반 있음

각 위반 항목:
```
[SEVERITY][추정?] <rule-id>
  변경 유형: <change_type>
  트리거 파일:
    - path/to/file  (status)
  불충족 묶음:
    - "<그룹명>": <required 경로들> 변경 없음
  체크리스트:
    - [ ] ...
  무시하려면:
    drift-ignore: <rule-id>
    reason: <이유>  ← BLOCKER/MAJOR 필수
```

`[추정]` — confidence가 `medium` 또는 `low`일 때 표시.

요약:
```
📊 BLOCKER N · MAJOR N · MINOR N · NIT N
⚙️ CI 판정: FAIL / WARN / PASS
```

### `--json` 출력 시

```json
{
  "summary": {
    "blocker": 1, "major": 0, "minor": 0, "nit": 0,
    "gate_decision": "fail"
  },
  "result": "fail",
  "change_types": ["api-surface"],
  "violations": [
    {
      "rule_id": "api-contract-sync",
      "severity": "BLOCKER",
      "confidence": "high",
      "change_types": ["api-surface"],
      "change_type": "api-surface",
      "message": "...",
      "trigger_files": [{"path": "src/routes/users.ts", "status": "modified"}],
      "unsatisfied_groups": [
        {"name": "API 계약 문서", "required": ["docs/spec.md"], "type": "any_changed"}
      ],
      "checklist": ["관련 spec/API 문서를 변경 내용에 맞게 업데이트"],
      "ignored": false
    }
  ],
  "skipped_rules": [
    {"rule_id": "workflow-ops-doc", "severity": "MINOR", "reason": "dev-only", "message": "..."}
  ],
  "rejected_ignores": [],
  "gate": {"fail_on_blocker": true, "fail_on_major_count": 2},
  "policy_file": ".drift-gate.yml"
}
```
