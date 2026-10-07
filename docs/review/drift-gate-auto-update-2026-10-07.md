# auto 개선안 운영 코드 반영 및 검증

2026-10-07, `ver2` HEAD `d262ec2` 위 미커밋 작업 트리. 기준 설계는 [auto-panel 검토](drift-gate-auto-panel-2026-10-07.md)이다. 이전 검증 자료와 v1 suite는 그대로 보존했다. 이 문서는 이번 턴의 구현과 실행 범위를 기록한다.

## 구현 결과

| 설계 항목 | 반영 내용 |
|---|---|
| 교차 조건 범위 | 관계마다 자체 파일을 선택해 내용 검사. 상위 적용 조건을 유지하고 relation/source_files를 별도로 기록. 직접 트리거 통제와 같은 fail/verified로 변경 |
| 평가 축 분리 | 실제 임시 Git 전후 파일과 전체 문서로 facts/decision/verification/gate를 각각 비교하는 별도 v2 실행기와 고정 입력 추가 |
| 강도 후보 누락 | router prefix, 체인 등록, 동적 환경 접근은 불확실한 후보로 유지. 확정된 환경 키가 있으면 별도 unknown 때문에 알려진 위반을 숨기지 않음 |
| YAML 및 getter 별칭 | adapters의 안전 YAML 정규화, 공통 bounded JSON 파서, os/getenv/environ 별칭 및 재할당·scope·동적 키의 uncertainty |
| 명시적 auto | 새 `content: auto-strict`. 전체 Python 계약 종류를 선택하며 경로 조건으로 대체하지 않음. 기존 auto의 호환 경로는 유지 |
| JS/TS 체인 | 문법 트리에서 Express import·const 선언·method/route 체인·literal mount를 확인. core에 정규화한 사실만 전달 |
| 독립 엔진 대조 | 기존 FastAPI32 통제에 비GET·전후 변경·삭제·여러 필드·변경 없음32 통제 추가. 실제 Express4.21.2의 HTTP4 통제 추가 |
| 외부 평가 | 인간 맹검·실제 PR 표본의 평가자 분리는 수행하지 않음. 새22개도 작성자 통제이며 제3자 정확도 평가가 아님 |

실행 흐름은 `adapter 입력 수집 → bounded 문법/문서 사실 → 규칙별·관계별 source scope → known/no-delta/unknown → 그룹 논리 결합 → 의무 판정 → verification 집계 → gate 조치`다. 전체 소스를 확보했다는 사실만으로 지원 밖 문법을 verified로 만들지 않는다. 스냅샷·YAML 정규화·Express 추출 사실은 해시로 실행 입력에 묶으며 보고서에 전체 소스를 추가하지 않는다.

핵심 파일은 [evaluator](../../drift_gate/core/evaluation/evaluator.py), [contracts](../../drift_gate/core/evaluation/contracts.py), [routes](../../drift_gate/core/evaluation/routes.py), [environment](../../drift_gate/core/evaluation/environment.py), [OpenAPI 파서](../../drift_gate/core/evaluation/openapi_document.py), [YAML adapter](../../drift_gate/adapters/docs/structured.py), [Express adapter](../../drift_gate/adapters/ast/express_routes.py)다. 입력 수집과 문법 파서는 adapters, 판단과 논리 집계는 core에 둔다.

## 실제 실행 결과

| 검증 | 결과 | 근거 |
|---|---|---|
| Python 전체 | 1,228 통과, skip0 | [원시 로그](../assessment/auto-update-2026-10-07/python-complete.log) |
| React | 125 통과 | [원시 로그](../assessment/auto-update-2026-10-07/react.log) |
| TypeScript / ruff E9,F | 모두 통과 | [tsc](../assessment/auto-update-2026-10-07/tsc.log), [ruff](../assessment/auto-update-2026-10-07/ruff-final.log) |
| 기존 고정 기능 fixture | 21/21 | [원시 출력](../assessment/auto-update-2026-10-07/fixed-evaluation.json) |
| 원본 generalization v1 | 지원24/24, 경계 gate5/8 | [원시 출력](../assessment/auto-update-2026-10-07/generalization-v1-verified.json) |
| 새 Python/Git v2 | 14/14, 네 축 각각 일치 | [원시 출력](../assessment/auto-update-2026-10-07/evaluation-v2-verified.json) |
| 새 Express/Git v1 | 8/8, 네 축 각각 일치 | [원시 출력](../assessment/auto-update-2026-10-07/express-v1-verified.json) |
| 교차 조건 원래 재현 | 관계 fail/verified, 직접 통제 fail/verified | [원시 입력·출력](../assessment/auto-update-2026-10-07/relation-after.json) |

새22개 고정 입력에서 거짓 verified와 알려진 위반 누락은 각각0이다. 추출·의무·검증·조치 일치 수를 각각 측정한 값이며, 실제 프로젝트의 미탐률0이나 정확도100%를 뜻하지 않는다. 새 suite는 기대값을 첫 실행 전에 작성했지만 개발 중 사용한 유형과 helper를 공유하므로 독립 맹검 자료가 아니다.

마지막 scope 검토에서 예외의 `except ... as getter`와 match capture의 별칭 가리기를 보완했고, TypeScript type-only import를 실제 Express 바인딩으로 인정하지 않는 통제도 추가했다. 앞선 통과 로그를 보존하며 최종 파일 해시는 verification-final.json에 별도로 기록한다. 자체 검사 마지막 snapshot은 self-check-complete-inputs.json이며 이전 snapshot과 구분한다. 결과는 pass/unverified로 내용 완전성 증명과 구분한다.

