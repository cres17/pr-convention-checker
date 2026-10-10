# 791565f 검토 반례 수정 (R1~R7)과 후속 보완

2026-10-08 KST · 기준 `791565f` · 수정 커밋 `f5b5ee6`(시간 입력), `8004ca7`(R1~R7·후속), 이 보고서 커밋

[791565f 검토](drift-gate-enterprise-791565f-review-2026-10-08.md)가 재현한 7개 문제를 고쳤고, 같은 검토의
"추가 검토 후보"와 "권고 순서 5"의 일부를 함께 처리했다. 각 반례는 검토자가 만든 회귀 사례이며 독립 정확도 평가가 아니다.
아래 결과는 이 수정이 해당 반례를 막는다는 근거이지, 각 기능에 다른 결함이 없다는 증명이 아니다.

## 반례별 수정과 재확인

검토자의 `reproduce.py`를 고치지 않고 복사해, 이제 거부되는 호출만 예외를 기록하도록 감싼 `recheck.py`로 다시
실행했다([결과](../assessment/enterprise-791565f-fixes-2026-10-08/recheck-results.json)). `reproduce_refs.py`는 그대로
실행했다([결과](../assessment/enterprise-791565f-fixes-2026-10-08/refs-recheck-results.json)).

| # | 반례 | 791565f | 수정 후 | 수정 |
|---|---|---|---|---|
| R1-1 | `oneOf:[number, integer]` → `integer` | T, gate pass | U, gate fail | `oneOf`는 분기가 서로소임을 증명할 때만 합집합으로 취급 |
| R1-2 | `allOf` 두 분기가 서로의 key 금지 → 두 key 허용 object | T, gate pass | F, gate fail | key별로 모든 분기의 schema 교집합, 금지 key 유지 |
| R1-3 | 기존 `default` string → 새 `200` integer | T | F(`type`) | 같은 code → `NXX` → `default` 순으로 대응 응답 비교 |
| R1-4 | Path Item에 required query parameter 추가 | T | F(`required-parameter-added`) | Path Item parameter를 operation에 상속, `$ref` parameter는 U |
| R2 | 신뢰 엔진 실행 직후 branch 이동 | 이전 commit 결과로 allow | 두 엔진 모두 시작 시 확정한 commit 검사 | ref를 처음에 OID로 확정, 결합 전 subject·정책·입력 digest 대조, 불일치는 `merge_basis=none` |
| R3 | `org/A` 범위 admin의 backup·purge·`*` admin 생성 | 모두 성공 | backup·위임 거부, purge는 범위 밖 결과 미삭제 | tenant 전체 작업은 `*` 범위 필요, purge·list 범위 필터, 위임은 위임자 이내 |
| R4 | Express mount 사례 | 제품 pass, holdout fail | 둘 다 pass, 입력 digest 동일 | holdout `run`이 제품 `inspect` 경로 사용 |
| R5 | 다른 frozen 입력의 labels로 score | 종료 0, metrics 작성 | 종료 2, 미작성 | packet·labels에 상위 digest 기록, score가 frozen digest·protocol·항목 대조 |
| R6 | `import("./dep.js")` | app.js 누락, closed=true | app.js 포함 | literal `import()`를 edge로 해석, 범위 밖 열린 경계도 closed=false |
| R7 | 캐시 value만 변경 | hit, 변경 값 반환 | 거부, 재계산 | entry v2에 `result_sha256`, 위조 방어가 아님을 계약에 명시 |

R1~R7과 후속 보완마다 회귀 테스트를 추가했다. 새 테스트 파일을 `791565f` 작업 트리에 복사해 실행하면 새 시험과
변경한 기존 시험 23건이 실패했다(R1 8, R2 2, R3 2, R4·R5 3, R6 4, R7 1, 후속 3). 같은 실행의 다른 2건은 작업 트리와
editable 설치 경로가 달라 worker가 실패한 환경 문제로, 수정과 무관하다. R1은 검토와 같은 `jsonschema` 4.26.0
`Draft202012Validator`를 독립 판정기로 사용해, 무작위 `oneOf/anyOf/allOf` 조합에서 T 판정에 반례가 없고 F 판정에
반례가 있는지 확인한다.

R6 수정 중 `_JS_DYNAMIC` 정규식이 공백 뒤 backtracking으로 줄바꿈된 literal `import(\n'./dep'\n)`을 동적 import로
오판하는 별도 결함을 발견해 함께 고쳤다.

