# 다자 평가 후 운영 수정과 검증

2026-10-07. 기준 HEAD는 `d262ec2faff3b98c917e3e99f7b6260cf0514ff3`이며 아래 수정은 아직 커밋되지 않은 작업 트리다.

## 결과

[다자 검토](drift-gate-multi-review-2026-10-06.md)의 R1~R8을 운영 코드에 반영했다. Python **953 passed**, React **122 passed**, TypeScript 검사·UI build·Ruff `E9,F`가 통과했다. 기존 Python 912개 대비 회귀 테스트 41개를 추가했다. 테스트 개수는 실제 PR 판정 정확도나 완전성의 증명이 아니다.

수정 소스로 새 Mac arm64 앱을 빌드하고 ad hoc 서명·strict 서명 검사 후 실행했다. OS outbound 차단·빈 파서 캐시에서 실제 UI/QWebChannel, 8개 언어 문법 분석, 시그니처·rename 검사가 통과했다. 기존 다운로드 설치본을 새 수정의 근거로 재사용하지 않았다.

운영 수정은 세 작업으로 나눠 작성하고 주 검토자가 통합 변경·전체 테스트·실제 앱 실행을 확인했다. 담당 작업의 마지막 교차 검토는 사용 한도로 중단됐으므로 모든 담당자가 최종 변경에 합의했다고 주장하지 않는다. 아래 상태는 주 검토자가 확인한 범위다.

## 수정별 판정

| 항목 | 운영 수정 | 재검증 |
|---|---|---|
| R1: 헤더와 코드 접두사 혼동 | hunk 내부에서는 첫 기호만 diff 표시로 소비 | 실제 Git에서 `++record()`·`--record()` 추가/삭제와 주석 대조군, 복수 hunk 통과 |
| R2: 빈 정책의 정상 pass | `require_check_policy`를 CLI·Desktop·MCP·Action·자체 검사에 공통 적용 | MCP 실제 stdio compact/full 오류, Action 입력 오류, 설정 목록의 빈 정책 허용 유지 |
| R3: 과거 설치본 결과 재사용 | 기존 출력 폴더 거부, 실행기 challenge·fixture 저장소 대조 | 과거 파일 보존·실행 전 거부, 잘못된 challenge 거부, 새 실제 앱 실행 성공 |
| R4: 목록 수집 직후 경합 | 목록·patch·원문·HEAD·미추적 상태를 두 diff 확인 사이에 수집 | tracked 편집·새 미추적 파일·HEAD 변경을 일정한 시점에 주입하면 입력 오류, 안정된 대조군 통과 |
| R5: 정책 의미 완화 | cross-file가 참조하는 선택 그룹도 비교, 비활성 blocker로 major/minor 승격 거부 | 두 기존 반례 거부, 선택 그룹 강화 허용, severity/gate 256개 조합과 위반 부분집합 대조 |
| R6: 기간 오류의 오래된 보고서 | 파서는 `CLIInputError`를 발생시키고 명령 경계에서 오류 출력·종료 처리 | 잘못된 temporal/history 기간이 종료2와 새 오류 보고서, 옵션 이름도 맞게 표시 |
| R7: 검사 단계 결과 혼동 | 앱·외부 검증기가 순서·중복·실행 ID·정확한 diff·rename 경로를 공유 검증 | 최초 결과 재사용, 같은 ID, 단계 교환, 잘못된 경로/추가 코드 등 변형 거부 |
| R8: MCP 미검사 파일 누락 | 실행 출처·정책/입력 digest·미추적 파일 총수를 compact/full에 보존 | 실제 stdio에서 미추적30개, 작은 예산에서 경로5개와 총수30·truncated 표시 유지 |

공통화는 검사 실행의 전제와 패키지 검증의 단계 조건에 집중했다. core의 I/O 경계는 유지했다. 기존 설정 로더와 규칙 목록은 빈 정책을 읽을 수 있으며 실제 판정 실행 시에만 빈 규칙을 거부한다. 단계 계약의 순수 검증 코드는 `desktop/package_check_contract.py`에 분리해 Qt 없이도 회귀 검사할 수 있다.

## 실행 근거