Express HTTP 검사는 작성한 fixture만 임시 로컬 포트에서 실행했다. 정상 `/v1/catalog`는200, 잘못된 `/catalog`·`/v2/catalog`는404인지 GET/POST/PUT/DELETE로 확인했다. FastAPI64는 OpenAPI 생성 대조이며 HTTP 실행64건이 아니다. 운영 검사에서는 대상 저장소의 코드를 실행하지 않는다.

전체 회귀 첫 실행에서 실제 import가 빠진 예전 환경 fixture와 확장된 Git 읽기를 반영하지 않은 mock을 발견했다. 운영 검사를 느슨하게 만들지 않고 fixture의 `import os`와 Git root/size/show 응답을 보완했다. 중간 실패 로그 `python-full.log`, `python-final.log`도 폴더에 남겼으며 최종 성공 파일은 `python-verified.log`다. 초기 고정 v1 입력은 수정하지 않았다.

## 1/8 수치의 해석

원래 경계8은 auto6와 env-keys2를 합친 것이다. 수정 후 게이트 기대 일치는5/8, verified이면서 기대 게이트까지 맞는 것은2/8이다.

| 원래 사례 | 현재 판정 | 의미 |
|---|---|---|
| B01 잘린 여러 줄 route | pass/unverified | legacy auto 호환 경로가 남음. 전체 소스 + auto-strict에서는 별도 통제로 확인 |
| B02 Markdown 표 | pass/verified | 기존 정상 통제 유지 |
| B03 잘린 YAML patch | fail/unverified, undetermined | 문서가 없다고 verified 위반을 단정하던 오류 제거. 전체 YAML 없이 원본 pass 기대값은 입증 못함 |
| B04 prefix / B05 동적 키 / B08 체인 | fail/unverified, undetermined | 조용한 unmatched 대신 불확실성을 노출·정책에 따라 차단. 계약 불일치 입증으로 계산하지 않음 |
| B06 getter 별칭 | fail/verified | 정적 새 키와 문서 부재를 입증 |
| B07 정의 없는 모델 교체 | pass/unverified | legacy auto 호환 경로. 전체 소스 + auto-strict에서 필드 변경/이름만 변경을 구분 |

기존 gate5/8과 새 의미 평가22/22를 합쳐 하나의 정확도로 발표하지 않는다. 정책·입력 완전성·지원 범위가 다르다. 무조건 fail 기준6/8보다 낮다는 사실도 숨기지 않는다. fail 수를 늘리는 대신 근거에 맞는 unknown과 verified를 구분하는 개선이다.

## 사용과 지원 경계

```yaml
rules:
  - id: api-contract
    severity: blocker
    when:
      any_changed: ['src/**']
      min_change_intensity: route-contract-change
    require:
      groups:
        - name: API 문서
          all_changed: ['openapi.yaml']
          content: auto-strict
gate:
  on_unverified: fail
```

명시적인 응답 schema 비교는 `api-schema`, 환경 키만 비교할 때는 `env-keys`를 선택할 수 있다. `auto-strict`의 문서 경로는 explicit 상대 경로다. 기존 auto는 자동 전환하지 않는다. 정책 guard는 내용 모드 변경을 검토해야 할 계약 변경으로 처리한다.

Express는 기본 ESM import, 같은 모듈의 직접 const app/router, literal 경로와 mount만 지원한다. CommonJS, named import, 동적 등록, path pattern/parameter, 외부 router, 재할당·alias·scope 가리기·export/opaque escape, middleware·응답 모델 해석은 아직 지원하지 않는다. Python의 외부 모델·동적 routing·복잡한 schema도 unknown이다. OpenAPI PathItem/operation 참조는 해석하지 않는다. JSON/YAML 전체 입력과 bounded object 검사는 완전한 OpenAPI 표준 검증기와 다르다.

추가 개발은 지원 범위가 분명한 실제 PR·별도 평가자 검토를 먼저 확보하고 CommonJS·외부 모듈 그래프·request/response 표현을 각각 새 계약으로 확장해야 한다. 지원되지 않는 사례를 임의 추측으로 verified 처리하는 방향은 채택하지 않았다.

## 재현·증거와 완료 범위

새 입력은 [Python/Git suite](../../drift_gate/tests/contracts/auto-contracts-v2.json)와 [Express/Git suite](../../drift_gate/tests/contracts/express-contracts-v1.json)에 고정했다. [실행기](../../scripts/audit_auto_contracts.py)는 기존 출력 파일을 거부한다.

```text
python scripts/audit_auto_contracts.py --out <새 출력.json>
python scripts/audit_auto_contracts.py --suite drift_gate/tests/contracts/express-contracts-v1.json --out <별도 새 출력.json>
```

[근거 폴더](../assessment/auto-update-2026-10-07/)에 새 평가·전체 테스트·교차 조건 재현·자체 검사 결과와 파일 해시 영수증을 저장한다. 자체 검사도 legacy auto의 파일 의무 확인이며 제품 논리의 완전성 증명으로 해석하지 않는다.

이번 턴은 로컬 Mac 소스·Qt/React 회귀·합성 Git·고정 프레임워크 대조까지 수행했다. CI 실행 목록은 업데이트했지만 원격 CI·새 설치본·Windows/Linux 실행·공개 릴리스 검증을 이번 턴에 완료한 것으로 표현하지 않는다. 커밋·푸시는 하지 않았다. 사용자가 삭제한 인수인계 문서2개도 복원하지 않았다.
