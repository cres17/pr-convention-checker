# S1-d 구현: 증명 구조와 결과 검증기

## 구현 결과

S1-d의 증명 DAG와 결과 검증기를 운영 코드에 추가했다. 명시적 내부 API와 기존
계약 계획의 shadow 경로에서 작동한다. 알려진 위반의 F 판정과 미확인 범위는 함께
보존한다. 기존 YAML·기본 게이트·외부 출력으로 전환하는 S1-e는 진행하지 않았다.

기준은 `ver2`의 HEAD `d262ec2faff3b98c917e3e99f7b6260cf0514ff3`에 누적된 작업 트리다.
이번 구현도 미커밋 상태이며 커밋·푸시는 하지 않았다. 이전 검증 자료와 고정 입력을
덮어쓰지 않고 [이번 실행 폴더](../assessment/proof-implementation-2026-10-07/)에 기록했다.

## 코드 구성과 실행 흐름

| 파일 | 책임 |
| --- | --- |
| `core/models/proof.py` | 불변 명제·근거·범위·노드·평가 IR, 엄격한 JSON 형식 해석 |
| `core/evaluation/propositions.py` | Strong Kleene 연산, 결정적인 충분 근거 선택, 제한된 DAG 생성 |
| `core/evaluation/result_guard.py` | 별도 기대 context에 대한 참조·논리·근거·coverage·자원 제한 검사 |
| `core/evaluation/contract_proof.py` | 계획의 분석 결과를 명시적 전제로 변환하고 검증된 증명 반환 |
| `core/contracts/input_identity.py` | 전달된 소스·문서 관측치의 결정적인 digest |
| `core/evaluation/analysis_session.py` | 검증된 최근 shadow 증명 보관 |
| `tests/test_proof_evaluation.py` | 114개 회귀·논리·조작 반례 테스트 |

`inspect_contract_proof(request, source_files, documents)`는 source discovery와 적용성·문서
요구 분석 후 명제를 구성한다. `ProofContext`는 검사 범위, 입력 digest, 명제 구조,
원자 전제와 허용 evidence를 갖는다. 생성기는 이 구조를 평가하고, 별도 검증기는
기대 context와 비교해 값을 재계산한다. 반환된 `ContractProof.to_dict()`도 검증을 다시
통과해야 `contract-proof-result-v1`을 내보낸다.

원본 파일·Git·네트워크·시각·Qt 접근은 새 core 코드에 없다. 결과에는 원문 대신
관측치 digest와 경로·프로파일·전제·증명 참조를 넣는다.

## 논리와 범위

- atom, not, all, any, conditional을 지원한다. conditional은 적용 조건 A와 문서 요구 R에
  대해 `¬A ∨ R`이다. 공유 원자 `U ∨ ¬U`를 임의로 T로 바꾸지 않는다.
- AND의 알려진 F와 OR의 알려진 T는 충분한 근거로 남긴다. NOT은 자식 근거를,
  conditional의 F는 A=T와 R=F 양쪽 근거를 요구한다.
- 근거에 사용하지 않은 자식도 coverage에 남긴다. `AND(F,U)`는 F/입증됨과
  범위 불완전이 함께 나올 수 있다. 실제 계획의 열린 discovery guard도 필수 자식이다.
- 비활성 discovery 영역도 root에 포함하므로 무엇을 검사했는지가 출력에서 사라지지
  않는다. A=F인 경우 문서 의무는 없고 R=U를 보존하되 불필요한 문서 영역은 만들지 않는다.
- 충분한 근거 선택은 안정 ID 순서로 결정한다. 최소 증명 탐색은 구현하지 않았다.

현재 증명은 family analyzer의 적용성·문서 요구 판정을 받아들인 **원자 전제에 조건부인
논리 일관성 증명**이다. 문서 선택 내부의 모든 비교 단계, AST 추출의 건전성,
parser 구현 자체를 독립적으로 증명하지 않는다. 이 전제는 결과의 assumptions와 assurance에
명시한다. `decision_proven`을 실사용 PR의 정확성이나 원본 진위로 해석하지 않는다.

## 결과 검증과 실패 처리

검증기는 생성기의 연산 함수를 재사용하지 않고 별도의 표·분기로 진리값을 확인한다.
다음 입력은 정상 결과로 반환하지 않고 `ResultValidationError`로 종결한다.

- U에 확정 proof가 붙거나 proven 표시가 저장 진리값과 어긋난 경우.
- 선언한 명제 구조·root·입력 context를 바꾸거나 노드를 누락한 경우.
- 같은 명제·evidence ID가 중복되거나 truth·profile을 서로 다르게 주장한 경우.
- 자식·evidence·domain·profile 참조를 해결하지 못하는 경우.
- evidence의 인정 범위가 원자 명제 범위보다 좁은 경우.
- 충분하지 않은 자식 근거, coverage 누락·변조, discovery guard 제거.
- 순환·미도달 노드, 기본 4,096 노드·16,384 간선·깊이 128 상한 초과.
- JSON 형식이 맞지 않거나 현재 스키마에서 최신 HEAD·원본 진위·서비스 완전성을
  인증한다고 주장하는 경우.

