# Gate와 입력 계약

## S2-c 원본 증거 묶음 저장·재실행 (2026-10-08)

`check/report --evidence-store <경로>`는 명시적으로 원본 입력 보관을 켠다. 기본 검사는
디스크에 원문을 저장하지 않는다. 저장 대상은 history/temporal gate·선택적 LLM 보강
이전의 기본 검사다. 출력의 `execution.evidence_bundle`은 보관 위치와 receipt SHA-256을
알리며, 이후 보강된 출력 전체가 보관된 것이라고 해석하지 않는다.

`bundles/<receipt SHA-256>/`에 입력 capsule, 관찰 manifest, Git evidence metadata,
내용 hash로 이름 붙인 원본 objects, schema 3 결과, receipt, `COMMITTED.json`을 보관한다.
Git blob·tree와 CRLF를 원래 bytes로 보존하며 UTF-8로 해석한 관찰과 별도로 검증한다.
부분 수집·명시 부재·unavailable·빈 파일의 상태도 유지한다. 같은 bytes의 반복 저장은
기존 묶음을 검증하고 재사용하며 다른 attempt는 별도 묶음으로 보존한다.

모든 파일을 비공개 staging directory에 쓰고 파일 fsync·POSIX directory fsync와 재검증
뒤 같은 filesystem의 directory rename 한 번으로 공개한다. `.pending-*`는 commit marker가
있어도 공개된 묶음으로 읽지 않는다. 중간 실패와 강제 종료는 부분 성공으로 반환하지
않는다. rename 후 parent sync 실패는 `publication-unknown`으로 경로를 알려 주고,
해당 묶음을 확인한 뒤 재시도한다. 정상 실패 시 staging을 정리하되 cleanup 실패나
강제 종료로 남은 staging을 자동 삭제하지 않는다.

`bundle verify <묶음 경로> [--expected-receipt-sha256 <별도 보관한 hash>]`는 파일 목록,
size·SHA-256, Git OID, 입력·정책·결과 binding을 재검증한다. 예상하지 않은 파일,
symlink, 경로 이탈, 잘못된 schema, 손상된/누락된 원본은 거부한다. v1 기본 한도는
총 64,000,000 bytes·파일당 8,000,000 bytes·4,096 files이며 reader가 자신의 한도를
적용한다. 이 한도는 bundle I/O에만 적용되고 Git 수집 전체의 자원 예산을 대신하지 않는다.

`bundle replay <묶음 경로>`는 저장소를 다시 읽지 않고 **현재 엔진**으로 실행한다.
전체 정책·shadow proof 결과를 attempt ID와 runtime만 제외해 비교한다. 동일하면 기존
gate 종료 코드(pass/warn 0, fail 1), 달라지면 결과와 차이 표시를 남기고 종료 2다.
잘못된 묶음도 기존 입력 오류 JSON과 종료 2다. source/package/Python의 관찰 identity와
실제 결과 일치 여부를 별도로 표시한다. parser binary·실행 중 code의 인증은 하지 않는다.

unsigned receipt의 hash 일치는 생산자의 신뢰나 의미적 진위를 증명하지 않는다. 전체
묶음을 일관되게 위조하면 별도 hash pin이 없는 integrity 검사만으로는 탐지할 수 없다.
실제 재실행 대조와 독립 보관한 receipt hash의 역할이 다르다. JSON의
`approval_verified=true`를 재실행의 승인 근거로 사용하지 않으며 v1은 해당 입력의 저장·
불러오기를 거부한다. 외부 승인 envelope를 재검증하는 것은 후속 과제다.

원본에는 코드·문서·샘플 값·ignore 이유가 들어갈 수 있다. 명시적으로 선택한 store는
자동 업로드하거나 자동 삭제하지 않는다. 새 directory/file은 POSIX 0700/0600으로 만들고,
기존 상위 directory 권한과 Windows ACL은 사용자 환경을 따른다. 사용자나 관리자 권한의
동시 변조를 격리하는 보안 서비스나 전원 장애 후 모든 OS의 durability 보장은 아니다.
최신 결과 pointer·외부 게시·영구 cache·조직 승인·신뢰 검증기 분리는 아직 구현하지 않았다.

## S1-e 출력 projection·진입점 계약 (2026-10-07)

CLI `check/report --contract-proofs`, MCP `contract_proofs=true`, Desktop 서비스의
`scan_repository(..., contract_proofs=True)`, Action `contract_proofs: 'true'`로
검증된 shadow 증명을 출력에 포함할 수 있다. 기본값은 false이며 기존 schema 3의
판정·verification·집계는 그대로다. 새 projection은 조직의 pass/warn/fail을 계산하지 않는다.

공통 `core/compat/legacy_result.py`가 검증된 proof의 T/F/U와 전체 coverage를
`contract-legacy-projection-v1`의 decision/verification으로 변환한다. 알려진 T/F이고
범위가 열려 있으면 partial, U면 undetermined/unverified다. A=F인 의무는 N/A다.
반환 전에 proof를 검증하고 invalid IR은 정상 출력으로 바꾸지 않는다.

`contract_diagnostics`는 별도 버전 필드이며 role은 `legacy-selector-shadow`다.
기존 YAML에 명시적인 profile/document binding이 없으면 shadow는 unmapped 상태를
유지한다. 그룹 선택 패턴만으로 새 연결을 추측하지 않는다. 기존 정책 결과가 verified여도
shadow가 U일 수 있으며 새 진단은 게이트를 바꾸지 않는다. 직접 명시 요청의 proof를
projection하는 API는 별도로 제공하며 정책 시행으로 간주하지 않는다.

full 출력에는 projection과 전체 proof 결과를 담고 compact에는 projection만 담는다.
범위·입력 identity와 참조는 같은 공통 변환을 사용한다. `records_seen`, `retained_count`,
`omitted_record_count`, `retention_limit`, `trace_truncated`를 출력하고
`complete_policy_coverage=false`를 명시한다. 기록이 없는 입력도 검증 완료로 표시하지 않는다.
CLI 검증기 실패는 종료 2와 `result_validation_error`를 반환하며 정상 result 필드는 없다.

