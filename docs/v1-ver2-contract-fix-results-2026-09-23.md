# E05 계약 드리프트 오류 수정 후 재검증

기준일: 2026-09-23 · 수정 제품 코드: [`ver2` 커밋 `715335f`](https://github.com/cres17/pr-convention-checker/commit/715335f9877d0a7139f7f4ceaa289e6ab13b2a66)

## 결과와 해석

기존 [v1–ver2 통제 비교](v1-ver2-controlled-comparison-2026-09-23.md)에서 확인된 세 오류를 제품 코드에서 수정했다. **같은 12개 합성 Git 변경**을 실제 CLI에 다시 넣었을 때 P06 문자열 속 가짜 라우트는 `fail→pass`, P10 HEAD 라우트 누락은 `pass→fail`, B01 Markdown 표는 `fail→pass`로 기대 판정과 일치했다. 다른 9개 사례의 판정은 유지됐다. 일반 시나리오는 **9/11→11/11**, 형식 경계 사례는 **0/1→1/1**이다.

이 숫자는 **이미 알려진 오류를 고친 동일 입력의 회귀 결과**다. 실제 PR 전체의 정확도나 v1보다 높은 모델 판단 정확도를 의미하지 않는다. 별도로 보관된 32개 반례에서는 기대 일치가 **17/32→22/32**로 늘었고 악화된 사례는 없었지만, **10개는 여전히 불일치**한다. 이 반례도 개발자가 이미 알고 있었으므로 독립·블라인드 표본이 아니다.

## 무엇을 수정했는가

| 오류 | 수정 내용 | 확인한 판정 |
|---|---|---|
| P06: 문자열 속 가짜 라우트 오탐 | [공통 라우트 문법](../drift_gate/core/route_syntax.py)에서 등록 구문이 코드 줄의 시작에 있어야 한다는 기준을 사용했다. [강도 분류](../drift_gate/core/classification/intensity.py), [코드 계약 추출](../drift_gate/core/evaluation/contracts.py), [Python](../drift_gate/adapters/ast/python_adapter.py)·[JS/TS](../drift_gate/adapters/ast/typescript_adapter.py) 의미 신호를 같은 기준에 맞췄다. | `message = "@app.get('/sample')"`는 API 변경으로 보지 않아 `pass` |
| P10: HEAD 변경 미탐 | 공통 메서드 집합에 이미 있던 `HEAD`·`OPTIONS`를 분류와 의미 신호에서도 사용하게 했다. | 문서 없는 `@app.head('/health')`는 `fail`; 정확한 문서가 있으면 `pass` |
| B01: Markdown 표 오탐 | [문서 파서](../drift_gate/core/evaluation/contracts.py)에 `| GET | /members |`처럼 같은 행의 인접 셀에 있는 메서드·경로를 읽는 경로를 추가했다. 평문 형식과 추가·삭제 양쪽의 확인은 유지했다. | 이전 경로 삭제와 새 경로 추가를 문서가 모두 반영하면 `pass` |

## 동일 12개 사례의 전후 비교

`pass`는 허용, `fail`은 차단이다. v1 두 열은 실제 Claude 모델이 아닌 **고정 응답을 주입한 Action 셸의 결과**다. `위반 없음` 응답을 주면 모든 사례가 `pass`, `[BLOCKER]` 응답을 주면 모두 `fail`이었다. v1의 정확도는 측정하지 않았다.

| 사례 | 기대 | v1: 위반 없음 | v1: BLOCKER | ver2 수정 전 | ver2 수정 후 |
|---|---|---|---|---|---|
| P01 문서 없는 경로 변경 | fail | pass | fail | fail | fail |
| P02 문서와 일치하는 경로 변경 | pass | pass | fail | pass | pass |
| P03 무관한 문서 수정 | fail | pass | fail | fail | fail |
| P04 라우트 삭제 | fail | pass | fail | fail | fail |
| P05 구현만 변경 | pass | pass | fail | pass | pass |
| **P06 문자열 속 라우트** | **pass** | pass | fail | **fail** | **pass** |
| P07 환경변수 샘플 누락 | fail | pass | fail | fail | fail |
| P08 환경변수 샘플 반영 | pass | pass | fail | pass | pass |
| P09 무관한 환경변수 샘플 수정 | fail | pass | fail | fail | fail |
| **P10 HEAD 라우트** | **fail** | pass | fail | **pass** | **fail** |
| P11 문서만 변경 | pass | pass | fail | pass | pass |
| **B01 Markdown 표** | **pass** | pass | fail | **fail** | **pass** |

| ver2 평가 범위 | 수정 전 일치 | 수정 후 일치 | 수정 전 FP/FN | 수정 후 FP/FN |
|---|---:|---:|---:|---:|
| 일반 시나리오 | 9/11 | **11/11** | 1/1 | **0/0** |
| 형식 경계 | 0/1 | **1/1** | 1/0 | **0/0** |

새 실행에서도 v1 요청 발생 12/12, 고정 응답에 따른 게이트 변화 12/12, ver2 동일 입력 두 번 실행의 판정 일치 12/12였다. 실행 오류는 없었다. v1의 실제 모델 응답과 GitHub 댓글·후속 실패 단계는 여전히 검증 범위 밖이다.

## 이전에 만든 32개 반례도 다시 실행

[기존 32개 입력](assessment/generalization-audit-v1.json)과 기대값을 변경하지 않고 재실행했다. 수정 전 원본은 [기존 결과](assessment/generalization-ver2.json), 수정 후 원본은 [이번 결과](assessment/v1-ver2-controlled-2026-09-23/post-fix-generalization-715335f.json)이다.

| 범위 | 수정 전 기대 일치 | 수정 후 기대 일치 | 수정 후 FP | 수정 후 FN |
|---|---:|---:|---:|---:|
| 지원 범위 24개 | 17/24 | **21/24** | 2 | 1 |
| 형식 경계 8개 | 0/8 | **1/8** | 1 | 6 |

추가로 맞게 된 다섯 사례는 HEAD 추가(A03), OPTIONS 추가(A04), 문자열 속 라우트(A10), 줄 안 주석 속 라우트(A11), Markdown 표(B02)다. 기존에 맞았는데 틀리게 바뀐 사례는 없었다. 여전히 틀린 사례는 오래된 라우트가 남은 문서(A09), 환경변수 키 관련 두 사례(E04·E05), 여러 줄 라우트·OpenAPI YAML·라우터 접두사·동적 환경변수·별칭 환경변수 접근·응답 스키마·체인 라우터(B01·B03~B08)다. 따라서 **지원 문법 밖의 변경까지 탐지한다고 주장하지 않는다.**

## 재현성과 검증 한계

- 원본 12개 사례의 SHA-256 `9c8202b9b73b5573ab6281adfd8a23f501f57cdd9879da7b89376606d50c391b`를 유지했다. 새 [실행 도구](../scripts/compare_v1_ver2_postfix.py)는 기존 [고정 도구](../scripts/compare_v1_ver2.py)를 수정하지 않고 그 도구의 Git 사례 생성·v1 가짜 응답·v2 CLI 실행 함수를 재사용한다. 실행 전 원본 결과의 사례 해시와 각 Git diff 해시, v1 태그와 셸 스크립트 해시를 확인한다.
- [12개 재실행 원본](assessment/v1-ver2-controlled-2026-09-23/post-fix-715335f/result.json)에 기준 커밋, 수정 코드 커밋, 제품 파일별 해시, 도구 해시, 환경, 사례별 판정·종료 코드가 있다. 원래 `run-3`·`run-4`·`post-discovery-recheck` 원본은 그대로 보존했다.
- 단위·엔진·CLI 회귀 테스트를 포함한 전체 `pytest` **536개 통과**. 핵심 Python 오류 검사(`ruff --select E9,F63,F7,F82`) 통과. 다만 12개와 32개는 모두 알려진 합성 사례이며, 실제 PR 표본·별도 평가자가 확정한 기대값·v1 실제 모델 호출은 없다.

다시 실행하려면 Python 3.11과 프로젝트 의존성, Git·Bash·jq를 준비하고 **아직 존재하지 않는 출력 경로**를 지정한다.

```bash
python scripts/compare_v1_ver2_postfix.py --out /tmp/drift-gate-post-fix-recheck
python scripts/audit_generalization.py --source-root . --revision 715335f --out /tmp/drift-gate-generalization-recheck.json
python -m pytest -q
```