`validate_proof_payload(json_object, expected_context)`는 저장된 JSON도 검사할 수 있다.
**기대 context는 호출자가 독립적으로 확보해야 한다.** 받은 JSON에 든 context를 그대로
신뢰해 검증기에 전달하는 동작은 원본 검증이 아니다. S2의 manifest·권한·최신성 검증은
아직 구현하지 않았다. 원문 byte range와 manifest의 실제 일치 여부를 core가 확인했다고
주장하지 않는다. 위 상한은 방어적 IR 처리 한도이며 성능 SLA가 아니다.

기존 `evaluate_contract_plan`도 반환 전에 증명을 만들고 검증한다. `AnalysisSession`의
`shadow_contract_proofs`는 검증된 최근 증명만 보관한다. 실패를 catch해 정상 pass로
바꾸는 경로는 추가하지 않았다. 최근 128개 보관은 전체 정책 처리 완료의 증명이 아니다.

## 이전 검토 3건의 수정

| 이전 문제 | 수정과 대조군 |
| --- | --- |
| R1: 같은 경로의 새 소스로 이전 계획을 재평가해 T | discovery에 source digest 결합, 평가·적용성 분석 때 검사. 이전 계획 재사용은 거부하고 새 계획은 F |
| R2: 삭제된 env 문서의 잔존 키를 인정해 T | 공통 문서 상태 검사를 종류별 분기 앞에 배치. 불명확한 삭제는 U, 명시적 missing은 F |
| R3: 검사 종류가 달라도 결과 JSON 동일 | 기존 계획 직렬화에도 전체 discovery 추가. 비활성 종류가 달라도 출력이 구별됨 |

문서 관측치도 결과 digest에 결합했다. 같은 판정이라도 문서 bytes가 다르면 proof context는
다르며, 이전 proof를 새 context로 검증하면 거부한다. digest는 전달된 관측치의 동일성을
확인하며 외부 제공자의 진위나 실제 현재 파일과의 일치를 인증하지 않는다.

## 실행한 검증

| 검사 | 결과 |
| --- | --- |
| Python 전체 | 1,622 통과, skip 0 |
| S1-a~d 관련 테스트 | 321 통과 |
| 신규 proof 테스트 | 114개, 전체 및 관련 테스트에 포함 |
| React | 125 통과, 11개 파일 |
| Ruff E9,F (`drift_gate`, `scripts`) | 통과 |
| TypeScript·UI 빌드 | 통과, 임시 폴더로 출력 |
| Python/Git 고정 사례 | 14/14, 네 축 일치 |
| Express/Git 고정 사례 | 8/8, 네 축 일치 |
| 기존 고정 평가 | 21/21 |
| 기존 S1-c Git·문서 사례 | 6/6 |
| 새 proof Git·문서 사례 | 같은 6건에서 6/6 |
| 이전 반례 3건과 JSON 조작 4종 | 수정 확인 및 조작 거부 |
| 자체 정책 | pass / unverified, 입력 90개 |

신규 테스트는 이항 세 값 표 27개와 NOT 3개, 공유 원자, 중첩 식의 27개 배정과
미사용 leaf의 모든 이진 보완, 잘못된 참조·근거·진리값·순환·한도 등을 검증한다.
유한 논리 사례의 성공을 전체 프로그램 형식 검증으로 표현하지 않는다.

이전 실행과 Python/Express Git 22건의 suite 해시·사례별 입력 해시·기대값·실제값이
같았다. 고정 평가 21건의 판정과 보고서도 실행 식별자·시간 정보를 제외하면 같다.
사례는 작성자가 만든 비맹검 통제이며 실사용 PR 정확도 수치가 아니다.

자체 정책에는 HEAD 대비 추적 변경과 미추적 소스·테스트 43개를 명시적으로 포함했다.
총 90개 입력에서 정책에 분류되지 않은 제품 경로는 0개였다. 이 정책의 pass/unverified는
증명 검증 성공의 대체 근거가 아니다. 별도 proof 검사 결과를 함께 기록했다.

## 산출물과 남은 범위

- [입력·소스·결과 해시와 실행 영수증](../assessment/proof-implementation-2026-10-07/verification.json)
- [이전 평가와 비교](../assessment/proof-implementation-2026-10-07/comparison.json)
- [Git 입력으로 생성한 전체 증명 6건](../assessment/proof-implementation-2026-10-07/proof-git-final.json)
- [이전 반례 수정과 조작 거부 결과](../assessment/proof-implementation-2026-10-07/fix-controls-final.json)
- [Git 재현 프로그램](../assessment/proof-implementation-2026-10-07/probe_proof.py)
- [수정·조작 재현 프로그램](../assessment/proof-implementation-2026-10-07/probe_fixes.py)
- [Python 전체 로그](../assessment/proof-implementation-2026-10-07/python-full-final.log)
- [화면 빌드 로그](../assessment/proof-implementation-2026-10-07/ui-build.log)

Desktop CI 명시 테스트 목록에 proof 테스트를 추가했으나 이번 작업 트리를 원격 CI에서
실행한 것은 아니다. 설치본·Windows/Linux·실제 화면 조작·독립 홀드아웃·실사용 PR은
이번에 검증하지 않았다. 기존 `auto` 경계 1/8 수치는 재실행하거나 개선했다고 주장하지 않는다.

다음 구현은 S1-e의 버전별 legacy projection과 진입점 통합이다. manifest 인증·최신성,
조직 조치·waiver·명시 제외와 서비스 전체 closure는 후속 설계 범위로 남는다.