최신성·원본 인증·서비스 closure와 새 기본 정책 전환은 후속 범위다. schema 3은 유지하며
새 필드는 opt-in 확장이다. Markdown·HTML도 같은 projection 값을 표시한다.

## S1-d 내부 증명·결과 검증 계약 (2026-10-07)

`inspect_contract_proof`는 명시적 `PlanRequest`와 관측치를 받아 `contract-proof-result-v1`을
생성한다. atom/not/all/any/conditional DAG에 T/F/U 판정, 충분한 자식 근거,
전체 자식의 범위 coverage를 남긴다. 의무는 `¬A ∨ R`이며 알려진 F가 unknown 형제
때문에 사라지지 않는다. discovery의 비활성·열린 영역도 최종 범위에 포함한다.
`decision_proven`은 받아들인 분석 전제를 조건으로 한 논리 판정이며 원본의 진위,
parser 정확도, 현재 HEAD와 서비스 전체의 완전성을 인증하지 않는다.

계획은 수집된 소스 관측치의 digest에 결합된다. 경로가 같아도 내용·등록 route·상태가
다른 소스로 재사용하면 거부한다. 문서 관측치 digest도 결과에 포함하며 원문은
출력하지 않는다. 삭제 문서는 종류별 검사 전에 공통 상태 검사를 통과해야 한다.
`contract-obligation-evaluation-v1`에도 전체 discovery와 문서 digest가 추가된다.

`validate_proof_evaluation`과 `validate_proof_payload`는 호출자가 별도로 확보한
`ProofContext`를 요구한다. 받은 JSON의 `admitted_context`를 그대로 신뢰하여 다시
검증에 넣는 것은 원본 검증이 아니다. 검증기는 선언된 구조, 참조·profile,
충분한 evidence 범위, 독립적인 진리값 재계산, 자식 근거, 모든 자식의 coverage,
순환·미도달 노드와 상한을 검사한다. 실패는 `ResultValidationError`로 종결한다.
JSON이 최신성·원본 인증을 주장하면 현재 스키마에서는 거부한다.

기본 상한은 4,096 노드, 16,384 간선, 깊이 128이다. 방어적 IR 처리 상한이며 성능
SLA가 아니다. family analyzer의 적용성·문서 요구 결과는 명시적으로 받아들인
원자 전제다. 문서 선택의 세부 논리나 AST 자체를 독립적으로 다시 증명한 결과가 아니다.
명시 제외·waiver·조직 조치·manifest 신뢰·최신성 검증은 이 단계의 IR에 구현하지 않았다.

새 증명은 내부 API 및 `AnalysisSession.shadow_contract_proofs`에 연결한다. legacy gate,
YAML 의미와 CLI/MCP/Desktop의 기존 출력은 유지한다. 128개 shadow 보관 한도는 최근
진단 보관량이며 전체 정책 처리 완료의 인증이 아니다. S1-e 외부 projection은 후속이다.

## 검사 의미

Gate는 정책이 요구한 변경과 근거의 충족을 판정한다. 코드 품질·실제 PR 정확도·전체 문서 의미를 보증하지 않는다. `rule_decisions`의 `unmatched`는 통과한 규칙이 아니라 트리거가 맞지 않은 규칙이다. 분석 방식과 미지원 사유는 `scan_metrics.analysis_notes`에 남는다.

명시적 `paths`는 문서의 변경 여부를 확인한다. `env-keys`, `api-routes`, `api-schema`, `auto-strict`와 제한적인 `auto` 내용 검사는 지원 문법에 한해 추가 확인한다. `auto` 경로 대체는 호환 목적으로 유지하지만 내용 검증 완료로 표시하지 않는다.

## CLI와 Git 입력

- `check`, `report`, `review`, `self-audit`의 변경 수집 실패는 종료 코드 **2**다. 없는 base, 비저장소, Git timeout을 빈 변경으로 바꾸지 않는다.
- JSON 모드의 입력 실패는 `{"error":{"code":"input_error","message":"..."}}`다. stderr에도 오류를 쓴다. 정상 빈 `review --format json`은 `review` 객체와 빈 목록을 반환한다.
- `check`의 규칙 위반 `fail`은 종료 1, `warn/pass`는 종료 0이다. `review --fail-on`은 발견 항목 심각도에 따른 종료 1을 제어한다. 입력 실패 종료 2는 이 설정과 무관하다.
- 로컬 GitAdapter는 base를 commit으로 확정하고 NUL 구분 경로를 읽는다. 외부 diff/textconv를 끄고 literal pathspec과 호출별 30초 제한을 사용한다. review/self-audit는 이때 수집한 patch를 재사용한다.
- 새 파일은 Git index에 추가해야 수집된다. 작업 중인 디스크 전체가 원자적인 snapshot으로 고정되는 기능은 아직 없다.
- core `run`은 adapter가 로드한 `Policy`를 받는다. `policy_path`만 전달하는 호출은 거부한다.

## 지원 계약 내용

- literal HTTP route 제거는 문서의 제거 집합에서 다시 추가된 항목을 뺀 순제거로 확인한다. 같은 경로를 삭제 후 재추가하거나 다른 대상 문서로 옮기는 것은 제거 확인이 아니다.
- Python 환경 키는 파싱 가능한 조각의 실제 `os.getenv`, `os.environ.get`, `os.environ[...]`, 기존 `getenv` 호출에서 정적 문자열 키를 읽는다. 설명 문자열·주석은 접근으로 취급하지 않는다.
- 변경 전후 키 집합에 같은 키가 있으면 새 키가 아니다. `.strip()` 같은 값 처리만 바뀐 경우 새 환경 키를 요구하지 않는다. 새로운 정적 키는 샘플 파일의 키 목록과 대조한다.
- 불완전 Python 조각은 빈 키 집합으로 단정하지 않고 기존 보수적 휴리스틱을 유지한다. 별칭·동적 키·전체 모듈 심볼 해석은 지원 완료로 주장하지 않는다.

