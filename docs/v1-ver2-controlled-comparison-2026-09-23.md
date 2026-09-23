# 실제 v1 태그와 ver2의 통제 비교

실험일: 2026-09-23 · 대상: [`v1` 태그](https://github.com/cres17/pr-convention-checker/tree/v1) (`13a5ded`)와 [`ver2` 기준 커밋](https://github.com/cres17/pr-convention-checker/commit/b9c2bd4b2afaca0fcf932f9e3fc1f1428e038cbd) (`b9c2bd4`)

## 결론

두 참조는 같은 검사기를 조금 고친 정도가 아니라 **검사 기준과 판정 주체가 바뀐 제품 단계**다. `v1`은 `CLAUDE.md` 같은 팀 규칙과 PR diff를 Claude API에 보내 해석을 맡겼다. `ver2`는 `.drift-gate.yml`의 문서 동기화 정책을 Python 엔진이 판정하고 Claude는 선택적으로 설명을 보완한다. `main`의 `bffc655`는 이미 Python 엔진을 포함하므로 실제 `v1` 태그와 혼동하면 안 된다.

이번 실험에서 같은 12개 합성 Git 변경을 두 버전의 실행 경로에 넣었다. **`ver2`의 일반 시나리오 11개 중 9개가 사전 기대 판정과 일치했고, 형식 경계 사례 1개는 실패했다.** `v1`은 실제 Claude 모델을 호출하지 않아 정확도를 측정하지 않았다. 대신 12개 모두 규칙과 diff가 모델 요청까지 전달됐고, 같은 프롬프트에 준비된 응답만 바꾸면 Action의 결과가 12개 모두 바뀌는 것을 확인했다. 따라서 `v1 0% → ver2 82%` 같은 성능 향상 표현은 근거가 없다.

## 실험 설계

### 1. 버전과 범위를 먼저 고정

| 항목 | v1 태그 | ver2 기준 커밋 |
|---|---|---|
| Git 커밋 | `13a5ded9ca03f67cf07d134421d5a1e1cd82b19e` | `b9c2bd4b2afaca0fcf932f9e3fc1f1428e038cbd` |
| 검사 기준 | `CLAUDE.md` 등 자연어 규칙 | `.drift-gate.yml`의 명시적 정책 |
| 핵심 판정 | Claude 응답 텍스트의 `[BLOCKER]` 등 표식 | Python 정책 엔진의 `pass/fail` |
| 실행 경로 | 태그의 `github-action/entrypoint.sh` | `main.py check --base … --json` |
| Claude API | Action 실행에 필수 | 정책 판정에는 불필요, 설명 보완에 선택적 |
| 동일하게 통제한 것 | 기준 파일·변경 파일·Git diff·문서 동기화 요구·실행 환경 | 동일 |
| 달라질 수밖에 없는 것 | 자연어 규칙과 외부 모델의 판단 | YAML 규칙과 결정적 평가 |

`v1`과 `v1.0.0` 태그는 같은 커밋을 가리킨다. 비교에 사용한 `ver2` 제품 코드는 이후 문서 커밋을 하더라도 바이트 단위 해시로 기준 커밋과 동일함을 확인한다.

### 2. 사례와 기대값을 실행 전에 기록

[12개 합성 사례](assessment/v1-ver2-controlled-2026-09-23/cases.json)의 기준 파일, 변경 파일, 기대값과 이유를 먼저 작성했다. API 경로 변경, 삭제, 무관한 문서 수정, 정상 구현 변경, 문자열 속 가짜 라우트, 환경변수 키와 샘플, HEAD 메서드, 문서만 수정한 경우를 포함했다. 정상 변경도 넣어 모두 차단하면 높은 점수를 받지 못하게 했다. Markdown 표는 별도 형식 경계로 구분했다.

각 사례에서 새 임시 Git 저장소를 만들고 같은 기준 커밋·변경 커밋을 두 실행 경로에 전달했다. 샘플 규칙은 각 제품의 문법에 맞게 `CLAUDE.md`와 `.drift-gate.yml`에 함께 썼다. **같은 정책 의도를 표현했지만 두 언어의 의미가 완전히 같다고 증명한 것은 아니다.**

[사전 프로토콜](assessment/v1-ver2-controlled-2026-09-23/protocol.md)에 지표·오탐/미탐 정의·제외 조건을 적었다. 사례 파일의 SHA-256은 `9c8202b9b73b5573ab6281adfd8a23f501f57cdd9879da7b89376606d50c391b`다. 작성자가 이미 두 제품의 코드를 본 상태여서 독립·블라인드 검증이 아니다.

### 3. 외부 모델을 통제하고 실행

`v1`은 **태그에 들어 있는 셸 스크립트를 그대로 실행**했다. `curl`만 로컬 가짜 응답기로 교체해 네트워크·API 키·비용을 없앴다. 같은 프롬프트에 `위반 없음`과 `[BLOCKER]` 두 응답을 각각 주고 Action이 기록하는 `result`와 모델 요청 여부를 관찰했다. 이 실험은 모델의 답변 능력이 아니라 **제품의 입력·게이트 연결 동작**을 테스트한다. 실제 GitHub Action의 댓글 게시와 최종 실패 단계는 실행하지 않았다. 셸 스크립트의 `result=fail`과 Action 설정의 후속 실패 단계는 구분해야 한다.

`ver2`는 같은 저장소에서 기준 커밋을 지정해 CLI의 실제 JSON 결과와 종료 코드를 기록했다. 매 사례를 연속 두 번 실행해 판정이 같은지도 확인했다. 파일명이나 개수를 바꾸지 않은 독립 임시 저장소 실행을 한 차례 더 수행했다. 두 최종 실행의 결과·입력/코드 해시는 시간 기록을 제외하고 모두 일치했다.

## 관측 결과

### ver2 판정

| 평가 범위 | 기대값 일치 | 정상 변경 오차단(FP) | 누락 미탐(FN) | 해석 |
|---|---:|---:|---:|---|
| 일반 시나리오 | **9/11** | **1/5** | **1/6** | 문자열 오탐 1건, HEAD 변경 미탐 1건 |
| 형식 경계 | **0/1** | **1/1** | 0/0 | 정상 Markdown 표 수정 차단 |

일반 시나리오의 차단 대상 6개 중 5개는 차단했고, 허용 대상 5개 중 4개는 허용했다. 12개 모두 실행 오류는 0건, 같은 입력을 연속 재실행했을 때 판정 변경은 0건이었다. 이는 **이 합성 사례의 결과**이며 실제 PR의 정확도 81.8%를 뜻하지 않는다.

### v1 실행 경로

| 관측 항목 | 결과 | 의미 |
|---|---:|---|
| 가짜 Claude 요청까지 도달 | 12/12 | 규칙 문서와 Git diff가 요청에 포함됨 |
| 같은 프롬프트 + 두 통제 응답에서 게이트 결과 변화 | 12/12 | 셸 단계 판정이 모델 응답 표식에 의존함 |
| `.env.example`이 바뀐 두 사례에서 해당 diff가 프롬프트에 전달 | 0/2 | v1 전처리의 `.env*` 파일 제외 동작 확인 |
| 실제 Claude 응답으로 검증한 사례 | 0/12 | v1 정확도·재현성은 미측정 |

가짜 응답 `위반 없음`을 주면 모두 `pass`, `[BLOCKER]`를 주면 모두 `fail`이었다. 이 숫자는 **의도적으로 주입한 응답에 대한 셸 동작**이다. 실제 모델이 어떤 사례를 맞힐지와는 관계없다. v1의 초기 Action 단계는 `result=fail`을 기록해도 셸 종료 코드는 0이다. Action 설정에서 `fail_on_blocker`가 켜지면 뒤의 단계가 작업을 실패 처리한다.

### 사례별 비교

아래의 v1 두 열은 모델을 통제했을 때의 **실행 결과**이며 정확도 비교 점수가 아니다. `pass`는 허용, `fail`은 차단이다.

| 사례 | 기대 | v1: 위반 없음 응답 | v1: BLOCKER 응답 | ver2 실제 | ver2 평가 |
|---|---|---|---|---|---|
| `P01-route-undocumented` | fail | pass | fail | fail | 일치 |
| `P02-route-documented` | pass | pass | fail | pass | 일치 |
| `P03-unrelated-doc` | fail | pass | fail | fail | 일치 |
| `P04-deleted-route` | fail | pass | fail | fail | 일치 |
| `P05-implementation-only` | pass | pass | fail | pass | 일치 |
| `P06-route-in-string` | pass | pass | fail | fail | 오탐 |
| `P07-env-missing` | fail | pass | fail | fail | 일치 |
| `P08-env-present` | pass | pass | fail | pass | 일치 |
| `P09-env-unrelated` | fail | pass | fail | fail | 일치 |
| `P10-head-route` | fail | pass | fail | pass | 미탐 |
| `P11-docs-only` | pass | pass | fail | pass | 일치 |
| `B01-markdown-table` | pass | pass | fail | fail | 오탐 |

문자열 속 `@app.get`을 변경한 P06은 실제 라우트 등록이 아닌데 `ver2`가 차단했다. P10의 HEAD 등록은 API 변경이지만 `ver2`가 규칙을 발동하지 않아 통과했다. B01의 Markdown 표는 올바르게 경로를 바꿨지만 내용 추출 형식이 맞지 않아 차단됐다. 이 세 사례는 앞선 [main→ver2 사후 평가](generalization-audit-2026-09-22.md)에서 발견된 오류 유형을 **새 Git 저장소·CLI 실행 경로로 재현**한 것이다. 새로운 독립 발견 건수로 세지 않는다.

## 무엇을 비교할 수 있고 없는가

**비교 가능한 것:** 동일한 Git 변경을 실제 실행 경로에 넣었을 때 각 버전이 어떤 입력을 읽고, 어떤 조건에서 결과를 내는지. 또한 `ver2`의 정책 엔진이 통제한 사례의 기대 판정을 얼마나 충족하는지.

**직접 비교할 수 없는 것:** `v1`과 `ver2`의 탐지 정확도 우열. v1의 핵심 판단은 실행하지 않은 Claude 모델에 있고, 자연어 규칙과 YAML 정책도 완전히 같은 프로그램이 아니다. 실제 모델을 나중에 실행해도 모델 버전·온도·API 상태·비용·응답 파싱을 통제하고 별도의 블라인드 표본을 마련해야 비교가 성립한다.

기존 [개선 전후 비교표](assessment/after-v1/comparison.md)와 [32개 사후 반례](generalization-audit-2026-09-22.md)는 `main`의 `bffc655` → `ver2`를 비교한다. 그 `main`은 이미 Python 정책 엔진이어서 **실제 v1 태그의 측정값으로 바꿔 쓸 수 없다.** 이 두 비교 축을 구분해 해석해야 한다.

## 재현과 원본 자료

- [사례와 기대 판정](assessment/v1-ver2-controlled-2026-09-23/cases.json)
- [실험 프로토콜과 도구 보정 기록](assessment/v1-ver2-controlled-2026-09-23/protocol.md)
- [최종 실행 1 원본](assessment/v1-ver2-controlled-2026-09-23/run-3/result.json) · [최종 실행 2 원본](assessment/v1-ver2-controlled-2026-09-23/run-4/result.json)
- [실행 도구](../scripts/compare_v1_ver2.py)

사례·프로토콜·실행 도구·제품 파일별 SHA-256과 환경 버전은 원본 JSON에 있다. 처음 두 실행(`run-1`, `run-2`) 뒤 **문서 커밋 후에도 재현되도록 실행 도구의 제품 코드 고정 확인 방식을 보정**했다. 사례나 기대값은 변경하지 않았고, 보정 전 결과도 보존했다. 도구가 첫 실행부터 완전히 사전 고정됐다고 주장하지 않는다.

`ver2` 브랜치에서 Python 3.11과 Git·Bash·jq를 준비한 뒤 다음 명령을 실행한다. 패키지 의존성은 [pyproject.toml](../pyproject.toml)을 따른다. 결과 경로는 존재하지 않아야 한다.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python scripts/compare_v1_ver2.py --out docs/assessment/v1-ver2-controlled-2026-09-23/run-recheck
```

실제 GitHub의 조직 권한·PR 댓글·Claude 응답, PR 표본의 오탐·미탐, 리뷰 시간은 검증 범위 밖이다. 다음 검증에서는 실제 PR을 별도 표본으로 정하고 기대 판정을 독립 리뷰로 확정한 뒤, 같은 표본에 두 버전을 실행해야 한다. 그때는 모델 호출 비용과 비결정성도 기록해야 한다.

## 이 작업으로 확인된 경험의 범위

이번 작업에서는 비교 대상을 태그와 커밋으로 고정하고, 같은 Git 변경과 기대값을 먼저 설계했다. 외부 모델 호출을 통제해 제품 입력·출력 경로를 검증했고, `ver2`의 실제 판정을 사례별로 분석했다. 실패 사례와 실험 도구의 중간 보정도 공개했다. **실제 사용자 PR에서 우수한 성능을 입증했다는 경험으로 표현하지 않는다.**
