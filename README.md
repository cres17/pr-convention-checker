# Drift Gate

**코드는 바뀌었는데 API 문서와 설정 예제는 그대로인 PR을 찾습니다.**

Drift Gate는 코드 변경에 따라 함께 확인해야 할 문서를 검사하는 개발 도구입니다. 팀의 규칙을 YAML로 정하고, 로컬 CLI나 GitHub Actions에서 실행합니다. 누락된 항목과 판정 근거는 Markdown·JSON·HTML 보고서로 확인할 수 있습니다.

[![CI](https://github.com/cres17/pr-convention-checker/actions/workflows/ci.yml/badge.svg?branch=ver2)](https://github.com/cres17/pr-convention-checker/actions/workflows/ci.yml?query=branch%3Aver2)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[시작하기](#시작하기) · [사용 흐름](#사용-흐름) · [검증 결과](#검증-결과) · [버전별 변경](#버전별-변경) · [문서 모음](#문서-모음)

> **현재 브랜치: `ver2` — 내용 검증을 확장하는 개발 버전입니다.** 기존 테스트는 통과하지만, 새 반례에서 오탐과 미탐이 확인됐습니다. 적용 전 [지원 범위와 한계](#지원-범위와-한계)를 확인해 주세요.

## 어떤 문제를 해결하나요?

API 주소를 변경하고 테스트까지 고쳤더라도, 문서에는 이전 주소가 남을 수 있습니다. 새로운 환경변수를 읽도록 구현했는데 `.env.example`에 키가 없으면 다른 개발자는 실행에 필요한 설정을 놓치게 됩니다.

Drift Gate는 이런 누락을 코드 리뷰 전에 확인하도록 만들었습니다.

| 코드 변경 | 함께 확인할 대상 | 확인 방식 |
|---|---|---|
| API 메서드·경로 추가, 변경, 삭제 | API 문서 | 지원하는 형식에서 메서드·경로의 변경 내용 대조 |
| 정적인 환경변수 키 추가 | `.env.example` 등 설정 예제 | 현재 파일에 해당 키가 있는지 확인 |
| DB 스키마·마이그레이션 변경 | 운영 문서, 변경 이력 | 정책에 지정한 파일의 동반 수정 확인 |
| CI·인프라·인증 로직 변경 | 배포·보안 문서 | 정책에 지정한 파일의 동반 수정 확인 |

문서 전체의 의미가 코드와 같은지를 증명하는 도구는 아닙니다. **파일 동반 수정 검사**와 **일부 API·설정의 내용 검사**를 구분합니다. 통과·실패는 정책 엔진이 결정하며, 선택적으로 연결하는 Claude는 체크리스트 설명을 보완합니다.

## 사용 흐름

```mermaid
flowchart LR
    A[로컬 변경 또는 PR] --> B[변경 경로와 diff 수집]
    B --> C[변경 유형과 분석 근거 확인]
    P[팀의 YAML 정책] --> D[필요한 문서 검사]
    C --> D
    D --> E[통과 · 경고 · 실패]
    E --> F[보고서와 PR 리뷰]
```

1. **규칙을 정합니다.** 어떤 경로의 변경에 어떤 문서가 필요한지 `.drift-gate.yml`에 작성합니다.
2. **변경을 검사합니다.** 경로와 diff를 분석하고, 사용할 수 있는 문법 분석 신호를 추가합니다. 분석이 불가능하거나 휴리스틱으로 대체된 경우 보고서에 근거를 남깁니다.
3. **결과를 확인합니다.** 누락된 문서를 보완하거나 정해진 예외 절차를 따릅니다. 승인 필수 예외는 PR 본문에 이름만 적는 것으로 허용되지 않습니다.

### 검사 예시

`@app.get('/users')`를 `@app.get('/members')`로 변경했다면:

| 함께 변경한 내용 | 내용 검사 결과 |
|---|---|
| API 문서 없음 | 실패 |
| 다른 문서의 오타만 수정 | 실패 |
| 문서의 `GET /users`를 `GET /members`로 수정 | 통과 |

위 예시는 한 줄로 작성한 라우트와 `GET /members` 형태의 문서에 해당합니다. Markdown 표와 중첩 OpenAPI YAML은 현재 같은 방식으로 처리하지 못합니다.

## 시작하기

Python 3.10 이상과 Git이 필요합니다. 아래는 macOS·Linux 기준입니다. Windows에서는 `python3` 대신 `py`를 사용하고, 가상환경은 `.venv\Scripts\Activate.ps1`로 활성화합니다.

### 먼저 예제 보고서 보기

```bash
git clone --branch ver2 https://github.com/cres17/pr-convention-checker.git
cd pr-convention-checker
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
drift-gate demo
```

생성된 `benchmark.html`을 브라우저로 열면 저장소에 포함된 합성 사례의 판정과 근거를 볼 수 있습니다. 실제 서비스 PR을 검사한 결과는 아닙니다. Tree-sitter 문법을 처음 읽을 때는 다운로드가 필요할 수 있습니다.

### 내 저장소에 적용하기

설치한 가상환경이 활성화된 상태에서 **검사할 Git 저장소로 이동**합니다.

```bash
drift-gate init --preset api
```

생성된 `.drift-gate.yml`의 코드·문서 경로를 프로젝트에 맞게 수정합니다. 정책 파일이 이미 있다면 초기화 대신 기존 파일을 편집하세요. 변경한 새 파일은 Git에 추가한 후 검사합니다. 아직 추적하지 않는 파일은 로컬 diff에 포함되지 않습니다.

```bash
drift-gate check --base HEAD --explain
```

`HEAD`와 현재 작업 트리를 비교하므로 커밋 전 확인에 사용할 수 있습니다. 이미 커밋한 변경을 비교하려면 `--base main`처럼 실제 기준 브랜치를 지정합니다.

| 필요한 작업 | 명령 |
|---|---|
| HTML 보고서 저장 | `drift-gate report --base HEAD --out-html report.html` |
| JSON 결과 확인 | `drift-gate check --base HEAD --json` |
| CLI·정책 문서의 정합성 확인 | `drift-gate docs-check README.md --json` |
| 기존 평가 사례 전체 실행 | `drift-gate-eval --recursive --compare-baseline` |

## 정책 작성

예를 들어 다음 정책은 API 계약 수준의 변경이 있을 때 API 문서를 확인합니다.

```yaml
rules:
  - id: api-doc-sync
    when:
      any_changed: ["src/routes/**"]
      min_change_intensity: route-contract-change
    require:
      groups:
        - name: API 문서
          any_changed: ["docs/api/**"]
          content: api-routes
    severity: blocker
```

`content`는 문서를 어떻게 확인할지 정합니다.

| 값 | 용도 |
|---|---|
| `paths` | 지정한 문서 파일이 함께 수정됐는지만 확인 |
| `api-routes` | 문서 diff에서 인식 가능한 HTTP 메서드·경로 변경 확인 |
| `env-keys` | 명시한 설정 예제 파일에서 새 환경변수 키 확인 |
| `auto` — 기본값 | 인식 가능한 API 변경·문서 경로에는 내용 검사, 그 외에는 경로 검사 |

`api-routes`도 앞 단계에서 규칙이 발동한 변경만 검사합니다. 현재 HEAD·OPTIONS 변경을 놓치는 문제가 있으므로 엄격 모드라는 이름만으로 전체 탐지를 보장하지 않습니다. 기존 동작을 유지하려면 `paths`를 명시할 수 있지만, 이 경우 무관한 문서 수정도 조건을 충족할 수 있습니다.

환경변수 정책과 승인 예외 설정은 [내용 검증 안내](docs/content-verification.md)를 참고하세요.

## GitHub Actions 연결

검사할 저장소에 정책 파일을 커밋한 뒤 `.github/workflows/drift-gate.yml`을 추가합니다.

```yaml
name: Drift Gate
on:
  pull_request:
    types: [opened, synchronize, reopened]
permissions:
  contents: read
  pull-requests: write
jobs:
  drift-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v4
        with:
          python-version: "3.11"
      - uses: cres17/pr-convention-checker@ver2
```

기본 설정은 PR 댓글과 보고서 파일을 남기고, 정책 결과가 `fail`이면 작업을 실패 처리합니다. `ver2`는 변경될 수 있는 개발 브랜치입니다. 검증을 마친 버전을 계속 사용하려면 해당 커밋 SHA를 지정하세요.

<details>
<summary>주요 설정과 선택 기능</summary>

| 입력 | 기본값 | 설명 |
|---|---|---|
| `policy_file` | `.drift-gate.yml` | 정책 파일 경로 |
| `post_comment` | `true` | PR 댓글 게시 여부 |
| `fail_on_blocker` | `true` | 정책 결과가 실패일 때 작업 실패 처리 |
| `upload_report_artifact` | `true` | 생성한 보고서를 Actions 실행 결과에 보관 |
| `anthropic_api_key` | 없음 | Claude 체크리스트 보완 사용 |

Claude 연결은 필수가 아닙니다. API 키를 설정하지 않아도 정책 검사와 보고서 생성은 동작합니다. 전체 입력·출력은 [action.yml](action.yml), MCP·플러그인 구성은 [플러그인 메타데이터](.claude-plugin/plugin.json)를 참고하세요.

</details>

## 검증 결과

**개선은 확인했지만, 일반적인 PR 정확도는 아직 측정하지 않았습니다.** 기존 커밋과 개선본을 같은 환경·입력으로 실행했습니다. 아래 수치는 각각의 평가셋에만 해당하며, 서로 합산하지 않습니다.

| 검증 항목 | 개선 전 | ver2 개선본 | 읽는 방법 |
|---|---:|---:|---|
| 기존 합성 사례 | 22/22 | 22/22 | 기존 기대 동작 유지 |
| 개발 목표 사례 | 4/8 | 8/8 | 구현에 사용한 인수 기준 충족 |
| 별도 환경변수 사례 | 5/8 | 8/8 | 개발 중 만든 정적 키 검사 사례 |
| **새 반례: 지원 범위** | **10/24** | **17/24** | 사후 검증에서 +7개, 여전히 7개 실패 |
| 정상 변경을 잘못 차단 — 새 반례 | 5/12 | 4/12 | 오탐 1건 감소 |
| 누락을 놓침 — 새 반례 | 9/12 | 3/12 | 미탐 6건 감소 |
| **새 반례: 확장·형식 경계** | **2/8** | **0/8** | 정상 문서 형식 2개를 추가로 잘못 차단 |
| 전체 pytest | 470/471 | 524/524 | 기존 실패 1개 수정 + 테스트 53개 추가 |
| 파서 직접 실행 | 0/3 | 3/3 | Python·TypeScript·Go 호출 확인 |

새 반례는 구현 후 기대 판정을 고정하고, 제품 코드를 바꾸지 않은 채 두 버전에 적용했습니다. 다만 코드를 본 작성자가 만든 합성 데이터이므로 독립·블라인드 검증은 아닙니다. **8/8 통과를 정확도 100%로 표현할 수 없고, 17/24도 실제 PR의 정확도 추정치가 아닙니다.**

실행 환경, 사례별 판정, 소스·입력 해시와 재현 명령은 [과적합 점검 및 비교 검증](docs/generalization-audit-2026-09-22.md)에 있습니다. 전체 테스트 통과와 실제 GitHub 권한 환경의 정상 동작 여부는 별개의 검증입니다.

## 지원 범위와 한계

- **문자열·줄 끝 주석 오탐:** 코드처럼 보이는 예시 문자열이나 주석을 실제 라우트·설정 접근으로 해석할 수 있습니다.
- **일부 계약 변경 미탐:** HEAD·OPTIONS, 라우터 prefix, 요청·응답 스키마 변경을 놓칩니다. 문서에 이전 경로를 다시 추가해도 통과하는 반례가 있습니다.
- **문서 형식 제약:** Markdown 표·중첩 OpenAPI YAML의 올바른 수정도 내용 검사에서 차단할 수 있습니다.
- **설정 검사 제약:** 정적 키 위주이며, 별칭·동적 키를 충분히 다루지 못합니다. 기존 키 사용 코드만 정리했는데 차단되는 반례도 있습니다.
- **실사용 검증 부족:** 실제 PR 표본 평가, 리뷰 시간 절감, 조직 권한을 사용한 승인 검증은 아직 측정하지 않았습니다.

다음 개선은 이 문제들을 재현하는 테스트를 유지하면서, 전체 파일의 변경 전후 구조 비교와 별도의 실제 PR 평가셋을 추가하는 데 초점을 둡니다. [우선순위와 완료 기준](docs/generalization-audit-2026-09-22.md#다음-개선-순서)을 확인할 수 있습니다.

## 기술 스택

| 영역 | 사용 기술 | 선택한 역할 |
|---|---|---|
| 정책 엔진 | Python 3.10+, PyYAML | YAML 규칙을 읽고 같은 입력에 같은 판정 생성 |
| 변경 분석 | Git diff, 정규식·휴리스틱, Tree-sitter | 변경 구간의 유형과 문법 신호 추출 |
| 실행·연동 | CLI, GitHub REST API, GitHub Actions, MCP | 로컬과 PR 리뷰에서 같은 엔진 사용 |
| 보고서 | Markdown, JSON, HTML | 사람이 읽는 근거와 자동화용 결과 제공 |
| 검증 | pytest, Ruff, 고정 JSON 사례 | 회귀 검사와 원본·개선본 재현 비교 |
| 선택 기능 | Claude API | 판정을 바꾸지 않는 체크리스트 설명 보완 |

핵심 판정은 `core`, 외부 데이터 수집은 `adapters`, 출력은 `reporters`로 나눴습니다. Tree-sitter를 사용하지만 현재 내용 검증에는 정규식과 휴리스틱이 함께 쓰입니다. 전체 프로그램 의미를 분석하는 AST 검증기로 보지는 않습니다.

## 버전별 변경

| 구분 | 주요 내용 | 현재 상태 |
|---|---|---|
| **v1** — 기존 `v1`·`v1.0.0` 태그 | YAML 정책, 코드·문서 동반 수정 검사, CLI·Action·MCP, 보고서와 기존 평가 도구 | 기존 배포 참조 |
| **ver2** — 현재 개발 브랜치 | 파서 호환성 복구, 삭제·분석 입력 누락 처리, API·환경변수 내용 검사, 승인 근거 검증, 전후 측정 자료 | 구현 및 로컬 검증, 사후 반례의 실패 항목 공개 |
| **다음 개선** — 미구현 | 문자열·주석 구분, 인식 단계 통일, 문서 순변경 비교, 문서 형식 확장, 실제 PR 평가 | [개선 계획](docs/generalization-audit-2026-09-22.md#다음-개선-순서) |

`ver2`는 브랜치명이며 `v2.0.0` 릴리스를 뜻하지 않습니다. Python 패키지 버전은 현재 `1.0.0`, Claude 플러그인 버전은 `0.2.0`으로 각각 별도 관리되고 있습니다.

## 문서 모음

| 목적 | 문서 |
|---|---|
| 개선 전후 결과를 검토하고 싶을 때 | [사후 검증·비교표](docs/generalization-audit-2026-09-22.md) · [1차 구현 결과](docs/development-results-2026-09-22.md) |
| 다음 개발 범위를 확인할 때 | [개선 계획과 기준값](docs/development-roadmap.md) |
| 내용 검사와 예외 승인을 설정할 때 | [내용 검증 안내](docs/content-verification.md) |
| 탐지 규칙·기존 설정을 이해할 때 | [탐지기 안내](docs/detector-guide.md) · [마이그레이션](docs/migration-guide.md) |
| 프레임워크별로 적용할 때 | [FastAPI](examples/fastapi/README.md) · [Express](examples/express-api/README.md) · [Next.js](examples/nextjs/README.md) · [Django](examples/django/README.md) · [Prisma](examples/prisma/README.md) |
| 실행 문제를 해결할 때 | [문제 해결](docs/troubleshooting.md) |

## 개발과 테스트

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
```

측정 자료는 `docs/assessment/`에 보존합니다. 새로운 결과는 기존 파일을 덮어쓰지 않고 다른 경로에 저장합니다.

Claude를 활용해 혼자 개발한 개인 프로젝트입니다. 현재 공개한 성과는 저장소의 코드와 재현 가능한 테스트 결과에 한정하며, 서비스 운영 효과는 별도로 검증할 예정입니다.

[MIT License](LICENSE)