## 회귀 기준

`test_git_collection.py`, `test_contract_route_regressions.py`, `test_development_regressions.py`의 오류/정상 통제를 유지한다. 고정 합성 평가를 수정 전후 같은 입력으로 비교하고, 새 변형 검사는 기존 합성 점수와 따로 기록한다. 테스트 이름 힌트는 실제 행동 테스트 부재의 증명이 아니다.

## 2026-10-06 입력·범위 보완

`check`는 기본 정책을 로컬 Git 루트에서 읽고 명시적 `--policy`는 호출 위치에 상대적으로 읽는다. 원격 PR 모드는 로컬 Git 저장소를 요구하지 않는다. 정책을 한 번 읽어 평가와 출력에 같은 원문을 사용한다. CLI와 데스크톱 검사는 빈 규칙을 입력 오류로 거부한다. core의 직접 `Policy()` 호출은 기존 호환 계약을 유지한다. YAML 중복/알 수 없는 키, 잘못된 타입, bool/0/음수 실패 임계값은 거부한다. 정책은 1MB·깊이20·alias100·event20000으로 제한하고 YAML merge 키는 지원하지 않는다.

`--comparison-mode commit`이 기존 기본값이며 `merge-base`는 내 브랜치 변경을 비교할 때 사용한다. 정책 오류·Git 입력 오류는 CLI 종료2와 새 오류 JSON을 만든다. 고정 출력 경로를 원자 교체하며 실행 ID·정책 digest·비교 SHA·dirty·미등록 파일 제외 목록을 기록한다. 쓰기 실패나 강제 종료 시 새 파일을 보장하지 않으므로 종료 코드와 실행 ID를 함께 확인한다.

rename은 이전/현재 경로로 trigger와 ignore를 판단하며 양쪽 모두 ignore일 때만 제외한다. require 충족은 현재 경로에 존재하는 변경만 인정한다. 문서/테스트 전용 변경도 명시적인 정책 trigger가 있으면 평가한다. `evaluated_rules`는 실제 적용 규칙 수이며 skip/no_policy를 JSON에 포함한다.

`*extra`, `**options`, `#define`을 공통 prefix만으로 주석 처리하지 않는다. Python 로컬 Git 분석은 최대1MB before/after 원문을 어휘 문맥에 사용하지만 보고서에는 원문 사본을 넣지 않는다. 원격/API 및 합성 입력에 원문이 없으면 Python diff 토큰 추정은 휴리스틱이다. hunk 밖에서 시작한 문자열 문맥은 여전히 한계다. 지원하지 않는 언어의 주석 조각은 보수적으로 구현 변경으로 남아 경고가 늘 수 있다. 문자열 값 변경은 구현 변경이다.

self-audit schema2의 `related-evidence-found`는 관련 변경 참조만 뜻하며 항상 `behavior_verified=false`이다. 경로 조각으로 모든 파일을 연결하지 않고 정확한 경로나 유일한 파일명만 연결한다. 이는 주장 내용의 진위를 자동 검증하지 않는다.

정책 의무 비교는 기존 all_changed 그룹에 any_changed를 추가하는 완화를 거부한다. 현재 정책 로더와 core 직접 호출도 두 배열의 동시 지정 자체를 오류로 거부한다.

## 논리 검사 schema 3

규칙 내부의 그룹 이름은 비어 있거나 중복될 수 없다. 교차 조건 이름 중복·미정의 참조도 오류다. 그룹은 비어 있지 않은 any_changed 또는 all_changed 중 하나만 지정한다. 기존 동시 지정 정책은 의도에 맞는 하나를 선택해 이전한다.

최상위 schema_version=3과 verification, 요약의 undetermined_rules/unverified_rules, 그룹의 decision/verification/content_mode가 추가된다. 규칙 판정은 satisfied/violated/waived/undetermined/not-applicable, 검증 상태는 verified/partial/unverified/not-applicable이다. rule_decisions.status에는 undetermined가 추가된다. paths의 verified는 파일 조건을 확인했다는 의미다. 알려진 위반만 violations와 심각도 수에 포함한다. 확인된 위반과 확인 불가가 공존하면 위반을 유지하고 verification은 partial이다. 조건의 변경 강도 자체를 확인하지 못했으면 단지 문서가 없다는 사실로 조건부 위반을 입증하지 않는다.

gate.on_unverified는 fail(기본값) 또는 warn이다. 기존 엄격한 검사의 차단을 유지하며, warn 전환은 정책 완화다. 확인 불가만으로 fail이면 blocker 수가 0일 수 있다. pass/warn/fail·CLI 종료 코드는 유지한다. 기존 auto 경로 대체는 pass 가능하지만 verification=unverified와 이유가 남는다. 이 호환 경로는 on_unverified의 적용 대상인 undetermined와 다르다. 내용 검증이 필요하면 명시적 내용 모드로 이전한다. confidence는 경로 매칭 구체성이며 정확도 확률이 아니다(confidence_basis에 명시).

CLI·MCP·Desktop·Action은 adapters/inspection.py에서 실행 전제·의미 신호 분석·순수 엔진 호출·실행 기록을 공유한다. 외부 입력 수집은 각 어댑터에 남는다. 입력 digest에는 비직렬화 before/after 원문의 해시가 포함되며 원문 사본은 보고서·이력에 넣지 않는다. policy_digest_kind는 원문(source) 또는 직접 호출의 정책 객체(policy-object)를 구분한다.

### api-schema 지원 범위

그룹에 content: api-schema와 명시적 상대 경로의 OpenAPI 3 JSON(예: all_changed: [openapi.json])을 지정한다. 트리거는 Python 모듈이다. 직접 import한 FastAPI()/APIRouter()의 최상위 메서드 데코레이터와 같은 파일의 직접 BaseModel 응답 모델을 실행 없이 전후 비교한다. 직접 str/int/float/bool 필드, 필수 여부와 단순 상수 기본값을 비교한다. URL이 같아도 필드 변경을 탐지하며 모델 이름만 달라 구조가 같으면 문서 의무 없음(not-applicable)이다.

