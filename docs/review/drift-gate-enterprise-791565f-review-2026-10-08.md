# 791565f 구현 보고 검증과 반례 리뷰

2026-10-08 KST. 대상은 고정 커밋 `791565fd88e109645379b2a2efcd6601840e4191`이다.
기존 Mac 작업 폴더의 미커밋 수정과 삭제 파일은 보존했고, 별도 작업 트리에서 읽기·시험만 했다.
PR #1 검증 댓글은 삭제하거나 수정하지 않았다. 운영 코드 수정·커밋·푸시는 하지 않았다.

## 판단

**원격 성공·설치본 실행 보고는 근거와 일치한다. 하지만 5~23번의 보장까지 모두 완성됐다는 평가는 받아들일 수 없다.**
새 기능의 연결과 반례를 검사해 7개 문제 묶음을 재현했다. 테스트 수가 많아도 호환성의 건전성,
검증 대상의 동일성, 권한 범위, 평가 입력의 출처 연결을 보장하지는 못했다.

심각도와 수정 순서는 검토자의 판단이다. 아래 사례는 작성자가 고른 회귀 반례이며 독립 holdout 정확도가 아니다.
전체 신규 코드의 무결함을 증명하거나 실서비스 사고 발생률을 추정하는 평가도 아니다.

## 확인한 실행 근거

