# Spec/Contract Drift Gate

PR 변경분을 분석해 코드 변경이 팀의 계약 문서(spec/contract/acceptance/runbook/release note)와
어긋났는지 자동 점검하는 정책 집행형 GitHub Action + Claude Plugin입니다.

---

## 프로젝트 핵심 개념

이 도구의 핵심은 **AI 리뷰**가 아니라 **문서-코드 정합성 정책 엔진**입니다.

- 코드 스타일, 버그, 보안 취약점을 잡는 게 목적이 아닙니다.
- `spec.md`, `contract.md`, `acceptance.md`, `runbook.md`, `CHANGELOG.md`, `.env.example` 같은
  팀 계약 문서와 실제 코드 변경이 **얼마나 동기화되어 있는가**를 판정합니다.
- LLM은 ambiguous한 경우에만 사용하고, 확실한 패턴은 경로 규칙으로 처리합니다.

---

## 모듈 구조

```
collectors/   — git diff, GitHub API로 변경 파일/diff 수집
detectors/    — API, DB, env, workflow, auth 변경 유형 감지 (규칙 기반 + LLM 혼합)
policies/     — 팀별 규칙 정의 YAML (.drift-gate.yml)
reasoners/    — LLM 프롬프트, 근거 생성
reporters/    — markdown/json/github comment 출력
gates/        — fail/pass 기준 집행
```

가장 중요한 모듈은 `policies/`입니다. 정책 파일의 품질이 재사용성과 정확도를 결정합니다.

---

## 변경 유형 분류

PR diff와 변경 파일을 읽어 아래 카테고리로 분류합니다.
복수 카테고리 동시 적용 가능합니다.

단, `docs-only`, `test-only`는 **보조 라벨이 아니라 단독 분류 조건**입니다.
즉, 아래 조건을 만족할 때만 해당됩니다.

- `docs-only`: 모든 변경 파일이 문서 패턴(`docs/**`, `**/*.md`, `**/*.rst`)에만 해당할 때
- `test-only`: 모든 변경 파일이 테스트 패턴(`tests/**`, `**/*.test.*`, `**/*.spec.*`)에만 해당할 때

코드/설정/인프라 파일이 1개라도 포함되면 `docs-only`, `test-only`로 분류하지 않습니다.

| 유형 | 트리거 경로 예시 |
|------|----------------|
| `api-surface` | `src/routes/**`, `openapi/**`, `proto/**`, `src/controllers/**` |
| `db-schema` | `db/migrations/**`, `prisma/schema.prisma`, `sql/**`, `**/schema.sql` |
| `env-config` | `.env`, `.env.local`, `.env.production`, `config/**`, `src/config/**`, `**/settings.py` |
| `workflow-ci` | `.github/workflows/**`, `Dockerfile*`, `infra/**`, `terraform/**` |
| `auth-permission` | `**/auth/**`, `**/middleware/auth*`, `**/rbac/**`, `**/permissions/**` |
| `docs-only` | `docs/**`, `**/*.md`, `**/*.rst` |
| `test-only` | `tests/**`, `**/*.test.*`, `**/*.spec.*` |

분류는 규칙 기반 우선입니다.
경계가 모호한 경우에만 LLM을 사용하며, 이 경우 결과에 `confidence: low`를 부여합니다.

### 파일 상태 처리 규칙

`changed_files[].status` 는 `added`, `modified`, `deleted`, `renamed` 중 하나로 가정합니다.

- `deleted`: 요구 산출물이 삭제된 경우, 해당 규칙 위반 가능성을 우선 검토합니다.
- `renamed`: rename 전후 경로를 모두 고려해 규칙을 평가합니다.
- `modified`: patch가 비어 있어도 changed path 자체는 규칙 판정에 사용합니다.
## 정책 파일 형식 (.drift-gate.yml)

레포 루트에 `.drift-gate.yml`을 두면 팀 규칙을 정의할 수 있습니다.

```yaml
rules:
  - id: api-contract-sync
    when:
      any_changed:
        - "src/routes/**"
        - "openapi/**"
        - "proto/**"
        - "src/controllers/**"
    require:
      groups:
        - name: "API 계약 문서"
          any_changed:
            - "docs/spec.md"
            - "docs/api/**"
        - name: "릴리즈 공지"
          all_changed:
            - "CHANGELOG.md"
    severity: blocker
    message: "API surface changed without synced contract/docs"

  - id: schema-migration-proof
    when:
      any_changed:
        - "db/migrations/**"
        - "prisma/schema.prisma"
        - "sql/**"
    require:
      groups:
        - name: "운영 문서"
          any_changed:
            - "docs/runbook/**"
            - "docs/migration-notes/**"
        - name: "검증 흔적"
          any_changed:
            - "tests/integration/**"
            - "tests/e2e/**"
    severity: major
    message: "DB schema changed without migration note/runbook or verification test"

  - id: env-config-sync
    when:
      any_changed:
        - ".env"
        - ".env.local"
        - ".env.production"
        - "config/**"
        - "src/config/**"
    require:
      groups:
        - name: "샘플 환경변수"
          all_changed:
            - ".env.example"
        - name: "배포 문서"
          any_changed:
            - "docs/deployment/**"
            - "docs/runbook/**"
    severity: major
    message: "env/config changed without .env.example or deployment docs update"

  - id: workflow-ops-doc
    when:
      any_changed:
        - ".github/workflows/**"
        - "infra/**"
        - "terraform/**"
        - "Dockerfile*"
    require:
      groups:
        - name: "운영 문서"
          any_changed:
            - "docs/ops/**"
            - "docs/runbook/**"
    severity: minor
    message: "CI/infra changed without ops documentation update"

gate:
  fail_on_blocker: true
  fail_on_major_count: 2

ignore_paths:
  - "src/internal/**"
  - "scripts/dev/**"


---

## C. `정책 필드 정의` 섹션 교체본

```md
### 정책 필드 정의