문서는 해당 메서드·경로의 200 → application/json 응답 객체 또는 직접 #/components/schemas/Name 참조로 대조한다. all_changed는 각 문서가 전체 계약을 충족해야 하고 any_changed는 하나의 완전한 문서로 충족한다. 이미 정확한 변경되지 않은 문서도 인정한다. 문서 부재는 불일치, 읽기 실패·미지원 스키마는 확인 불가다. JSON 중복 키와 비유한 숫자도 거부한다.

별칭·다중 상속·추가 데코레이터·동적 경로·파일 간 router 조합·동적 prefix·외부 모델·중첩/nullable/container 타입·Field/validator·추가 HTTP 응답/미디어 타입·OpenAPI YAML은 지원하지 않는다. 지원하지 않는 관측 입력은 빈 계약이나 파일 조건 충족으로 낮추지 않는다. 실제 HTTP 서버·배포 경로·클라이언트 호환성·자연어 문서의 진실성을 보장하는 검사는 아니다. 호환성 파괴를 자동 단정하지 않고 응답 선언 구조와 문서의 일치를 확인한다.

최대1MB 원문을 로컬 Git에서 수집한다. PR은 고정 head와 compare API의 merge-base에서 원문을 읽는다. 기준 또는 원문을 얻지 못하면 확인 불가다. 파일시스템 전체의 원자적 snapshot을 보장하지 않는 기존 한계는 유지한다.

### 계약 비교의 경계와 집계

상대 경로의 framework/model import, 모듈 수준의 조건문·반복문·예외/컨텍스트 선언, 기본 타입 이름을 가리는 모델 필드, 해석하지 못한 함수 데코레이터는 api-schema에서 확인 불가다. 상대 import의 이름이 fastapi 또는 pydantic이라는 이유로 절대 import와 동일하게 인정하지 않는다. 직접 절대 import가 실제 프레임워크를 가리킨다는 전제에서 정적 선언을 비교하며, 실행 환경의 패키지 해석·모듈 실행 성공·Python 전체의 이름 해석을 증명하지 않는다.

OpenAPI Path Item의 $ref는 해결하지 않으므로 해당 경로의 존재·삭제 모두 확인 불가다. operation이 없다는 사실과 잘못된 null 값은 구분한다. 한 문서 안의 계약 항목을 모두 평가하여, 확인된 불일치와 해석 불가 항목이 공존하면 violated/partial로 남긴다. 문서 대안의 any 집계에서도 partial을 verified로 올리지 않는다. 다른 문서가 전체 계약을 확인하여 충족한 경우에는 그 완전한 대안을 근거로 verified/satisfied가 가능하다. 항목·문서 입력 순서가 판정과 검증 상태를 바꾸지 않는다.

api-schema 규칙에 변경 강도 조건이 있으면 전체 소스의 응답 계약 비교를 강도 필터 전에 적용한다. 실제 Git diff가 모델 필드 몇 줄만 포함해도 확인된 응답 계약 변경은 route-contract-change로 평가한다. 이를 확인할 입력이 없거나 지원 범위 밖이고 독립적인 강도 근거도 없으면 조건을 확인 불가로 유지한다. 모든 트리거가 이 상태이면 문서 부재를 확정 위반으로 단정하지 않는다.

## 다자 검토 후 실행 계약

설정용 로더는 빈 규칙 목록을 읽을 수 있지만, CLI·Desktop·MCP·GitHub Action·자체 검사처럼 판정을 실행하는 경로는 공통 `require_check_policy`를 사용하여 이를 입력 오류로 거부한다. 설정 목록과 편집 기능은 이 실행 전제와 구분한다.

변경 줄은 hunk 내부에서 첫 기호만 diff 표시로 해석한다. 따라서 `++call()` 추가나 `--call()` 삭제를 `+++`·`---` 파일 헤더로 버리지 않는다. Git 수집은 파일 목록을 읽기 전부터 전체 diff를 확인하고 원문·상태 수집 후 다시 확인한다. 변경이 관측되면 재실행을 요청하며, 임의 편집 후 원복까지 검출하는 파일시스템 트랜잭션을 보장하지 않는다.

정책 의무 비교는 교차 조건이 참조하는 선택 그룹의 내용도 보존한다. `major/minor`를 `blocker`로 올려도 blocker 실패가 비활성화되어 판정이 약해지면 허용하지 않는다. `check --temporal-window`와 `history --last`의 잘못된 값은 공통 입력 오류 처리에서 종료2와 새 오류 산출물을 만든다. 내부 파서에서 직접 종료하여 이전 성공 보고서를 남기지 않는다.


## 2026-10-07 논리 후속 보완

### 정적 router 조합

api-schema는 같은 모듈에 직접 선언한 FastAPI 앱 하나와 APIRouter들의 정적 조합을 지원한다. APIRouter(prefix="/v1")와 include_router(child, prefix="/api")의 문자열 prefix를 누적한다. 여러 줄 메서드 데코레이터도 전체 AST에서 읽는다. 앱에 연결하지 않은 router의 경로는 해당 앱의 계약에 포함하지 않는다. 앱이 없는 경우에는 단일 standalone router만 허용한다.

include_router는 모든 route·receiver 선언 이후에 있어야 하며, 자식의 조합은 부모에 포함하기 전에 끝나야 한다. 이 제한은 라우터 등록 순서의 버전 차이를 추정하지 않기 위한 것이다. 다른 파일의 router, 동적 prefix, 추가 설정, 다중 앱, 순환·중복 경로, path converter, 불투명한 app/router/model 메서드 호출과 외부 함수로의 전달은 확인 불가다. 깊이 32, 방문 256, 최종 경로 256을 넘는 단일 모듈도 확인 불가다. 실제 배포 prefix와 middleware까지 해석하지 않는다.

### 소스의 부분 확인

