# Spec/Contract Drift Gate

PR 변경분을 분석해 코드 변경이 팀의 계약 문서(spec/contract/runbook/CHANGELOG/.env.example)와
어긋났는지 자동 점검하는 정책 집행형 GitHub Action + Claude Plugin.

---

## 핵심 개념

**AI 리뷰가 아닌 문서-코드 정합성 정책 엔진.**
- 코드 스타일/버그/보안 취약점 검사 목적 아님
- `.drift-gate.yml` 규칙이 전부 — YAML만 바꾸면 코드 수정 없이 동작
- LLM은 체크리스트 보강에만 사용, core 판정 로직에 불필요

---

## 패키지 구조

```
drift_gate/
├── core/              ← 순수 로직, I/O 없음, 외부 의존성 없음
│   ├── models/        ← ChangedFile, Policy, EvaluationResult
│   ├── classification/ ← 파일 경로 → 변경 유형 분류
│   ├── policy/        ← .drift-gate.yml 로더 + require.groups 검증
│   ├── evaluation/    ← 규칙 평가 (drift-ignore 정책 포함)
│   ├── reasoning/     ← 결정론적 fallback 체크리스트
│   ├── gating/        ← pass/warn/fail 판정
│   └── engine.py      ← 단일 진입점 run()
│
├── adapters/          ← 모든 I/O는 여기서만
│   ├── github/        ← GitHub API (페이지네이션 포함)
│   ├── github_action/ ← GitHub Actions 전용 ($GITHUB_OUTPUT 기록)
│   ├── git/           ← local git diff
│   ├── cli/           ← argparse CLI
│   └── claude/        ← 선택적 LLM 보강 (실패 시 fallback)
│
├── reporters/         ← MarkdownReporter, JsonReporter (I/O 없음)
├── tests/
│   ├── fixtures/      ← PR 시나리오 JSON (api/db/docs-only)
│   └── test_engine.py ← 21개 테스트
└── utils/
    └── glob_matcher.py ← fnmatch 불사용, ** 직접 처리
```

---

## 변경 유형 분류

| 유형 | 트리거 경로 예시 |
|------|----------------|
| `api-surface` | `src/routes/**`, `openapi/**`, `proto/**` |
| `db-schema` | `db/migrations/**`, `prisma/schema.prisma` |
| `env-config` | `.env*`, `config/**`, `**/settings.py` |
| `workflow-ci` | `.github/workflows/**`, `Dockerfile*`, `infra/**` |
| `auth-permission` | `**/auth/**`, `**/rbac/**`, `**/permissions/**` |
| `docs-only` | 모든 파일이 `docs/**`, `**/*.md`, `**/*.rst` 패턴일 때만 |
| `test-only` | 모든 파일이 `tests/**`, `**/*.test.*` 패턴일 때만 |

`docs-only` / `test-only`는 단독 분류 조건 — 코드 파일 1개라도 포함되면 적용 안 됨.

---

## 정책 파일 형식 (.drift-gate.yml)

```yaml
rules:
  - id: api-contract-sync
    when:
      any_changed: ["src/routes/**", "openapi/**"]
    require:
      groups:
        - name: "API 계약 문서"
          any_changed: ["docs/spec.md", "docs/api/**"]
        - name: "릴리즈 공지"
          all_changed: ["CHANGELOG.md"]
    severity: blocker
    message: "API surface changed without synced contract/docs"

gate:
  fail_on_blocker: true
  fail_on_major_count: 2

ignore_paths:
  - "src/internal/**"
```

**ignore_paths 주의**: 트리거(when)와 충족(require) 양쪽에서 제외됨.
`docs/**`, `tests/**` 같이 require.groups에서 사용하는 경로는 여기에 넣지 말 것.

---

## drift-ignore 정책

PR description에서 파싱:
```
drift-ignore: <rule-id>
reason: <이유>
```

| 심각도 | reason 있음 | reason 없음 |
|--------|------------|------------|
| BLOCKER/MAJOR | skipped_rules → 규칙 생략 | **rejected_ignores → 규칙 유지** |
| MINOR/NIT | skipped_rules → 규칙 생략 | skipped_rules → 생략 |

---

## JSON 출력 계약

`EvaluationResult.to_dict()` 스키마:

```json
{
  "summary": {"blocker": 0, "major": 0, "minor": 0, "nit": 0, "gate_decision": "pass"},
  "result": "pass | warn | fail",
  "change_types": ["api-surface"],
  "violations": [{
    "rule_id": "...", "severity": "BLOCKER",
    "confidence": "high | medium | low",
    "change_types": ["api-surface"], "change_type": "api-surface",
    "message": "...", "trigger_files": [...],
    "unsatisfied_groups": [{"name": "...", "required": [...], "type": "any_changed"}],
    "checklist": ["..."], "ignored": false
  }],
  "skipped_rules": [{"rule_id": "...", "severity": "...", "reason": "...", "message": "..."}],
  "rejected_ignores": [{"rule_id": "...", "severity": "...", "message": "..."}],
  "gate": {"fail_on_blocker": true, "fail_on_major_count": 2}
}
```

---

## CI 게이트 판정

```
docs-only / test-only PR        → pass (평가 생략)
BLOCKER ≥ 1 + fail_on_blocker   → fail
MAJOR ≥ fail_on_major_count     → fail
MAJOR ≥ 1 또는 MINOR ≥ 1       → warn
위반 없음                       → pass
```

---

## 개발 원칙

- core 내부에서 GitHub API, subprocess, print, sys.exit 사용 금지
- 모든 외부 I/O는 adapters에서만
- LLM 없이 core gate 판정 완전 동작
- false positive 줄이기가 기능 추가보다 중요
- 새 규칙은 코드가 아닌 .drift-gate.yml로만
