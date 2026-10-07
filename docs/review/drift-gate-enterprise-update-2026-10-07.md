# 심화 논리 설계의 운영 코드 반영과 검증

2026-10-07 · `ver2`의 `d262ec2` 위 미커밋 작업 트리

기준은 [심화 설계](../architecture/drift-gate-enterprise-logical-design-2026-10-07.md)다. 이번에는 우선 구현 묶음 W01–W04와 W10의 입력 계약 부분을 반영했다. 전체 17개 설계 과제를 구현 완료한 보고서는 아니다. 이전 작업과 사용자가 삭제한 문서 두 개를 그대로 보존했고, 커밋·푸시는 하지 않았다.

## 바뀐 동작

| 항목 | 수정 전 | 수정 후 |
|---|---|---|
| E01 혼합 env/API | 변경 없는 env 읽기가 API 경로 변경을 가려 `pass/not-applicable` | 혼합 범위를 `undetermined/unverified`로 유지. 명시 그룹 분리 안내, 정책의 unknown 조치 적용 |
| E02 타입 전용 import | 주석·탭·줄바꿈이 들어가면 런타임 Express 바인딩으로 오인 | AST의 `type` 토큰으로 거부. 같은 방식으로 const 선언의 공백 변형도 처리 |
| E03 JSON 지수 오버플로 | `1e999`가 무한대 float로 수락 | 중첩을 포함한 모든 float의 유한성을 확인하고 `unsupported_numeric_range`로 거부 |
| W04 만료 날짜 | core가 `date.today()`를 직접 읽음 | adapter가 UTC 날짜를 주입하고 core는 명시 입력으로 평가. 날짜를 영수증과 입력 digest에 결합 |
| W10 평가 입력 | 빈 사례·빠진 기대 축을 성공으로 계산할 여지가 있음 | protocol·비어 있지 않은 사례·고유 ID·네 기대 축·결과 값·파일 경로를 검증하고 잘못된 입력은 종료2 |

혼합 계약은 자동으로 모든 의무를 구성한 것이 아니라 안전한 보류 경로다. `gate.on_unverified: fail`이면 fail이지만 **API 불일치를 확정한 위반과는 구분한다.** 알려진 API 불일치를 확정하려면 `api-routes`/`api-schema`와 `env-keys`를 각각 명시한다. 해당 명시 그룹 통제는 그대로 `violated/verified`다.

혼합 여부를 단순한 FastAPI import 존재만으로 결정하지 않는다. 해석 가능한 미사용 import에서는 route 사실이 비어 있음을 확인하므로 불필요한 API 의무를 만들지 않는다. 해석할 수 없는 외부 route 데코레이터는 환경 키가 바뀌지 않았더라도 unknown으로 남긴다. route와 schema 후보를 동시에 찾으면 schema를 확인하며 검사 이름의 알파벳 순서로 고르지 않는다.

## 날짜·호환성 계약

[EvaluationContext](../../drift_gate/core/models/evaluation_context.py)는 immutable한 `date` 입력을 가진다. string, bool, datetime을 자동 변환하지 않는다.

```python
from datetime import date
from drift_gate.core.models.evaluation_context import EvaluationContext

result = run(files, policy=policy, drift_ignores=ignores,
             context=EvaluationContext(date(2026, 10, 7)))
```

직접 core 호출에서 만료가 있는 ignore에 context를 주지 않으면 해당 ignore를 거부한다. 만료가 없는 ignore는 기존 계약을 유지한다. CLI/MCP/Desktop/Action은 공통 inspection에서 실제 UTC 날짜를 만든다. 만료 날짜 당일까지 유효하고 그 다음 날짜부터 거부한다. 같은 context 재실행은 같은 의미 판정을 만들지만 과거 context를 현재 승인으로 사용할 수는 없다.

결과의 기존 필드는 유지하며 실행 metadata에 `evaluation_context`, `input_digest_version=3`을 추가했다. 입력 SHA는 날짜를 포함하므로 이전 digest 형식과 직접 비교하지 않는다. 같은 파일과 같은 날짜의 digest는 같고 다른 날짜는 다르다는 회귀가 있다. 엔진 아티팩트·프로필·승인을 포함한 전체 provenance 모델은 후속 과제다.

## 검증 결과