메서드·최종 경로는 확정했지만 단순 응답 필드의 타입 표현만 미지원인 경우 해당 계약에 UnknownResponse를 남긴다. 예를 들어 직접 BaseModel의 list[int] 필드는 아직 비교하지 않으나, 다른 경로의 확인된 문서 불일치를 숨기지 않는다. 알려진 불일치와 공존하면 violated/partial이다. 모든 변경이 이런 확인 불가 상태라면, 문서 부재만으로 위반을 확정하지 않는다.

반면 외부 모델·동적 등록·알 수 없는 경로·모델 실행 코드 등 routing scope를 확정할 수 없는 입력은 전체 비교를 확인 불가로 유지한다. 모듈 사이의 같은 메서드·경로도 거부한다. 임의로 해석에 성공한 파일만 합쳐 확정 위반을 만들지 않는다. 구체적 모듈/경로의 입력과 사유는 기존 trigger_files와 그룹 근거에 남는다.

### 검사 실행 범위의 캐시

각 evaluate 호출은 전용 AnalysisSession을 만든다. Python 계약 추출과 OpenAPI JSON 파싱을 분석 모드·내용 SHA-256 기준으로 재사용한다. 성공·확인 불가 모두 캐시하며 최대 128항목을 유지한다. 전역 캐시와 디스크 캐시를 사용하지 않고 다음 실행은 새 세션을 쓴다. 전체 소스나 오류를 수정하면 새 내용의 키로 다시 분석한다. 캐시는 입력 판정이나 게이트 의미를 변경하지 않는다.

### 독립 프레임워크 oracle

개발용 oracle extra는 FastAPI 0.115.12와 Pydantic 2.11.5를 고정한다. 테스트가 작성한 통제 소스만 실행하여 프레임워크가 생성한 OpenAPI와 정적 결과를 대조한다. 운영 분석은 대상 저장소의 소스를 실행하지 않는다. 직접 앱·router·중첩·반복 include와 기본 타입/기본값의 정상·변조 통제를 CI 목록에 연결했다. 이 검사는 실제 서비스의 HTTP 응답·배포 설정·최신 모든 프레임워크 버전의 일치 보장이 아니다.

## 2026-10-07 auto 개선안 반영

### 교차 조건의 소스 범위

상위 when과 변경 강도는 규칙 적용 여부를 결정한다. cross_file 관계는 그 뒤에 평가하며 자체 when_any_changed에 해당하는 파일에서 내용 변경을 추출한다. 상위 트리거 파일을 관계의 내용 입력으로 재사용하지 않는다. rename의 이전 경로와 현재 경로, unchanged 제외, ignore 조건은 공통 선택 계약을 따른다. 관계 그룹 결과에는 relation과 source_files를 남기며 RuleDecision.trigger_files는 상위 when의 근거를 유지한다. 상위 강도 자체가 불확실하면 관계 문서 부재도 확정 위반으로 단정하지 않는다.

### 명시적 auto-strict

그룹에 content: auto-strict와 명시적 상대 문서 경로를 설정한다. 기존 auto는 호환 경로이며 자동 이전하지 않는다. auto-strict는 전체 Python 전후 소스의 os 환경 접근·FastAPI route·response_model을 구분한다. 응답 모델이 있으면 api-schema, 환경 접근이면 env-keys, 나머지는 등록된 FastAPI 경로를 비교한다. 혼합 환경/API 또는 Python/JS 범위는 명시적 그룹으로 나누도록 확인 불가를 반환한다. 해석 불가나 부족한 입력을 paths로 대체하지 않는다. 입증된 변경 없음은 not-applicable이고, unknown은 gate.on_unverified를 따른다. paths의 의미는 계속 파일 변경 조건이다.

Git은 Python과 JS/TS의 1MB 이하 전후 소스를 수집한다. 원격 명시적 내용 모드도 merge-base/head의 소스를 수집한다. api-routes에 전체 소스가 있으면 등록 범위를 비교하고, 기존 patch 입력은 제한된 literal route 검사를 유지한다. 입력 부족 상태에서 router prefix·체인 등록 또는 동적 환경 접근을 발견하면 강도 필터에서 무관 변경으로 버리지 않고 판단 보류한다. 단순 후보 인식은 실제 계약 입증과 구분한다.

### 문서 형식과 환경 getter

OpenAPI 3.0/3.1 JSON과 안전하게 정규화한 YAML을 사용한다. YAML은 adapters에서 해석하며 중복·비문자 키, merge, alias, 20단계 깊이, 20,000 이벤트, 1MB 초과, 비유한 값과 사용자 객체 태그를 거부한다. JSON도 중복 키·비유한 값·동일 깊이/노드/크기 상한을 검사한다. 원문과 정규화 결과의 해시를 실행 입력에 결합하며 원문은 보고서에 추가 직렬화하지 않는다. PathItem/operation의 외부·지역 참조는 아직 해석하지 않아 unknown이다. 응답 모델 비교에서는 기존 직접 components/schemas 참조만 지원한다.

구조화 문서의 patch 조각을 Markdown으로 읽어 operation이 없다고 단정하지 않는다. api-routes/auto의 glob은 이미 수집한 변경 문서만 읽는다. 변경 없는 모든 glob 문서를 저장소 전체에서 검색하는 기능은 없다. 정확한 전체 문서 조건이 필요하면 explicit 경로와 auto-strict/api-schema를 사용한다. Markdown 전체 내용의 method/path 표기는 선언된 텍스트 계약이며 임의 설명문의 의미나 실제 API를 증명하지 않는다.

Python은 직접 os import와 모듈/getenv/environ 별칭의 정적 키를 지원한다. 재할당·이름 가리기·getter 전달·reflective 변경·동적 키는 unknown이다. 기존 입력이 불확실하면 새 키 집합 차이를 확정 사실로 승격하지 않는다. 확인된 새 키와 별도 unknown이 함께 있으면 알려진 문서 누락은 violated/partial로 보존한다. 전체 입력으로 신규 키가 없음을 확인하면 not-applicable이다. JS process.env literal은 기존 제한 검사를 유지하며 JS/TS 환경 scope 전체의 이름 해석은 입증하지 않는다.

