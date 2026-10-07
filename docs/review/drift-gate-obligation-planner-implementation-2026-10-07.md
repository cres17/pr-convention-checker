# 심화 설계 S1-c: 계약별 의무와 문서 연결 구현

2026-10-07 · `ver2`, `d262ec2` 위 미커밋 작업 트리

[심화 설계](../architecture/drift-gate-enterprise-detailed-design-2026-10-07.md)의 S1-c를 구현했다. [S1-b](drift-gate-profile-discovery-implementation-2026-10-07.md)의 후보·미확인 domain을 계약별 의무와 명시적 문서 연결로 이어 준다. 기본 게이트 전환이나 전체 S1 완료 보고서는 아니다. 기존 편집과 문서 삭제를 보존했으며 이번에도 커밋·푸시하지 않았다.

## 구현 내용과 구성

- [planner.py](../../drift_gate/core/contracts/planner.py): 불변 request·scope·binding·assessment·obligation·plan·outcome 타입과 구조 검증을 담당한다. 계약 의무, 적용성, 조건부 진리값, 검사 완전성을 구분한다.
- [obligations.py](../../drift_gate/core/evaluation/obligations.py): 기존 분석기를 사용해 프로필별 전후 변화를 구하고 명시 문서 관찰을 평가한다. 파일·네트워크·Git 읽기와 소스 실행은 하지 않는다.
- [routes.py](../../drift_gate/core/evaluation/routes.py): 실제 `auto-strict`가 새 planner를 shadow 실행한다. 기존 게이트에는 이전 호환 힌트만 사용한다.
- [analysis_session.py](../../drift_gate/core/evaluation/analysis_session.py): 실행별로 최근 limit개 shadow 결과를 진단용으로 보관한다. 외부 JSON 필드나 전체 정책 인증으로 사용하지 않는다.
- [test_obligation_planner.py](../../drift_gate/tests/test_obligation_planner.py): 신규 회귀 77개. 일반 CI의 전체 수집과 [Desktop 명시 목록](../../.github/workflows/desktop-build.yml)에 포함한다.

계획의 선언·검증과 분석기/문서 평가를 두 모듈로 분리했다. planner는 특정 분석기를 직접 실행하지 않는다. evaluator는 프로필의 scope를 정확히 선택하고 기존 분석기의 결과를 typed delta와 applicability에 연결한다. 파일 관찰 객체를 불변 계획 안에 보관하지 않는다.

## 새 내부 API의 계약

`PlanRequest`는 rule/group/relation 식별자, 선택 source 경로와 버전이 명시된 `DocumentBindings`를 받는다. binding의 schema는 `contract-document-bindings-v1`이며 프로필 ID/버전별 문서 selector와 any/all 모드를 선언한다. 이는 현재 YAML에 추가할 수 있는 옵션이 아니다.

한 프로필의 활성 후보가 있으면 같은 프로필의 선택 모듈을 함께 분석한다. 비활성 모듈을 버리지 않아 env 키의 파일 간 이동이 신규 추가가 되지 않는다. route와 response는 각각 의무를 만들며 암묵적인 대체 관계가 없다.

다음 구조적 오류를 거부한다.

- 요청과 discovery/source/assessment의 범위 불일치, 빈 요청과 중복 경로.
- 의무·문서 binding·결과·필수 open guard의 누락이나 다른 scope로의 치환.
- 모호한 프로필별 문서 배정, 잘못된 binding 버전과 참조.
- typed delta와 모순된 applicability, untyped 상태와 unknown requirement의 complete 표시.

빠진 assessment는 지우지 않고 `missing_contract_assessment`의 unknown 의무로 남긴다. 문서 연결이 없는 적용 의무는 `unmapped_contract_document`로 남긴다. 연결이 없어도 확정 no-delta인 계약에 문서 갱신 의무를 새로 만들지는 않는다.

생성자 검증은 참조와 상태 구조를 검사한다. 분석기의 의미적 정확성이나 호출자가 제공한 원문의 진실성을 자동으로 증명하지 않는다.

## 혼합 계약의 실제 Git 재현