R2의 shadow 경로는 신뢰 엔진(`ed9f904`)의 보고서에 있는 head·base·정책 revision·정책 SHA-256·비교 방식을 사용한다.
입력 digest protocol이 다르면 digest는 비교하지 않고 그 사실을 기록한다.

## 후속 보완

- **시간 입력:** Mac 작업 트리에 커밋되지 않고 남아 있던 NaN·Infinity lease 수정과 테스트를 변경 없이 통합했다
  ([당시 감사](drift-gate-claude-continuation-audit-2026-10-08.md)).
- **설치본 producer identity:** 설치 앱은 Python 소스가 없어 producer digest가 빈 파일 집합이다. replay는 이를
  `producer_sources_observed=false`로 기록하고 인증 replay는 `bundle-producer-sources-unobserved`로 거부한다.
  설치본 CLI 검증 결과에도 `certified_engine_replay=false`를 남긴다.
- **수집 memory 상한:** `scope`는 객체 크기를 먼저 조회해 bytes 예산을 청구한 뒤 내용을 읽는다.
- **혼합 언어 서비스:** 서비스 경로에 Python·JS·TS 이외 소스가 있으면 `unsupported_language`로 인증하지 않는다.

## 검증

| 검사 | 결과 | 근거 |
|---|---|---|
| 전체 pytest (Linux 컨테이너, Python 3.11.17) | 1,934 통과, 12 건너뜀 | [full-suite.log](../assessment/enterprise-791565f-fixes-2026-10-08/full-suite.log) |
| ruff `E9,F` | 통과 | [ruff.log](../assessment/enterprise-791565f-fixes-2026-10-08/ruff.log) |
| 자체 정책 검사 (`791565f`..`8004ca7`) | pass | 로컬 실행 |
| 신뢰 엔진 대조 (`ed9f904`) | 신뢰 pass, 후보 pass, subject 불일치 없음, review(검사기 변경) | [trusted-check.json](../assessment/enterprise-791565f-fixes-2026-10-08/trusted-check.json) |

건너뛴 12개의 사유는 이전과 같다(PySide6 4, Express 대조 설치 4, zstandard 3, Windows 전용 1).

`25d7518` push 후 원격 결과:

| 실행 | 결과 |
|---|---|
| [CI push 37754952867](https://github.com/cres17/pr-convention-checker/actions/runs/37754952867) | 성공. Ubuntu·macOS·Windows × 3.10~3.12, self-check(신뢰 엔진 대조 포함), lint, benchmark |
| [CI PR 37754957955](https://github.com/cres17/pr-convention-checker/actions/runs/37754957955) | 성공. `main`→`ver2` 전체 범위 immutable 검사·묶음 재실행 포함 |
| [Desktop 37754952843](https://github.com/cres17/pr-convention-checker/actions/runs/37754952843) | macOS arm64·Intel 성공. Windows는 desktop 회귀 단계가 `1123 passed, 5 skipped` 출력 후 종료 코드 127로 실패해 이후 설치본 단계가 실행되지 않음 |

Windows 종료 코드 127의 원인은 확인하지 못했다. 이 단계에서 바뀐 시험 파일은 없고, 직전 세 commit에서는 같은 단계가
통과했다. 다음 실행부터 `python -X faulthandler`와 JUnit 결과를 남기도록 workflow를 바꿨다(이후 commit). 원인을 모르는
상태에서 재실행 통과를 해결로 기록하지 않는다.

## 남은 한계

- 신뢰 엔진 대조는 여전히 후보 코드가 설치된 runner에서 실행된다. 별도 신뢰 runner 분리는 하지 않았다.
- holdout 사례와 독립 사람 label은 없다. 평가 도구는 제품 경로와 계보를 맞췄을 뿐 성능 수치를 만들지 않았다.
- 캐시 무결성 검사는 같은 파일 안의 digest라 entry 전체를 다시 쓰는 주체를 막지 못한다.
- JS 의존 탐지는 정규식 기반이어서 주석·문자열 안의 호출을 구분하지 않는다.
- Intel 종료 실패의 원인은 여전히 관찰되지 않았다.
- 검토의 판단대로, 이 수정 후에도 "엔터프라이즈 보장 완료"나 "독립 평가 완료"로 표현할 근거는 없다.