| 주장/검사 | 직접 확인한 결과 | 범위 |
|---|---|---|
| 원격 ver2 | `791565fd88e109645379b2a2efcd6601840e4191` | fetch 및 원격 조회 |
| push CI | [37744699574](https://github.com/cres17/pr-convention-checker/actions/runs/37744699574) success | head SHA 확인 |
| PR CI | [37744705509](https://github.com/cres17/pr-convention-checker/actions/runs/37744705509) success | head SHA 확인 |
| Desktop | [37744699455](https://github.com/cres17/pr-convention-checker/actions/runs/37744699455) 세 플랫폼 success | Windows, macOS arm64, Intel |
| 설치본 CLI | 실제 산출물 JSON 6/6의 4단계 모두 `ok` | dist 3개 + Windows 설치본 + DMG 2개 |
| 재실행 | 6/6 `repository_deleted_before_replay=true`, `replay_matches=true` | 의도한 위반의 gate/replay `fail`, 종료 1이 정상 기대값 |
| byte 범위·실행 기록 | 각 3개 범위 검증, `publication-skipped`까지 기록 | 해당 합성 패키지 시험 |
| Intel 종료 | 5/5 exit 0, 이벤트 루프 반환·atexit 기록 | 이전 실패 원인 규명이나 해결 증거는 아님 |
| 로컬 Python | **1,920 passed, 6 skipped**, 90.12초 | Mac Python 3.11.15, 고정 작업 트리를 설치한 별도 환경 |
| Ruff | `E9,F`, drift_gate/packaging/scripts 모두 통과 | 캐시 없이 실행 |

컨테이너의 1,869/12 수치를 이 Mac에서 같은 의존성으로 재현한 것은 아니다. 환경별 수치를 섞지 않았다.
처음에는 부모 테스트만 새 작업 트리를 읽고 `python -I` 자식은 이전 editable 설치를 읽어 4건이 실패했다.
새 전용 환경에 고정 작업 트리를 설치하고 자식 import 경로까지 확인한 후 전체 재실행해 위 결과를 얻었다.
초기 4건은 제품 회귀로 계산하지 않았다.

산출물은 [근거 폴더](../assessment/enterprise-791565f-review-2026-10-08/)에 보존했다.
설치 실행 파일 자체를 이 Mac에서 재설치·실행한 것은 아니다. GitHub에서 내려받은 실제 CI JSON을 검증했다.

## R1 — 높음: 호환성이 깨져도 verified/pass가 나온다

위치: `core/evaluation/compatibility.py:86-99,133-157,313-325,390-406,408-436`.

1. 기존 응답 schema가 `oneOf: [number, integer]`, 새 schema가 `integer`인 경우다.
   값 `1`은 기존 schema의 두 분기에 동시에 들어가 기존 계약에서는 유효하지 않지만 새 계약에서는 유효하다.
   응답 집합이 기존 허용 집합 밖으로 넓어졌는데 결과는 `truth=T`, 실제 검사 게이트도 `pass`다.
2. `allOf`의 두 object 분기가 각각 `a`와 `b`만 허용하고 `additionalProperties:false`를 가지는 경우다.
   이를 두 필드를 모두 허용하는 단일 object로 바꾸면 `{"a":"x"}`가 새로 허용된다.
   코드가 분기별 제약을 단순 합쳐 같은 의미로 보고 `T/pass`를 낸다.
3. 기존 `default` 응답이 string이고 새 `200` 응답이 integer여도 `T`다.
   추가 status가 default에 대응하는 경우 body 비교가 빠져 있다.
4. Path Item에 required query parameter를 추가해도 `T`다. operation의 parameters만 읽는다.

1·2는 독립 라이브러리 **jsonschema 4.26.0 / Draft202012Validator**로 같은 증인 값을 대조했다.
두 경우 모두 `old_accepts=false`, `new_accepts=true`였다. 실제 정책·inspection 경로에서도 `pass`를 확인했다.
3·4는 비교 함수에서 직접 재현했다. 전체 CLI까지 재실행했다고 주장하지 않는다.

수정 방향: `oneOf`의 배타성과 `allOf`의 분기별 허용 범위를 보존한다. 정확한 포함 관계를 결정할 수 없는
조합은 U로 둔다. default/status 및 Path Item/operation 상속을 해소한 유효 계약을 비교한다.
위 네 반례와 비호환/호환 대조군을 회귀 테스트에 넣어야 한다.

## R2 — 높음: 신뢰 엔진과 후보가 서로 다른 커밋을 검사해도 allow

위치: `adapters/trusted_validation.py:31-60`.

실제 고정 엔진 `ed9f904`를 실행하고, 그 호출이 반환된 직후 shadow 입력 수집 직전에 임시 저장소의
`candidate` 브랜치를 A에서 B로 이동시켰다. 타이밍을 고정하는 wrapper만 사용했고 엔진 결과·해시·attestation은
모조 값으로 바꾸지 않았다.

- 신뢰 엔진이 검사한 head: `ab4b45a87f84696801e8a1a4295ec1b163002ed9`.
- 최종 결과의 subject head: `0b110ac071455cfabb160256453e1bc56ce33ee7`.
- 신뢰/후보 입력 SHA-256이 다르지만 `action=allow`, `merge_basis=trusted-engine`.
- 로드한 엔진 코드와 파서의 pin 검사는 모두 true였다.

새 commit을 검사한 신뢰 결과가 없는데 이전 commit의 결과를 승인 근거로 연결한다.
이번 두 commit은 모두 pass인 대조다. 악성 commit을 실제 GitHub에서 병합하거나 CI를 우회시킨 실험은 아니다.
현재 워크플로처럼 고정 SHA를 주는 경로와, CLI가 허용하는 이동 가능한 ref 경로를 구분해야 한다.

수정 방향: 입구에서 base/head/policy ref를 한 번만 OID로 확정하고 양쪽에 같은 불변 입력을 전달한다.
결과를 결합하기 전에 subject·정책·평가 context의 동일성을 필수 검증하고 불일치는 merge 근거 없음으로 처리한다.
엔진 버전 때문에 입력 digest 형식이 달라질 수 있다면 버전별 공통 원본 subject 검증 규칙이 필요하다.

## R3 — 높음(조직 기능 사용 시): 저장소 범위 밖 결과의 백업·삭제·권한 확대

위치: `core/org/policy.py:53-64`, `adapters/org_service.py:106-114,184-215`.

`org/A`만 허용된 admin을 만들고 `org/B`의 결과를 저장했다. 이 admin의 B 직접 읽기는 정상 거부됐다.
그러나 같은 admin으로 다음이 성공했다.

- backup ZIP 안에 B의 결과 본문이 포함됨.
- 보존 기간을 지난 B 결과가 purge로 삭제됨.
- `scopes=['*']`인 새 admin 생성.

`repository=None`인 작업은 scope 검사를 건너뛰는 것이 원인이다. tenant 간 접근이나 로그인 우회를
재현한 것은 아니다. 인증 없는 로컬 저장소라는 명시적 한계를 고려해도 저장소 scope 계약 내부의 모순이다.

수정 방향: tenant 전체 관리 권한은 명시적인 `*` scope 또는 별도 tenant-admin 역할을 요구한다.
범위 제한 purge/backup을 허용하려면 대상 전체를 scope로 필터링해야 한다. 위임 권한은 위임자의 범위를
넓힐 수 없어야 한다. 직접 읽기뿐 아니라 관리 작업의 권한 행렬을 시험해야 한다.

## R4 — 중간: holdout 실행 경로가 실제 제품과 다르다

위치: `adapters/holdout.py:138-153`, `adapters/inspection.py:65`.

Express router의 `/catalog`를 `/products`로 바꾸고 `/v1`에 mount하며 문서에 `GET /v1/products`를 적었다.
같은 policy와 before/after 원문으로 제품 inspection은 `pass`, holdout은 `undetermined/unverified`, gate `fail`이었다.

제품의 `attach_express_routes`가 평가 경로에는 없다. 따라서 이 도구의 오탐률·미탐률을 곧바로 제품 전체의
성능으로 읽으면 안 된다. 단순 누락을 보충하는 것보다 불변 입력을 받는 공식 inspection 경로를 공통으로
사용해 이후 다른 전처리 추가도 함께 반영되도록 해야 한다. 평가 context도 양쪽에 동일하게 고정해야 한다.

## R5 — 중간: labels pin은 생겼지만 평가 대상과 labels의 연결은 없다

위치: `adapters/holdout.py:163-178,181-237`, `adapters/cli/runner.py:1300-1314`.

내용과 SHA-256이 다른 frozen A/B를 만들고 같은 case/rule ID를 사용했다. B의 packet을 두 검토자가 판정한
labels와 A의 실행 결과를 조합해 **정확한 results/labels 파일 SHA pin을 모두 전달**했다.
`holdout score`는 종료 0으로 metrics를 썼다.

파일이 바뀌지 않았다는 검사는 동작한다. 그러나 그 labels가 바로 그 frozen 입력을 검토했다는 연결은 없다.
labels에는 frozen digest나 packet digest가 없고 score는 ID 문자열만 맞춘다.

수정 방향: frozen → packet → labels → metrics에 상위 산출물 digest를 연결하고 score에서 동일한 원본을
확인한다. blind packet에는 기대값·엔진 결과를 숨기되 원본 digest 및 판단에 필요한 context는 남긴다.
두 frozen 입력의 ID 충돌, 다른 protocol, 만료일·면제 context 변경을 명시적으로 거부/구분하는 시험이 필요하다.

## R6 — 중간: 동적 literal import를 누락하고 그래프가 닫혔다고 보고

위치: `core/contracts/dependency.py:22-24,145-168`.

`app.js`에서 `import("./dep.js")`를 호출하고 `dep.js`를 변경했다. 영향 범위는 dep.js뿐이고 app.js가 빠졌다.
동시에 `closed=true`, `open_boundaries=[]`였다. 일반적인 정적 import로 바꾼 대조군에서는 app.js가 포함됐다.

정적 import/require 패턴에는 이 호출이 없고, dynamic 감지 패턴은 literal 호출을 제외한다.
지원 밖이면 열린 경계여야 한다는 계약도 충족하지 못한다.
literal dynamic import를 해석하거나 열린 경계로 남기고, 일반 import·require·computed import를 함께 시험한다.

## R7 — 중간: 캐시 결과 value를 바꿔도 정상 hit

위치: `adapters/analysis_cache.py:65-95`.

env 분석 캐시에 `['SECRET_KEY']`를 저장한 뒤 key_inputs는 그대로 두고 value만 `[]`로 바꿨다.
정규 JSON bytes로 기록하면 읽기 결과가 `hit=1`, `rejected_entries=0`이고 변경한 값이 반환된다.

키는 입력을 해시하지만 결과 본문의 무결성을 검증하지 않는다. 보고서의 '변조 시 miss'는 이 사례에서 틀리다.
로컬 쓰기 권한자가 실행 코드도 바꿀 수 있다는 한계와 구분해야 한다. 원격 공격이나 권한 상승을 입증한 것은 아니다.

수정 방향: 단순 손상 검출에는 결과 digest를 포함한 envelope 검증이 필요하다. 공격자가 파일 전체를 다시 쓸 수
있다는 위협 모델에서는 같은 파일 안의 digest만으로는 충분하지 않다. 인증된 저장소/서명 또는 재계산이 필요하며,
그 경계까지 보장하지 않을 경우 캐시를 merge 근거로 신뢰하지 않는 계약을 명시해야 한다.

## 완료 범위의 재분류

- **5·7:** 엔진 분리와 replay 경로는 구현됐다. R2와 별개로 후보 코드가 이미 설치된 runner라는 보고서의
  한계도 유효하다. 별도 신뢰 runner를 갖춘 운영 보안 경계가 완성된 것은 아니다.
- **12·13:** 도구 추가와 독립 평가 완료는 다르다. 데이터·독립 사람 정답은 없으며, R4/R5 때문에 평가 도구도 보완이 필요하다.
- **14:** 설치본의 증거 저장·일반 replay·spans·journal 주장은 확인했다. 다만 6개 JSON 모두
  `producer.source_files=0`, 빈 map의 source digest, `loaded_code_attested=false`, `parser_binary_attested=false`다.
  따라서 이 시험은 동일 고정 엔진으로 인증 replay한 증거로 승격할 수 없다. 해당 인증 replay의 설치본 경로는 직접 시험하지 않았다.
- **15:** Intel 5회 정상 종료를 확인했다. 과거 실패 원인은 여전히 미규명이다.
- **16·21·22·23:** 코드가 존재하지만 R6/R1/R3/R7로 선언한 보장에 반례가 있다.
- **8·18 추가 검토 후보(이번 반례 실행 제외):** scope는 Python/JS/TS만 열거하므로 mixed-language 서비스 전체의
  인증과 구분해야 한다. `_batch_read`는 subprocess stdout 전체를 받은 뒤 bytes 예산을 소비하므로,
  수집 전 메모리 상한을 보장하지 않는다. 별도 부하·범위 시험이 필요하다.

기존 Mac의 NaN 시간 입력 수정은 원격에 합쳐지지 않았다. `791565f`의 recover는 여전히
`isinstance`와 `<=0`만 검사하는 것을 코드에서 확인했다. 이번 새 문제와 별도로 기존 수정·41개 테스트를
보존했으며 통합하지 않았다. [이전 감사](drift-gate-claude-continuation-audit-2026-10-08.md)는 당시 상태 기록이다.

## 권고 순서와 종료 기준

1. R1·R2: 잘못된 verified/pass와 잘못 연결된 승인 근거부터 막는다. 지원 불확실성은 U/review로 보존한다.
2. R3: 조직 기능 사용 전에 범위 제한 역할과 tenant 관리 권한을 분리한다.
3. R4·R5: 평가 경로의 제품 동등성과 산출물 계보를 고친 뒤 holdout 평가를 시작한다.
4. R6·R7: 누락된 의존 경계와 캐시 무결성 계약을 보완한다.
5. 기존 NaN 수정 통합, 설치본 엔진 identity 보완, 신뢰 runner 분리 및 자원 예산 부하 시험을 별도로 검증한다.

각 수정은 해당 반례와 정상 대조군 → 전체 회귀 → 고정 commit CI → 영향을 받는 설치본 경로 순으로 확인한다.
위 문제 해결 전에는 '코드 존재·실행 경로 구축 완료' 수준으로 표현하고, '엔터프라이즈 보장 완료' 또는
'독립 평가 완료'로 표현하지 않는 것이 근거에 맞다.

## 재현

근거 폴더의 `reproduce.py`는 `791565f`를 설치한 Python 3.11 환경과 `jsonschema==4.26.0`을 사용한다.
`reproduce_refs.py`는 `DRIFT_GATE_REVIEW_ROOT`로 고정 소스 checkout을 지정한다. 해당 저장소에는 `ed9f904`
객체도 있어야 한다. 모든 시험용 변경은 임시 폴더에서 수행한다. 파서가 준비된 동일 환경에서 실행했다.
검토 스크립트는 결과를 기록하는 진단 자료이며 아직 제품 회귀 테스트에 통합하지 않았다.

```sh
python reproduce.py > results-new.json
DRIFT_GATE_REVIEW_ROOT=/absolute/path/to/791565f-checkout python reproduce_refs.py > refs-results-new.json
```

새 결과는 이전 증거를 덮어쓰지 않는다. 원본 테스트 로그, 실제 CI JSON, 재현 JSON과 파일별 SHA-256 목록을 함께 보존한다.
