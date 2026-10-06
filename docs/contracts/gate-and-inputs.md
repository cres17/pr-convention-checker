# Gate와 입력 계약

## 검사 의미

Gate는 정책이 요구한 변경과 근거의 충족을 판정한다. 코드 품질·실제 PR 정확도·전체 문서 의미를 보증하지 않는다. `rule_decisions`의 `unmatched`는 통과한 규칙이 아니라 트리거가 맞지 않은 규칙이다. 분석 방식과 미지원 사유는 `scan_metrics.analysis_notes`에 남는다.

기본 경로 요구는 문서의 변경 여부를 확인한다. 명시적 `env-keys`, `api-routes`와 제한적인 `auto` 내용 검사는 지원 문법에 한해 추가 확인한다.

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

정책 의무 비교는 기존 all_changed 그룹에 any_changed를 추가해 우선순위를 바꾸는 완화도 거부한다. evaluator에서 any_changed가 우선하므로 배열 포함 여부만 비교하지 않는다.