| 검증 | 결과 |
|---|---|
| 전체 Python | 953 passed, 27.99초 |
| React | 122 passed |
| TypeScript·UI build | 통과 |
| Ruff `E9,F` | 통과 |
| 변경 소스 공백 검사 | 통과 |
| 기존 고정 합성21개 | 21/21, FP0/FN0 |
| 기존 일반화 평가 | 지원24/24, 경계1/8 유지 |
| Drift Gate 자체 정책 | pass; 선언된 운영 변경 경로 모두 정책 범위에 포함 |
| 새 Mac 앱 | 실제 자동 UI/브리지·오프라인8언어·시그니처/rename 통과 |

자체 검사는 사용자의 Git index를 바꾸지 않도록 임시 체크아웃에 현재 후보 파일을 복사·등록해 실행했다. 기준은 `d262ec2`, 신뢰 정책은 기존 고정 참조 `ae0028d5edd95d5dd4819939a5801cb028639a6b`다. coverage의 일반 `unmatched` 목록에는 트리거가 없는 평가 자료와 문서도 포함된다. 이것을 미분류 운영 파일로 해석하지 않는다. 문서 내용의 진실성을 자체 정책의 pass만으로 입증하지 않는다.

새 패키지 검증은 실행 ID `07f95e48afd14131b75715c1625d6664`와 해당 실행의 fixture 저장소를 대조했다. 앱 안의 두 숫자 IP 연결은 모두 `Operation not permitted`였고 파서 캐시에 생성된 파일은 0개였다. 마지막 화면은 rename 검사라 원문 없는 rename patch의 휴리스틱 안내가 표시된다. 최초8언어 검사는 모두 `grammar+heuristic`이며 두 사실은 모순되지 않는다.

초기 로컬 빌드 시 spec 폴더를 옮기면서 상대 데이터 경로가 맞지 않아 실패했고 절대 경로로 고쳤다. 일반화 입력을 단일 CLI fixture로 전달한 첫 시도도 형식이 달라 실패했다. 이후 기존 `audit_generalization.py` harness로 같은 입력을 실행해 위 수치를 기록했다. 이 두 실행 오류를 제품의 평가 실패나 성공으로 집계하지 않았다.

## 남은 범위

- 소스·Mac 로컬 앱 검증은 완료했다. 이번 변경의 원격 CI, Windows·Intel Mac 설치본 검증은 아직 실행하지 않았다. Desktop CI 목록에는 새 회귀 파일 세 개를 추가했다.
- Mac은 ad hoc 서명이며 Developer ID 서명·공증이 아니다. 전체 화면의 수동 사용성 검증을 수행하지 않았다.
- 파일 수집은 관측되는 변경을 거부한다. 수집 도중 바뀌었다가 원복되는 모든 순서까지 막는 파일시스템 트랜잭션은 아니다.
- challenge와 fixture 검사는 과거/다른 실행 재사용과 협조하는 앱의 회귀를 검출한다. 악의적인 바이너리의 자체 보고를 인증하는 서명은 아니다.
- 경계 평가의 미지원 사례, 전체 파일 AST, 자연어 문서 정합성, 별도 신뢰 실행기·필수 검사 발행 통제는 이번 수정의 완료 범위가 아니다.
- 커밋·푸시는 하지 않았다. 사용자가 삭제한 `conversation-summary-2026-10-01.md`, `handoff-2026-10-01.md`는 수정 범위에서 제외했다.

## 자료

- [검증 영수증](../assessment/multi-review-fixes-2026-10-07/verification.json)
- [Python 로그](../assessment/multi-review-fixes-2026-10-07/python-full.log)
- [새 앱 결과](../assessment/multi-review-fixes-2026-10-07/package-result.json)
- [자체 검사 결과](../assessment/multi-review-fixes-2026-10-07/self-check.json)
- [고정 평가](../assessment/multi-review-fixes-2026-10-07/fixed-evaluation.json), [일반화 평가](../assessment/multi-review-fixes-2026-10-07/generalization-audit.json)

큰 앱·빌드 캐시·원본 화면은 Git에서 제외되는 `build/multi-review-fixes-20261007/`에 보존한다. 새 자료는 이전 평가 입력과 결과를 덮어쓰지 않는다.