| 검사 | 결과 | 근거 |
|---|---|---|
| Python 전체 최종 | **1,301 통과, skip 0** | [최종 원시 로그](../assessment/enterprise-update-2026-10-07/python-final.log) |
| 새 회귀 | **73개** | [test_enterprise_correctness.py](../../drift_gate/tests/test_enterprise_correctness.py). 전체 1,301에 포함 |
| React | **125 통과** | [로그](../assessment/enterprise-update-2026-10-07/react.log) |
| TypeScript | 통과 | [로그](../assessment/enterprise-update-2026-10-07/tsc.log) |
| ruff E9,F | 통과 | [로그](../assessment/enterprise-update-2026-10-07/ruff.log) |
| 기존 고정 기능 fixture | 21/21 | [결과](../assessment/enterprise-update-2026-10-07/fixed-evaluation.json) |
| Python/Git v2 | 네 축 각각 14/14 | [결과](../assessment/enterprise-update-2026-10-07/python-git-v2-verified.json) |
| Express/Git v1 | 네 축 각각 8/8 | [결과](../assessment/enterprise-update-2026-10-07/express-git-v1-verified.json) |
| 원래 반례 재실행 | 다섯 수락 조건 충족 | [관측](../assessment/enterprise-update-2026-10-07/probes-after.json), [단언](../assessment/enterprise-update-2026-10-07/probe-assertions.json) |
| 자체 Drift Gate | pass / unverified, 적용 규칙5 | [결과](../assessment/enterprise-update-2026-10-07/self-check.json), [입력](../assessment/enterprise-update-2026-10-07/self-check-inputs.json) |
| README docs-check | 경고0 | [결과](../assessment/enterprise-update-2026-10-07/docs-check.json) |

전체 테스트에는 작성된 FastAPI64 OpenAPI 대조 및 Express4 HTTP 대조가 포함됐다. Express 대조는 sandbox 안에서 로컬 포트 열기가 EPERM으로 거부돼, 해당 동작을 허용한 테스트 실행에서 재검증했다. 대상 사용자 저장소의 앱 코드를 실행한 것은 아니다.

자체 검사는 기존 tracked 변경에 추가로 untracked source/test 27개를 명시 수집해 총74개 파일을 입력으로 사용했다. Git index를 변경하지 않았다. 자체 정책에 미분류된 운영 경로는0이다. 이 pass는 계약 문서 변경 의무의 충족이며 새 논리 전체의 정확성 증명이 아니다.

새 suite 입력 검증을 처음 적용하면서 기존 자료의 protocol 객체와 `not-applicable` 상태를 놓친 문제를 발견했다. 실행기와 회귀를 보완했으며 고정 suite를 수정하지 않았다. 첫 탐색 회귀에는 테스트의 근거 필드 이름과 route 변화가 없는 입력의 기대값 오류도 있었다. 탐색 로그는 보존하고 최종 통과 로그와 구분한다.

## 변경 위치

- [자동 계약 선택](../../drift_gate/core/evaluation/routes.py): 혼합 범위 보존, 미사용 import 통제, schema 선택 우선순위.
- [Express 분석](../../drift_gate/adapters/ast/express_routes.py): AST 의미 토큰으로 type-only와 const 확인.
- [OpenAPI decode](../../drift_gate/core/evaluation/openapi_document.py): 유한성 검사, 원래 오류 사유 보존, 파싱 cache 버전 갱신.
- [core 실행](../../drift_gate/core/engine.py), [평가기](../../drift_gate/core/evaluation/evaluator.py), [공통 inspection](../../drift_gate/adapters/inspection.py): 명시 날짜 입력, UTC adapter, 날짜를 포함한 영수증.
- [평가 실행기](../../scripts/audit_auto_contracts.py): 잘못된 평가 입력·Git 내부 경로 거부.
- [회귀](../../drift_gate/tests/test_enterprise_correctness.py), [기존 엔진 테스트](../../drift_gate/tests/test_engine.py), [Desktop CI](../../.github/workflows/desktop-build.yml): 정상·반례·만료·실제 suite·CLI 입력 오류 통제.
- [게이트 계약](../contracts/gate-and-inputs.md), [운영 계약](../ops/drift-gate-self-check.md): 현재 동작과 호환성 변경을 명시.

## 설계 과제의 잔여 범위

| 과제 | 이번 상태 |
|---|---|
| W01–03 | 재현된 결함과 정상 통제 수정 완료 |
| W04 | 평가 날짜 입력과 영수증 반영 완료. 전체 외부 승인 envelope는 미구현 |
| W05–06·W08 | typed facts·프로필 registry·구조화 증거 회로는 후속. 이번 변경은 안전한 호환 단계 |
| W07·W09·W15–16 | 스냅샷·신뢰 실행·캐시·게시·최종 설치본 출처 모델은 전체 구현 완료 아님 |
| W10 | 평가 입력 검증 완료. 외부 사람·저장소 holdout·평가 독립성 개선은 미수행 |
| W11–14 | 의존 closure·전역 자원 격리·typed trigger·넓은 schema 호환성은 후속 |
| W17 | 조직별 권한·격리·보존 요구 확인 전 조건부 과제 |

기존 v1의 지원24/24·경계5/8을 이번에 재실행했다고 주장하지 않는다. 현재 22개 고정 의미 사례도 작성자 비맹검 회귀이고 실제 PR 정확도가 아니다. 새 원격 CI·설치본·Windows/Linux·공개 릴리스 검증은 수행하지 않았다. 변경된 파일과 최종 근거의 digest는 [영수증](../assessment/enterprise-update-2026-10-07/verification.json)에 기록한다.