### Express의 제한된 등록 범위

JS/TS의 전체 소스는 adapter의 문법 트리에서 Express 기본 ESM import, 직접 const app/router, 단순 literal 경로, 직접 method 또는 route().get().post() 체인과 같은 모듈의 use(prefix, router)를 확인한다. 앱에 등록되지 않은 router는 최종 경로에서 제외한다. core는 정규화한 전후 경로 사실만 소비하며 외부 파서 의존성이 없다. 사실 해시도 실행 영수증에 포함한다.

기본 import 없는 유사 객체, CommonJS·named import, 동적 경로/prefix, path-to-regexp 패턴, 재할당·이름 가리기·외부 전달·조건부 등록·불투명한 호출·중복/순환은 unknown이다. AST 20,000노드, 깊이32, 방문256, 최종 경로256으로 제한한다. 패키지 import가 실제 Express이며 handler 바인딩이 유효하다는 전제의 정적 등록 비교다. 코드 실행 성공, 권한·middleware·응답 shape·배포 prefix까지 보증하지 않는다. 운영에서는 저장소 코드를 실행하지 않는다.

### 평가 축과 프레임워크 대조

audit_auto_contracts.py는 별도 고정 suite의 파일을 임시 Git 저장소에 전후로 구성하여 실제 수집을 거친다. 추출 사실·의무 판정·verification·게이트를 각각 비교한다. 기존 generalization v1은 수정하지 않는다. 새 suite도 작성자가 만든 비맹검 회귀 자료이며 실제 PR 정확도가 아니다. FastAPI oracle은 GET/POST/PUT/DELETE의 전후 필드·메서드·삭제·변경 없음으로 확장한다. Express oracle은 고정4.21.2 테스트 의존성과 작성한 앱만 로컬 HTTP로 실행해 GET/POST/PUT/DELETE 정상 경로와 잘못된 경로를 대조한다. 외부 실제 사용자 코드나 최신 프레임워크 모두의 동작 보장은 아니다.
## 2026-10-07 심화 설계의 정확성·재현성 보완

`auto-strict`는 환경 키뿐 아니라 응답 모델 없는 API 경로의 범위도 확인한다. 같은 Python 입력에서 환경·API 범위가 함께 있으면 명시적 그룹으로 나누기 전까지 `undetermined/unverified`로 남긴다. 변경 없는 환경 키를 근거로 API 검사 전체를 `not-applicable`로 만들지 않는다. 해석 가능한 미사용 FastAPI import만으로 API 의무를 만들지는 않는다. 응답 모델 계약과 경로 계약이 함께 확인되면 응답 구조까지 보는 `api-schema`를 선택하며, 이름의 알파벳 순서로 검사 종류를 선택하지 않는다.

이 보완은 혼합 계약의 안전한 보류 경로다. 여러 계약 종류의 문서·의무를 자동으로 모두 구성하는 프로필 registry가 완성된 것은 아니다. 혼합 프로젝트에서는 `api-routes` 또는 `api-schema`와 `env-keys`를 별도 그룹으로 지정한다.

Express의 type-only import와 const 선언은 문자열 접두어가 아니라 AST 토큰으로 판별한다. 주석·탭·줄바꿈이 타입 전용 import를 실행 가능한 값 import로 바꾸지 않는다. 이 분석은 대상 애플리케이션을 실행하거나 프로젝트 전체 TypeScript 타입 검사를 수행하지 않는다.

OpenAPI JSON은 `NaN`·`Infinity` 토큰뿐 아니라 지수 오버플로로 생긴 비유한 float도 모든 중첩 값에서 거부한다. 이 경우 `unsupported_numeric_range` 이유로 판단 불가를 남긴다. 유한 JSON 값과 기존 단순 schema 비교는 유지한다. 임의 정밀도 숫자·RFC 8785 전체 적합성 지원을 추가한 것은 아니다.

만료가 있는 ignore를 직접 `core.run()`에 전달하면 `EvaluationContext(evaluated_on=date(...))`가 필요하다. 날짜를 주지 않으면 현재 시간을 몰래 읽지 않고 해당 ignore를 거부한다. CLI·MCP·Desktop·Action의 공통 inspection adapter는 실행 시작 시 UTC 날짜를 입력으로 만든다. 만료 날짜 당일까지는 유효하며 그 다음 날짜부터 만료다. 만료가 없는 ignore의 기존 계약은 유지한다.

실행 기록의 `evaluation_context`에는 UTC 평가 날짜가 있고, `input_digest_version=3`의 입력 digest는 파일 입력과 평가 날짜를 함께 포함한다. 과거 결과 재현은 당시 날짜를 명시해야 한다. 과거 날짜로 재현한 승인을 현재 유효한 승인으로 취급하지 않는다. 이 변경은 순수 판정의 날짜 의존성을 명시한 것이며 신뢰 실행·서명·외부 승인 체계 전체를 완성한 것은 아니다.

## 내부 typed facts 연결 단계

2026-10-07 S1-a는 내부 분석 결과를 `ExactFacts`, `BoundedFacts`, `UnknownFacts`와
변화 타입으로 구분한다. unknown의 상한은 `None`(top)이며 빈 집합과 다르다.
사실의 범위·계약 종류·프로필 ID/버전이 다르면 비교를 거부한다.
생성자는 잘못된 identity, must/may 역전, 확정 추가/삭제 중복과 이유 코드 누락을 거부한다.

완전 소스를 사용하는 기존 route·Python env 경로가 이 타입을 거치며 기존 gate/YAML/JSON
출력 계약은 유지한다. route의 Exact는 선택된 모듈 안의 기존 지원 부분집합만 뜻한다.
서비스 전체 discovery·dependency 완전성이나 원문 출처 인증을 증명하지 않는다.
adapter route facts는 원문 hash로 위장하지 않고 별도 참조로 남긴다.
추가/삭제 상태의 부재는 legacy 입력의 선언이며 검증된 Git absence certificate가 아니다.

