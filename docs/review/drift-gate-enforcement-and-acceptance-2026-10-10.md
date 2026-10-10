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

## 3. Desktop 회귀 단계의 종료 crash

`5a7b2fa`를 push한 뒤 Desktop run 38035946798의 세 플랫폼이 모두 "Check desktop behavior" 단계에서 실패했다. 시험은 전부 통과했고
(macOS 1,128 통과), 그 뒤 interpreter 종료 중 `Fatal Python error: Segmentation fault`(Windows는 `Aborted`)로 끝났다. 앞서 기록한
Windows 종료 코드 127(run 37754952843)과 같은 위치다. 직전 커밋에서 추가한 `-X faulthandler`가 이 정보를 남겼다.

컨테이너에 PySide6 6.12.0을 설치해 같은 시험 목록을 실행했다.

| 조건 | 결과 |
|---|---|
| 수정 전, 같은 목록 5회 | 2회 segmentation fault(종료 코드 139) |
| 수정 전, `ReviewDialog` 시험 단독 6회 | 6회 crash |
| 최소 재현: `QDialog` 자식 버튼 signal을 `lambda: self...`에 연결 후 삭제 | 3/3 crash. bound method·`self` 없는 lambda는 0/3 |
| 수정 후, 같은 목록 5회 | 5회 정상 종료 |

`ReviewDialog`의 질문 복사 버튼과 `PackageCheck`의 timeout이 `self`를 잡는 lambda였다. 둘 다 bound method로 바꿨다.
`PackageCheck`는 설치본의 `--verify-package` 실행에서 쓰이므로, 과거 Intel 설치본 종료 실패와 관련이 있을 수 있다. 그 실패는 이번에
재현하지 않았으므로 원인으로 확정하지 않는다. 새 `test_qt_teardown.py`는 desktop 코드의 해당 연결 패턴을 금지하고(모든 환경),
PySide6가 있는 환경에서 dialog를 지운 뒤 interpreter가 정상 종료하는지 3회 확인한다. 수정 전 코드에서는 4건 모두 실패했다.
기록: [desktop-regression-runs.log](../assessment/qt-teardown-2026-10-10/desktop-regression-runs.log). macOS·Windows는 CI 실행으로 확인한다.