| 필드 | 설명 |
|------|------|
| `id` | 규칙 식별자. `drift-ignore: <id>` 로 무시 가능 |
| `when.any_changed` | 이 경로 중 하나라도 변경되면 규칙 활성화 |
| `require.groups` | 통과를 위해 만족해야 하는 요구 묶음 목록 |
| `require.groups[].name` | PR 코멘트/리포트에 표시할 요구 묶음 이름 |
| `require.groups[].any_changed` | 이 묶음 안의 경로 중 하나라도 변경되면 묶음 충족 |
| `require.groups[].all_changed` | 이 묶음 안의 경로가 모두 변경되어야 묶음 충족 |
| `severity` | `blocker` / `major` / `minor` / `nit` |
| `message` | 위반 시 표시할 기본 설명 |
| `ignore_paths` | drift 규칙 평가에서 제외할 경로 |
| `gate.fail_on_blocker` | BLOCKER 1개 이상일 때 CI 실패 여부 |
| `gate.fail_on_major_count` | MAJOR 누적 기준 이상이면 CI 실패 |

### 평가 규칙

- `when`이 충족되면 규칙이 활성화됩니다.
- 활성화된 규칙은 `require.groups`의 **모든 묶음**을 만족해야 통과합니다.
- 묶음 하나라도 불충족이면 해당 규칙은 위반입니다.
- `require.groups`가 없으면 잘못된 정책으로 간주하고 로드 단계에서 실패합니다.

## 심각도 및 CI 게이트 기준

```
BLOCKER  — 반드시 수정 후 머지. CI 실패 유발.
MAJOR    — 문서 누락/미동기화. 팀 논의 후 머지 또는 수정.
MINOR    — 경미한 누락. PR 코멘트는 남기되 블로킹하지 않음.
NIT      — 선호 수준. 참고만.
```

기본 CI 게이트 정책:

```yaml
gate:
  fail_on_blocker: true          # BLOCKER 1개 이상 → CI 실패
  fail_on_major_count: 2         # MAJOR 2개 이상 → CI 실패
  # MINOR만 있으면 통과, PR 코멘트만 남김
```

---

## False Positive 억제

특정 규칙을 의도적으로 무시하려면 PR description 또는 커밋 메시지에 추가합니다:

```text
drift-ignore: api-contract-sync
reason: internal refactor only, no externally visible contract change
ref: #456
```

파일 단위로 무시하려면 `.drift-gate.yml`에 추가:

```yaml
ignore_paths:
  - "src/internal/**"
  - "scripts/dev/**"
```

---

## 출력 근거 리포트 형식

출력은 반드시 **Markdown 요약 + JSON 결과** 두 가지를 생성합니다.

### Markdown 위반 항목 형식

```text
[SEVERITY] <rule-id>  (confidence=low면 [추정] 표시)
  변경 유형: <유형>
  트리거 파일:
    - <changed file>
  누락 산출물:
    - <required artifact or group>
  왜 필요한가: <근거>
  체크리스트:
    - [ ] ...
    - [ ] ...
  무시하려면:
    drift-ignore: <rule-id>
    reason: <why>
```

---

## GitHub Actions 모드

PR 생성/업데이트 시 자동 실행됩니다.
결과는 PR 코멘트로 게시되며, BLOCKER 조건에서 CI를 실패시킵니다.

## Claude Plugin 모드 (로컬 프리플라이트)

`/drift-gate:review` 커맨드로 PR 올리기 전에 로컬에서 미리 점검합니다.
개발자가 누락 문서를 사전에 발견하고 수정할 수 있게 합니다.

---

## 개발 원칙

- 확실한 패턴은 경로 규칙(`policies/`)으로 처리하고 LLM에 의존하지 않습니다.
- LLM은 ambiguous한 변경 유형 분류와 근거 메시지 생성에만 씁니다.
- false positive를 줄이는 것이 기능 추가보다 중요합니다.
- 정책 파일(`.drift-gate.yml`)이 좋아야 재사용성이 생깁니다. 정책 품질에 집중합니다.