새 Python env observation API는 patch 입력을 항상 unknown으로 처리하고 그 휴리스틱 키를
확정 사실로 보존하지 않는다. 기존 patch 기반 env 경로는 호환성을 위해 유지한다.
기존 service 전체 새 키 규칙을 바꾸거나 mixed auto 의무 집합을 구현한 단계는 아니다.
S1-b–e(profile discovery·planner·proof DAG·새 projection)는 S1-a에서 구현하지 않았다.

## 내부 profile discovery 연결 단계

2026-10-07 S1-b는 기존 Python env/FastAPI route/명시 response_model과 Express 등록
부분집합을 불변 profile registry로 정의한다. 요청한 파일 × 계약 종류의 모든 domain을
유지하며, profile 없음·미지원 바인딩·불완전 입력은 open과 안정 reason code로 기록한다.
도메인 전체나 일부가 빠진 DiscoveryResult, 중복 입력 경로, 모호한 profile 선택은 거부한다.

후보 활성화는 분석을 시작할 신호이며 변화나 문서 의무의 확정이 아니다. route와 response
후보는 따로 남긴다. 미사용 FastAPI import·주석·설명 문자열만으로 후보를 만들지 않는다.
response profile은 명시 response_model을 대상으로 하며 임의 응답 본문 스키마 추론은 아니다.

새 discovery를 실제 auto-strict 경로에서 호출한다. S1-b는 기존 호환 힌트만 현재 selector에
사용하므로 기존 gate·YAML·외부 JSON 계약과 혼합 범위의 unknown 동작을 유지한다.
전체 domain의 open/closed·후보 정보는 새 내부 API에서 따로 조회할 수 있다.
legacy selector의 verification과 새 discovery의 coverage가 같다고 해석하지 않는다.

Express의 전체 세 계약 요청에서는 route만 닫힐 수 있고 env/response는 미지원으로 남는다.
명시 route-only 요청의 complete는 그 부분집합에만 적용된다. 빈 선택에는 완전성 인증이 없다.
service scope와 imported-consumer closure는 인증하지 않으며 결과에도 이를 명시한다.
profile 선언만 추가해서 새 분석기나 버전을 지원한 것으로 취급하지 않는다.
engine/profile/parser digest의 인증, 정책 제외 증명과 필수 guard 집행은 후속 단계다.

S1-b에서는 모든 적용 의무 구성과 문서 배정, proof·projection을 구현하지 않았다.

## 내부 obligation planner 연결 단계

2026-10-07 S1-c는 `PlanRequest`·`DocumentBindings`·`ObligationPlan`·`PlanEvaluation`을
추가한다. 새 bindings의 내부 schema는 `contract-document-bindings-v1`이다.
프로필 ID/버전별 문서 selector와 any/all 결합을 명시하며, 확장자나 기존 auto group의
경로만으로 연결을 추정하지 않는다. 현재 YAML에 입력할 수 있는 새 옵션이 아니다.

활성 계약을 모두 계획하고, 같은 프로필의 비활성 모듈도 source scope에 포함해 파일 간
env 키 이동을 신규 키로 오인하지 않는다. API response는 route 의무를 대체하지 않는다.
요청·discovery·assessment의 source scope가 다르면 거부하며 relation 요청은 그 relation의
선택 source만 사용한다. 누락 assessment는 unknown 의무로 유지한다.

필수 open domain guard를 계획에서 제거할 수 없다. 문서 연결이 없는 적용 의무는 unknown,
문서 관찰이 수집되지 않은 selector도 unknown이다. 문서가 없다는 명시 관찰과 읽기 실패를
구분한다. 새 env 관찰은 전체 선택 프로필의 전후 구간을 비교하므로 다른 모듈의 unknown
old getter를 무시하고 새 키를 확정하지 않는다. env 삭제만으로는 신규 키 의무를 만들지 않는다.

glob selector에 대해 현재 전달된 문서 목록은 전체 열거 인증이 아니다. 미수집 가능 대안을
unknown으로 남긴다. 관찰한 정합 문서의 T 증거는 유지하지만, 관찰 문서가 모두 불일치라는
이유만으로 전체 OR을 F로 확정하지 않고 completeness도 닫지 않는다.

새 평가의 conditional은 `not(A) or R`의 Strong Kleene 값이다. 확인한 F와 unknown이
함께 있으면 전체 truth는 F로 유지되며 completeness는 별도다. 문서 OR에서 T 대안이
있어도 미확인 다른 대안을 completeness에서 지우지 않는다. 이것은 아직 proof DAG가 아니다.

기존 auto-strict는 planner를 shadow 실행하고 기존 호환 힌트만 gate에 적용한다.
기존 YAML은 새 프로필별 연결을 선언하지 않았으므로 shadow에서 unmapped로 표시된다.
진단용 trace는 해당 AnalysisSession의 최근 limit개만 유지하며 전체 정책 평가 인증이 아니다.
legacy 결과·YAML·외부 JSON 의미를 유지하며 새 내부 결과는 명시 API에서만 조회한다.

source/profile 부분집합의 주장만 평가한다. 서비스 범위·dependency closure·원문 manifest
인증·새 gate 기본값·전체 정책/ignore/threshold migration은 후속 단계다. S1-d–e에서 proof
DAG·validator·외부 projection과 진입점의 일관성을 연결한다.
## S2-a: 분석 전 불변 입력 캡처

공통 inspection은 코드·patch·문서·정책·ignore 근거·UTC 평가 날짜·옵션을
`InspectionSnapshot`에 봉인한 뒤 private copy로 분석한다. 원래 객체와 이후 실행의
입력은 공유하지 않는다. `inspect_snapshot`은 저장소를 다시 읽지 않고 캡처된 입력을
현재 엔진으로 재실행한다. capsule은 프로세스 메모리에만 보관하며 JSON 보고서에는
원문을 넣지 않는다. 엔진·파서까지 고정한 장기 재현 프로토콜은 후속 단계다.