[재현 스크립트](../assessment/obligation-planner-implementation-2026-10-07/probe_planner.py)는 임시 저장소에 전후 파일을 만들고 실제 Git adapter로 변경을 수집한다. 문서 adapter가 현재 문서를 읽어 키 이름과 bounded 원문 관찰을 만든 뒤 새 계획을 평가한다. 현재 저장소의 index는 바꾸지 않는다. [최종 결과](../assessment/obligation-planner-implementation-2026-10-07/planner-git-examples-final.json)에 입력·기대값·실제값·의무별 상태가 있다.

| 사례 | 실제 새 계획 결과 | completeness |
|---|---|---|
| env 새 키 없음 + route 변경 + 옛 API 문서 | env N/A, API F → **F** | 선택 부분집합에서 닫힘 |
| env 새 키 + route 변경 + env만 갱신, API 문서 삭제 | env T, API F → **F** | 선택 부분집합에서 닫힘 |
| 동적 getter + 옛 API 문서 | env U, API F → **F** | open |
| 동적 getter + 새 API 문서 | env U, API T → **U** | open |
| env와 API 모두 no-delta, 비계약 코드만 변경 | 두 의무 N/A → **T** | 선택 부분집합에서 닫힘 |
| 미지원 Go 변경 + 지원 API 정합 | API T, 필수 discovery guard U → **U** | open |

설계의 6행 모두 일치했다. 기대값은 저자가 정의한 비맹검 회귀 통제다. 독립적인 실제 PR 정확도나 미지원 언어의 기능 지원률이 아니다.

## 추가로 보완한 논리 경계

**다른 모듈의 unknown old getter.** 한 파일의 이전 getter가 동적이면 다른 파일의 현재 literal 키가 정말 새 키인지 확정할 수 없다. 새 env 경로는 전체 선택 프로필의 must/may를 합친 뒤 비교한다. legacy 알고리즘의 의미는 기본 게이트에서 유지하고, 새 내부 계획에서 이 부당한 확정을 막는다. env 삭제는 신규 키 의무와 별개다.

**응답 후보가 없는 모듈과 경로 충돌.** 명시 response_model이 없는 닫힌 모듈 때문에 다른 모듈의 지원 응답 변화가 사라지지 않게 했다. 동시에 그 모듈이 같은 route identity를 등록한다면 응답 의무의 적용성을 확정하지 않는다. 응답의 국소 미지원과 알려진 응답 불일치가 함께 있으면 알려진 F는 유지하고 completeness는 open으로 남긴다.

**문서 선택의 관찰 범위.** literal selector에 대응하는 문서 관찰이 없으면 unknown이다. 명시 missing 관찰과 읽기 실패를 구분한다. glob에 전달된 현재 목록은 전체 열거 증명이 아니므로 미수집 가능 대안을 U로 남긴다. 정합한 문서의 T witness는 유지하지만 관찰한 문서가 모두 불일치라는 이유만으로 전체 OR을 F로 확정하지 않는다.

**진리값과 완전성.** 의무의 조건부 값은 Strong Kleene의 `not(A) or R`이다. F와 U의 AND는 F로 남고, T 대안과 U 대안의 OR은 T지만 검사 범위가 open임을 보존한다. `A=U, R=T`의 조건부 값도 T일 수 있으므로 단순 truth=T를 적용 범위 완전성이나 새 게이트 승인으로 해석하지 않는다. proof DAG와 action projection은 후속 단계다.

**relation 범위.** 명시 request는 relation의 source 선택을 그대로 사용하며 부모 source가 들어오면 거부한다. 기존 relation evaluator를 통해 실제 shadow를 실행했을 때도 relation source만 남는 것을 회귀로 확인했다.

## 직접 실행한 검증

