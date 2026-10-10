# 조직 조치 분리와 수락 시험 매트릭스

2026-10-10 KST · 기준 `d6d2f7f`

[심화 설계](../architecture/drift-gate-enterprise-detailed-design-2026-10-07.md)의 7장(조직 조치와 실행 결과의 분리)을 구현하고,
18장 수락 시험 매트릭스 A01~A17을 실행 가능한 형태로 묶었다.

## 1. EnforcementOutcome·ExecutionOutcome (7장)

| 출력 | 내용 |
|---|---|
| `enforcement` | `action`(allow·review·block), `basis`, 확정 위반·미결정·부분 검증·면제 규칙 ID, `gate_result` |
| `execution.outcome` | `completed`·`rejected-input`·`aborted`·`internal-error`, 원래 상태, 게시 상태 |

규칙을 다시 판정하지 않는 projection이다. gate가 fail이면 block, 아니면 위반·미결정·부분 검증이 하나라도 남으면 review,
모두 없으면 allow다. 기존 `result`·`summary`·종료 코드는 바뀌지 않는다. CLI JSON, MCP(full·compact), Markdown·HTML 보고서가
같은 함수의 결과를 싣는다. Desktop 화면은 아직 표시하지 않는다. 결과가 없는 실행에는 `enforcement`가 없다.

설계와 다른 점:
- 설계의 `unresolved_obligation_ids`는 규칙 단위(`unresolved_rule_ids`)로 냈다. 현재 결과의 판정 단위가 규칙이기 때문이다.
  의무 단위 ID는 proof 진단(`contract_diagnostics`)에만 있다.
- `partially_verified_rule_ids`를 추가했다. satisfied지만 범위가 열린 규칙을 allow로 처리하지 않기 위해서다.
- `policy_ref`는 값 대신 `execution.policy_sha256`을 가리킨다. 실행 metadata를 의미 결과에 섞지 않기 위해서다.

저장 묶음 재실행은 `enforcement`를 비교에서 제외한다. 다른 비교 필드의 순수 함수이고, 이 필드가 생기기 전에 기록된 결과도
재실행할 수 있어야 하기 때문이다. 대신 mapping 규칙이 바뀌어도 재실행 비교는 그 변화를 잡지 못한다.

시험: `test_enforcement_outcome.py` 14건(gate pass·fail·warn, docs-only 생략, `on_unverified: warn` unknown, 면제, CLI 성공·입력 오류,
재실행 비교, 실행 상태 mapping).

## 2. 수락 시험 매트릭스 (18장)

`scripts/acceptance_matrix.py`는 각 행의 통과 조건을 시험하는 회귀 테스트 43건을 실행하고, 외부 경로가 필요한 증거를 따로
기록한다. 결과 파일은 한 번만 쓴다. `test_acceptance_matrix.py`는 행이 A01~A17을 빠짐없이 갖고 지정한 테스트가 실제로 수집되는지
확인한다.

| ID | 대상 | 로컬 시험 | 외부 증거 |
|---|---|---|---|
| A01–A09 | facts·no-delta·planner·open scope·known F·OR·service·absence·closure | 통과 | 해당 없음 |
| A10 | trusted checker | 통과 | 일부: CI `trusted-engine` job pass(run 37903285344). required status check 설정은 미확인 |
| A11–A12 | expiry/cache·취소 | 통과 | 해당 없음 |
| A13–A14 | 게시·쓰기 timeout | 통과(가짜 provider) | 일부: PR #1 실제 GitHub 게시·응답 유실 시험(`5cd00ed` 코드, 이후 재실행 안 함) |
| A15 | schema 방향 | 통과(jsonschema 판정기) | 해당 없음 |
| A16 | 설치본 | 통과(`--cli` wrapper) | 일부: Desktop run 37756285887(`a4b0219`). 이후 엔진 변경분은 새 실행 필요 |
| A17 | holdout | 통과(도구) | 없음: holdout 사례와 독립 label 없음 |

[결과 JSON](../assessment/acceptance-matrix-2026-10-10/acceptance-matrix.json)(Linux 컨테이너, Python 3.11.17).

테스트 선택은 작성자의 판단이다. 각 행의 통과 조건을 그 테스트가 충분히 덮는다는 독립 검토는 받지 않았다. 로컬 통과는 외부
증거가 필요한 행을 완료로 바꾸지 않는다. 설계 문구대로 "유한 모델 pass로 A03–A17까지 완료 처리하지 않는다".

## 검증

| 검사 | 결과 |
|---|---|
| 전체 pytest(Linux 컨테이너, Python 3.11.17) | 1,950 통과, 12 건너뜀 |
| 원격 CI·Desktop | push 후 실행 기록으로 확인하며 이 표에 포함하지 않음 |
| ruff `E9,F` | 통과 |