`execution.input_capture`는 버전 있는 manifest와 입력·manifest SHA-256을 가진다.
present의 빈 텍스트, adapter가 선언한 absent, unavailable, not-collected, limited,
unsupported를 구분한다. rename의 before 경로와 삭제 파일의 before 관찰도 보존한다.
해시는 adapter가 전달한 문자열을 UTF-8로 표현한 bytes에 대한 값이다. 기존 Git
adapter의 대체 문자 디코딩과 줄바꿈 변환이 있어 원본 disk/blob bytes 인증으로 쓰지 않는다.

Python JSON encoding v1은 object key를 정렬하고 array 순서·Unicode code point를
보존하며 NaN/Infinity를 거부한다. 파일 관찰 순서와 정책 group 순서는 유지한다.
RFC 8785 준수나 다른 언어 producer와의 hash 일치를 주장하지 않는다.

정책 원문과 평가 정책이 서로 다르면 input error로 거부한다. 정책·문서 읽기는
1 MB까지 한 번 읽고 관찰 가능한 읽기 중 변경을 검사하며 줄바꿈을 보존한다.
원문을 읽은 뒤 YAML 해석이 실패하면 원문은 present로 보존하고 의미 입력은
unavailable로 남긴다. 환경 문서 값은 private capsule에만 보관하고 기본 file JSON과
공개 manifest에는 포함하지 않는다.

이 단계의 atomicity는 per-artifact-observation이며 전체 저장소의 동시 수집 보장이
아니다. revision 인증, 신뢰 정책 authority, 전체 selector 열거, 현재 HEAD 최신성도
아직 인증하지 않는다. 보고서의 해당 필드는 false 또는 unverified다. CLI·MCP·Desktop
서비스·Action의 공통 inspection에 적용하며 순수 core 직접 호출에는 파일 수집 보장이 없다.
compact MCP는 artifact 목록을 생략하고 원래 개수·digest·생략 여부를 유지한다.
## S2-b: 원본 Git 객체와 명시 정책 pin

CLI `check/report --head <ref>`는 `--base`, `--trusted-policy-ref`,
`--trusted-policy-sha256`으로 선언한 Git 객체만 수집한다. `--policy`는 저장소 상대 경로다.
base/head/trusted ref를 commit OID로 고정하며 merge-base가 여러 개면 명시 base를 요구한다.
working tree·미추적 파일·미저장 버퍼·replace refs는 입력에 포함하지 않는다.

원본 blob과 방문한 tree의 bytes를 Git object ID와 독립 SHA-256으로 결합한다.
원문은 비공개 메모리 evidence에 보관하고 공개 manifest에는 해시·OID·상태만 넣는다.
빈 blob과 고정 tree에서 확인한 absent를 구분한다. symlink·submodule을 따라가지 않으며,
텍스트 분석 불가 또는 1 MB object/20,000 tree entry 제한은 성공으로 숨기지 않는다.
표시·분석용 문자열 capsule의 v1 manifest와 원본 Git evidence의 schema는 별개이고,
두 digest를 결합하며 원본에서 해석한 문자열·평가 정책이 같은 bytes인지 확인한다.

정책은 caller가 지정한 ref와 기대 raw SHA-256을 일치시켜 선택한다. 후보 정책의
삭제·약화는 기존 보수적 guard로 거부한다. **실제 판정에는 pin한 정책을 사용한다.**
후보의 새 규칙을 자동 승인하거나 활성화하지 않는다. 정책 migration은 새 anchor를
명시적으로 선택해야 한다. 이 pin은 조직 승인·서명·trusted checker 인증을 대체하지 않는다.
`organization_approval_verified=false`, `checker_authority=current-engine-not-attested`를 유지한다.

CLI 기본 local 모드와 PR API 모드는 유지한다. immutable 모드를 요청하고 pin이 빠지거나
틀리면 input error·종료 2이며 정상 pass 결과가 없다. 원격 GitHub API 자동 수집의 새
trust 모드나 화면 설정은 이번 단계에 추가하지 않는다. 원본은 메모리에만 남으며
장기 디스크 bundle과 최신 결과 게시는 다음 단계다.

immutable diff는 원본 object directory를 읽는 임시 bare 저장소에서 만든다.
working tree·index fallback·`info/attributes`·global/system 속성·local diff 설정과
호출자의 `GIT_*` 환경변수를 배제하고, 원본 index·config·objects를 수정하지 않는다.
커밋된 `.gitattributes`도 이 raw 비교에는 적용하지 않는다. 공개 provenance에는
`diff_mode=isolated-raw-git`를 기록한다. 같은 고정 객체의 검사에서는 이러한 주변
상태가 바뀌어도 input capture·원본 evidence·verification이 같아야 한다.

CLI의 immutable 저장소 탐색에도 같은 환경 격리를 적용한다. 저장소 하위 폴더에서
실행해도 호출자의 `GIT_DIR`·`GIT_WORK_TREE`가 다른 저장소로 입력을 돌리지 않는다.
정책·문서의 LF/CRLF는 raw bytes대로 보존하며, 플랫폼 기본 문자 인코딩이나 줄바꿈으로
기대 해시를 바꾸지 않는다. 이 격리는 caller가 선택한 ref/hash의 무결성 계약이며,
조직 승인이나 현재 엔진의 외부 인증을 추가로 주장하지 않는다.

로컬 bounded read의 변경 감지는 열린 handle의 `fstat`끼리 비교한다. Windows에서
path `stat`과 handle `fstat`의 ctime 의미가 다를 수 있어 두 API를 직접 비교하지 않는다.
원문은 한 번 읽고, 첫 handle을 닫은 뒤 경로를 다시 열어 identity·size·mtime·ctime을
확인한다. 관찰된 교체·크기·시간 변경과 symlink는 계속 거부한다. 같은 크기·mtime의
다른 파일로 교체한 사례도 거부해야 한다. 전체 저장소 atomicity나 ABA 검출은 보장하지 않는다.