| 검사 | 결과 | 근거 |
|---|---|---|
| Python 전체 | **1,508 통과, skip 0** | [로그](../assessment/obligation-planner-implementation-2026-10-07/python-full.log) |
| 집중 회귀 | **328 통과** | [최종 로그](../assessment/obligation-planner-implementation-2026-10-07/targeted-complete.log) |
| Python 정적 검사 E9,F | 통과 | [최종 로그](../assessment/obligation-planner-implementation-2026-10-07/ruff-final.log) |
| 설계 혼합 사례, 실제 Git + 문서 adapter | **6/6** | [최종 결과](../assessment/obligation-planner-implementation-2026-10-07/planner-git-examples-final.json) |
| 고정 기능 fixture | **21/21** | [결과](../assessment/obligation-planner-implementation-2026-10-07/fixed-evaluation.json) |
| Python/Git v2 | 네 축 각각 **14/14** | [결과](../assessment/obligation-planner-implementation-2026-10-07/python-git.json) |
| Express/Git v1 | 네 축 각각 **8/8** | [결과](../assessment/obligation-planner-implementation-2026-10-07/express-git.json) |
| 이전 22개 의미 사례 | actual·입력 digest·suite hash 동일 | [비교 및 파일 해시 기록](../assessment/obligation-planner-implementation-2026-10-07/verification.json) |
| 자체 Drift Gate | **pass / unverified** | [결과](../assessment/obligation-planner-implementation-2026-10-07/self-check.json), [입력 메타데이터](../assessment/obligation-planner-implementation-2026-10-07/self-check-inputs.json) |

네 축은 facts/decision/verification/gate다. 실행 ID·시각·소요 시간의 동일성을 주장하지 않는다. 고정 입력 5개와 과거 결과 파일은 보존했다. 기존 auto 경계 평가 1/8을 이번 단계에서 다시 측정하거나 개선했다고 주장하지 않는다.

처음 집중 실행에서 기존 discovery 호출 추적 테스트 하나가 실패했다. 새 evaluator가 함수 참조를 미리 가져와 canonical 모듈의 호출 추적이 보이지 않았기 때문이다. [실패 로그](../assessment/obligation-planner-implementation-2026-10-07/targeted-first.log)를 남겼고 canonical 함수를 실행 시 조회하도록 연결을 고쳤다. 기존 테스트의 기대값은 약화하지 않았다. 이후 집중·전체 검사를 통과했다.

자체 게이트는 HEAD 대비 tracked 변경과 명시 수집한 untracked source/test 37개를 합친 총84개를 사용했다. 이전 턴의 작업도 포함한 검사이며 미분류 운영 경로는0이다. index는 바꾸지 않았다. 경로 의무 정책의 pass는 요구된 문서 변경의 충족이며 전체 코드 의미 검증은 아니다. verification은 unverified다.

## 현재 사용 범위와 남은 단계

`inspect_contract_plan()`은 bounded 원문·adapter 문서 관찰과 명시 binding을 받는 내부 프로그램 API다. 기존 YAML을 새 의미로 해석하거나 CLI 옵션을 새로 추가하지 않았다. 실제 auto-strict의 shadow에는 legacy 설정이 새 profile별 binding을 선언하지 않았으므로 unmapped가 남는다. 기본 게이트는 기존 결과를 유지한다.

shadow trace는 실행별 최근 limit개 진단 기록이며 전체 규칙·ignore·threshold 집행 기록이나 인증이 아니다. 실제 legacy shadow의 식별자는 selector 진단용이며 완전한 정책 relation/권한 context의 migration은 후속이다.

`complete_within_selection`은 선택한 모듈/profile과 전달된 문서 관찰의 제한된 분석 주장이다. 서비스 전체 범위, 여러 service의 identity 분리, dependency closure, 원문 manifest, profile/engine/parser digest 인증과 parser 건전성 증명이 아니다. 결과에 `service_scope_certified=false`, `proof_dag_attached=false`를 명시한다. 추가/삭제 부재도 legacy 입력의 선언이다.

UI 소스를 이번 단계에서 바꾸지 않았고 React·tsc는 다시 실행하지 않았다. 전체 Python에는 Qt/Desktop 회귀와 FastAPI/Express oracle이 포함된다. 새 원격 CI·Windows/Linux 실행·최종 설치본·실사용 PC·독립 holdout 평가를 수행하지 않았다.

다음은 **S1-d: proof DAG와 result validator**다. 의무의 진리값을 다시 계산하고 알려진 F의 충분한 witness와 전체 검사 범위를 분리하며, 누락된 참조·잘못된 증명·순환·필수 guard 제거를 거부한다. S1-e에서 그 결과를 외부 진입점과 기존 출력에 연결한 뒤 기본 동작 변경을 검증한다.
