<div align="center">

<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/brand/drift-gate-wordmark-dark.png">
    <img src="docs/assets/brand/drift-gate-wordmark-light.png" alt="Drift Gate" width="520">
  </picture>
</h1>

코드가 바뀌었는데 문서가 따라오지 않은 PR을 찾아내는 정책 엔진

[![CI](https://github.com/cres17/pr-convention-checker/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/cres17/pr-convention-checker/actions/workflows/ci.yml?query=branch%3Amain)
[![License: MIT](https://img.shields.io/badge/License-MIT-8B5CF6)](LICENSE)

![Python 3.10+](https://img.shields.io/badge/Python%203.10%2B-3776AB?style=flat&logoColor=white&logo=python)
![Tree-sitter](https://img.shields.io/badge/Tree--sitter-2B3443?style=flat&logoColor=white)
![GitHub REST API](https://img.shields.io/badge/GitHub%20REST%20API-181717?style=flat&logoColor=white&logo=github)
![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-2088FF?style=flat&logoColor=white&logo=githubactions)
![MCP](https://img.shields.io/badge/MCP-000000?style=flat&logoColor=white&logo=modelcontextprotocol)
![PySide6](https://img.shields.io/badge/PySide6-41CD52?style=flat&logoColor=black&logo=qt)
![React 19](https://img.shields.io/badge/React%2019-61DAFB?style=flat&logoColor=black&logo=react)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat&logoColor=white&logo=typescript)
![Claude API](https://img.shields.io/badge/Claude%20API-D97757?style=flat&logoColor=white&logo=claude)
![pytest](https://img.shields.io/badge/pytest-0A9EDC?style=flat&logoColor=white&logo=pytest)

</div>

API 경로를 바꿨는데 명세에는 이전 주소가 남아 있거나, 새 환경변수를 쓰는데 `.env.example`에 키가 없는 경우를 PR 단계에서 잡습니다. 팀이 `.drift-gate.yml`에 "이 코드가 바뀌면 이 문서도 바뀌어야 한다"는 규칙을 적으면, 변경 내용을 분석해 필요한 문서의 누락을 판정하고 근거를 보고서로 남깁니다. 같은 엔진을 로컬 CLI, GitHub Actions, 데스크톱 앱, MCP 서버에서 그대로 씁니다.

| 코드 변경 | 확인하는 문서 | 검사 방식 |
|-----------|--------------|----------|
| API 메서드 · 경로 | API 명세 | 추가 · 삭제된 메서드와 경로를 문서 diff와 대조 |
| 환경변수 키 | `.env.example` 등 | 새 키 누락, 코드에서 지운 키의 잔존 확인 |
| DB 스키마 · CI · 인프라 · 인증 | 운영 · 배포 · 보안 문서 | 지정한 문서의 동반 수정 확인 |

통과 · 실패는 규칙 엔진이 결정하고, LLM은 판정 뒤에 설명을 보태는 선택 기능입니다. 검증 기록은 [docs](docs)와 [계획](계획.md)에 공개합니다.

## 전체 아키텍처

<p align="center">
  <img src="docs/assets/readme/architecture.svg" alt="Drift Gate 전체 아키텍처" width="100%">
</p>

| 단계 | 하는 일 | 코드 |
|------|--------|------|
| 입력 | 로컬 Git diff 또는 GitHub PR의 변경 파일 · patch와 정책 YAML을 읽음 | `adapters/git`, `adapters/github`, `core/policy` |
| 신호 추출 | 변경된 코드에서 라우트 · 환경변수 접근 · 공개 선언을 Tree-sitter로 추출, 불완전한 diff는 휴리스틱으로 대체하고 그 사유를 기록 | `adapters/ast` |
| 정책 평가 | `when` 조건에 맞는 규칙의 `require.groups`를 확인하고, 승인된 예외를 CODEOWNERS · 리뷰 승인으로 검증 | `core/classification`, `core/trust` |
| 판정 | 심각도에 따라 pass · warn · fail · 검사 대상 없음을 결정 | `core/gating` |
| 출력 | Markdown · JSON · HTML 보고서, PR 댓글, Action artifact | `reporters`, `adapters/github` |

```text
drift_gate/
├── core/          정책 모델 · 분류 · 판정 · 예외 신뢰 검증 (외부 I/O 없음)
├── adapters/      git · github · ast · cli · github_action · mcp · claude · eval
├── reporters/     markdown · json · html
├── desktop/       PySide6 앱과 React 빌드 결과(web/)
└── tests/         단위 · 통합 테스트와 고정 평가 사례
desktop-ui/        데스크톱 화면 React 소스
examples/          FastAPI · Django · Express · Next.js · Prisma · Actions 배포용 정책 예제
```

## 핵심 설계 결정

| 결정 | 방식 | 위치 |
|------|------|------|
| 판정은 규칙 엔진, LLM은 설명만 | 통과 · 실패는 정책 평가 결과로만 정해지고, Claude는 판정이 끝난 위반 목록에 리뷰어용 체크리스트와 설명을 덧붙입니다. API 키가 없으면 건너뜁니다. | `core/gating`, `adapters/claude/enricher.py` |
| PR이 자신을 심판하는 정책을 바꾸지 못하게 | Action의 `policy_source` 기본값은 `base`라서 PR의 base 커밋에 있는 정책으로 판정합니다. PR 작성자가 믿을 수 있을 때만 `workspace`를 씁니다. | `action.yml` |
| 예외는 사유와 승인을 요구 | PR 본문의 `drift-ignore: <rule-id>`는 BLOCKER · MAJOR 규칙이면 사유가 있어야 받아들이고, 승인자 이름만 적은 것은 승인으로 인정하지 않습니다. 승인은 base 브랜치의 CODEOWNERS와 현재 리뷰 승인을 대조합니다. | `adapters/github/approvals.py`, `core/trust` |
| 확인하지 못한 것은 확인했다고 하지 않음 | 파싱에 실패하거나 diff 조각이 불완전하면 정규식 휴리스틱으로 넘어가고 어떤 방법을 썼는지 보고서에 표시합니다. 경로만 확인한 PASS에는 `unverified`와 "내용을 검증한 것이 아님" 문구가 붙습니다. | `adapters/ast`, `reporters` |
| 코어는 외부 I/O 없이 | 정책 모델 · 분류 · 판정 · 예외 신뢰 검증은 `core`에 두고 git · GitHub · AST · CLI는 `adapters`에 분리해, 같은 엔진을 CLI · Action · 데스크톱 · MCP에서 그대로 씁니다. `core`는 mypy로 검사합니다. | `drift_gate/core`, `drift_gate/adapters` |
| 배포하는 파서 라이브러리를 해시로 확인 | Tree-sitter 파서는 `tree-sitter-language-pack`에서 불러오고, 배포본에 넣는 파서 라이브러리는 `parser_hashes.json`의 해시와 대조합니다. | `drift_gate/adapters/parser_hashes.json`, `.github/workflows/parser-hashes.yml` |

## 빠른 시작

Python 3.10 이상이 필요합니다.

```bash
pip install -e .
drift-gate init --preset api     # auto · api · auth · ci · db · env · focused-python · fullstack
drift-gate check --base HEAD     # 작업 트리 변경을 정책으로 검사
```

FastAPI 라우트를 추가하고 명세(`docs/openapi.yaml`)는 고치지 않은 작업 트리에서 아래 정책으로 `drift-gate check --base HEAD`를 실행한 결과입니다.

```yaml
rules:
  - id: api-contract-sync
    severity: major
    message: API 라우트가 바뀌었는데 명세가 바뀌지 않았습니다
    when:
      any_changed: ["app/**"]
    require:
      groups:
        - name: API 명세
          any_changed: ["docs/openapi.yaml"]
```

| 상태 | 판정 | 보고서 내용 |
|------|------|------------|
| 명세를 고치지 않음 | `WARN` (MAJOR 1건, 종료 코드 0) | 트리거 `app/main.py`, 누락 문서 `docs/openapi.yaml`, 체크리스트 `API 명세 업데이트`, diff 근거, `drift-ignore` 예외 안내 |
| `docs/openapi.yaml` 수정 | `PASS` (위반 0건) | 경로 변경만 확인했으므로 `Verification: unverified` 표시 |

심각도에 따라 `warn` 또는 `fail`로 판정합니다. 프레임워크별 정책 예제는 [examples](examples)에 있습니다.

## GitHub Action

`action.yml`(composite action)의 주요 입력입니다.

| 입력 | 기본값 | 용도 |
|------|--------|------|
| `policy_file` | `.drift-gate.yml` | 정책 파일 경로 |
| `policy_source` | `base` | `base`는 PR base 커밋의 정책, `workspace`는 체크아웃된 PR의 정책 |
| `post_comment` | `true` | 결과를 PR 댓글로 게시 (`<!-- drift-gate-v1 -->` 마커로 기존 댓글을 갱신) |
| `fail_on_blocker` | `true` | 판정이 fail이면 job 실패 |
| `upload_report_artifact` | `true` | Markdown · JSON · HTML 보고서를 artifact로 업로드 |
| `anthropic_api_key` | (없음) | 선택. 체크리스트 설명 생성용 |

출력으로 `result`(pass / warn / fail / skip), `blocker_count`, `major_count`, `violation_count`, `policy_origin`, `comment_url`을 제공합니다.

## 검증

```bash
pip install -e ".[dev]"
ruff check drift_gate/ --select=E9,F
mypy drift_gate/core --ignore-missing-imports
pytest drift_gate/tests
drift-gate demo                  # 합성 21개 사례로 경로 기준 방식과 patch 분석 방식을 비교
```

`ci.yml`은 Ruff · mypy(core) job과 별도로 Ubuntu · Windows · macOS × Python 3.10 · 3.11 · 3.12의 9개 조합에서 pytest를 실행합니다. `benchmark.yml`은 합성 평가셋의 탐지 결과를, `parser-hashes.yml`은 파서 해시를 확인합니다. 평가셋은 작성자가 만든 합성 사례이며 원자료는 [`docs/assessment`](docs/assessment)에 있습니다.

## 기술 구성

| 기술 | 용도 | 위치 |
|------|------|------|
| PyYAML — 정책 파일 | 규칙은 `when.any_changed`(트리거 경로), `require.groups`(함께 바뀌어야 할 문서 묶음), `severity`, `message`로 구성. 모든 묶음을 만족해야 통과하고 하나라도 비면 위반 | `core/policy/loader.py`, `validator.py` |
| Tree-sitter | Python · TypeScript/JavaScript는 라우트 데코레이터 · Express 라우트 · 환경변수 접근을, Go · Java · Kotlin · Ruby는 공개 함수와 타입 선언을 추출 | `adapters/ast` |
| Git · GitHub REST API | 로컬은 `git diff`, PR은 REST API로 변경 파일 목록과 patch 수집 | `adapters/git`, `adapters/github` |
| CLI | `check`가 기본이고 `report` · `explain` · `doctor` · `demo` · `holdout` 등의 하위 명령 | `adapters/cli` |
| MCP 서버 | 외부 SDK 없이 JSON-RPC를 stdio로 주고받는 서버(`drift-gate-mcp`). MCP 클라이언트가 정책 조회와 검사를 도구로 호출 | `adapters/mcp/server.py` |
| PySide6 · React — 데스크톱 앱 | Qt WebEngine 창에 React 화면을 띄우고 QWebChannel로 Python 검사 서비스와 연결. 저장소를 고르면 규칙별 근거와 diff를 보여 주고 보고서를 저장. `desktop-build.yml`이 PyInstaller로 Windows · macOS 패키지 생성 | `drift_gate/desktop/web_app.py`, `desktop-ui` |
| Claude API · Codex · Claude Code (선택) | 위반 목록에 대한 체크리스트와 설명. 데스크톱 앱의 구독 검토는 로그인한 Codex CLI 또는 Claude Code를 하위 프로세스로 실행하고, 보내기 전에 전송 내용을 미리 보여 주며 도중에 중지 가능 | `adapters/claude/enricher.py`, `desktop/subscription_review.py` |
