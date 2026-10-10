# 기존 경계 평가 개선안과 독립 관점 논리 검토

작성일: 2026-10-07. `ver2`, Git HEAD `d262ec2` 기반 미커밋 작업 트리를 대상으로 한다. 이 턴에서는 운영 코드를 변경하지 않았다.

## 1. 결론과 수치 정정

앞서 말한 “auto 경계 평가 1/8”은 정확한 명칭이 아니다. 기존 경계 suite는 **auto API 정책 6개와 env-keys 정책 2개**를 섞은 것이다. 현재 코드로 다시 실행한 결과는 전체 1/8, auto 부분 1/6, env-keys 부분 0/2다. 이는 작성자가 만든 작은 합성 suite의 게이트 기대값 일치 수이며 실제 PR 정확도가 아니다.

개선의 핵심은 세 가지다.

1. 분석할 수 없는 변경을 강도 필터에서 없애거나 경로 변경만으로 통과시키지 않는다.
2. 계약 종류와 문서 형식에 맞는 분석기를 선택하고, 완전한 소스·문서를 확보한다.
3. `fail`이라는 최종 조치와 실제 계약 불일치의 입증을 별도로 평가한다.

새 독립 검토에서는 **교차 조건에 전달하는 소스 범위가 잘못되는 결함을 직접 재현했다.** 지원 확대보다 먼저 고칠 가치가 있다. 이번 요청은 개선 방안과 평가이므로 재현 자료와 설계를 남겼으며 운영 패치는 하지 않았다.

## 2. 다자 평가의 방법과 한계

서로 다른 과제를 받은 세 하위 에이전트가 독립적으로 읽기·실험을 시작했다.

| 검토 관점 | 전달받은 초기 결과 | 주 검토자의 재확인 |
|---|---|---|
| 경계 사례·정책 의미 | 1/8의 혼합 모드 구성, 각 실패 경로, 정책만 바꾼 점수 변화 | 현재 suite 재실행 및 별도 counterfactual 스크립트로 확인 |
| 반례 중심 코드 논리 | cross_file이 관계 대상 대신 상위 규칙의 소스를 내용 검사에 전달 | 독립 재현 스크립트와 직접 트리거 통제로 확인 |
| 평가 방법·증거 감사 | 소스152·근거27 해시 일치, oracle32의 실제 범위, blind 평가 아님 | 파일 해시 직접 대조, oracle 테스트 코드와 평가 집계 코드 읽기 |

세 하위 에이전트 모두 초기 결과 전달 뒤 도구 측 사용량 제한으로 종료되어 최종 리뷰는 완성하지 못했다. 위 표는 실제 받은 중간 결과만 정리한 것이다. 주 검토자가 핵심 결과를 재현했지만, 이를 세 명의 사람이나 서로 다른 회사·모델이 최종 합의한 평가로 표현하지 않는다. 같은 모델 계열의 AI끼리도 오류가 상관될 수 있다.

객관성의 근거는 “세 에이전트의 동의”가 아니라 고정 입력·원시 출력·반례 통제·소스 위치·재실행 가능성이다. 본 문서의 우선순위는 검토 의견이며 제품 정확도 점수는 부여하지 않았다.

## 3. 현재 8개 사례의 원인과 개선

| 사례 | 현재 결과 | 실제 막히는 단계 | 필요한 개선과 올바른 해석 |
|---|---|---|---|
| B01 여러 줄 route | pass / unverified | 한 줄 matcher가 경로 delta를 못 찾고 auto 경로 조건으로 대체 | 완전한 전후 소스의 AST로 route를 추출. 소스가 없고 조각이 불완전하면 undetermined. 줄을 이어 붙인 추측을 verified로 표시하지 않음 |
| B02 Markdown 표 | pass / verified | 정상 동작 | 기존 통제로 보존. 다른 메서드·잘못된 경로·이동/중복 표를 추가 통제로 검사 |
| B03 OpenAPI YAML | fail / verified | 구조화된 YAML을 Markdown route 정규식에 넣고 “없음”으로 단정 | 형식 판별 후 안전한 YAML 파서로 전체 문서의 paths/method를 읽음. 미지원/손상/입력부족은 unknown. 정상 구조화 문서를 확정 위반으로 취급하지 않음 |
| B04 router prefix | pass / not-applicable | prefix 변경이 강도 필터에서 탈락 | 등록된 router 관계와 최종 경로를 먼저 분석해 강도 근거에 반영. prefix 두 줄만으로 router가 앱에 연결됐는지 알 수 없으므로 입력부족은 unknown |
| B05 동적 환경 키 | pass / not-applicable | 정적 키가 없다는 것을 관련 변경이 없다는 뜻으로 취급 | 환경 접근 사실과 키 값 확정 여부를 분리. 동적 키는 undetermined; 정책으로 차단 가능하지만 “새 키 누락을 입증했다”로 계산하지 않음 |
| B06 getenv 별칭 | pass / not-applicable | 별칭 호출을 환경 접근으로 인식하지 못함 | 제한된 import 바인딩과 재할당·scope 추적. `from os import getenv as read_env`의 정적 호출 지원. 가려짐·동적 참조는 unknown |
| B07 응답 모델 교체 | pass / unverified | URL delta가 없어서 경로 조건만 확인 | 모델 전후 구조를 읽어 비교. 이름만 바뀌고 구조가 같으면 문서 의무가 없을 수 있음. 현재 fixture에는 모델 정의가 없으므로 불일치 입증 불가 |
| B08 Express chained route | pass / not-applicable | chained registration이 강도 필터에서 탈락 | 별도 JS/TS AST 분석기로 route().get() 체인과 router 등록 범위를 확인. 같은 이름의 임의 객체 호출은 Express라고 단정하지 않음 |

코드 근거:

- [auto 경로 대체·문서 matcher](../../drift_gate/core/evaluation/contracts.py): content_requirement와 route_delta.
- [강도 후보 판정](../../drift_gate/core/evaluation/evaluator.py): _threshold_candidates.
- [환경 키 분석 범위](../../drift_gate/core/python_syntax.py): environment_keys.
- [한 줄 route 분석 범위](../../drift_gate/core/route_syntax.py): literal_route.

최근 추가한 api-schema의 router 조합은 **완전한 소스·명시적 정책**에서 동작한다. 기존 suite는 잘린 patch·auto 정책을 사용한다. 그래서 새 기능이 있다는 사실만으로 이 suite의 점수가 오르지 않는다. 기존 입력을 몰래 바꾸어 8/8을 만들면 개선 근거가 사라진다.

## 4. 새로 재현한 결함: 교차 조건의 내용 검사 범위

심각도 의견: 높음. 실제 지원 기능의 잘못된 통과다.

입력:

- 상위 규칙의 when: `src/config.py`.
- 교차 조건의 when_any_changed: `src/api.py`.
- 해당 교차 조건이 선택 그룹 `API`를 요구하며 content는 api-schema.
- config의 단순 값 변경과 API의 응답 label 필드 삭제를 함께 제출.
- OpenAPI에는 삭제된 label이 그대로 남음.

관측:

- 교차 조건 구성: **pass / not-applicable / 위반 0**.
- 같은 API를 상위 when의 직접 대상으로 지정한 통제: **fail / verified**.

원인: `_evaluate_cross_file_relations()`가 관계에 맞는 파일의 존재만 확인하고 `_evaluate_groups()`에는 상위 규칙의 trigger_files를 넘긴다. 따라서 config 소스에서 API delta가 없다는 이유로 관계 요구를 충족시킨다. 관련 위치는 [evaluator.py](../../drift_gate/core/evaluation/evaluator.py)의 `_evaluate_cross_file_relations` 마지막 그룹 평가 호출이다.

수정 설계:

1. 관계마다 `relation_files`를 실제 선택한다. rename의 이전 경로와 ignore 조건은 공통 경로 판정 계약을 따른다.
2. 관계의 content 검사에 그 범위를 전달한다. 전역 changed_files는 문서 찾기에만 사용한다.
3. 상위 규칙의 성립 여부와 관계 조건의 성립 여부, 내용 검사 대상 범위를 별도로 보존한다.
4. 부모 불확실성 전파·상위 강도 조건과의 논리 결합은 먼저 계약으로 명시한다. 단순 인자 교체만 하고 종료하지 않는다.
5. API뿐 아니라 env-keys 관계에서도 서로 다른 source가 정확히 연결되는지 검사한다.

회귀 행렬: 부모·관계 경로 같음/다름, 관계만/부모만/둘다 변경, rename, ignored, 해당 소스 unavailable, 다중 관계, optional group, 올바른/오래된/없음 문서, min-intensity 설정과 파일 순서 교환을 포함한다.

[원시 결과와 입력](../assessment/auto-panel-2026-10-07/relation-result.json), [재현 스크립트](../assessment/auto-panel-2026-10-07/reproduce_relation.py).

## 5. 왜 8/8만 목표로 삼으면 안 되는가

기존 경계 기대값은 fail 6개·pass 2개다. **아무 입력이나 fail로 내보내도 6/8**이 된다.

실제로 제품 코드를 바꾸지 않고 실험용 정책의 최소 강도를 any로 낮추고 auto를 api-routes로 바꾸자 **게이트 일치가 7/8**이 됐다. 그러나 **verified이면서 기대값까지 맞는 것은 여전히 1개**였다. 나머지 개선 대부분은 확인 불가를 기본 정책에 따라 차단한 효과다.

이 실험은 방어적인 차단 정책의 효용을 부정하지 않는다. 분석의 이해도와 조치의 보수성을 같은 지표로 섞으면 안 된다는 증거다. 원래 정책과 suite는 수정하지 않았다.

[정책 변경 실험](../assessment/auto-panel-2026-10-07/counterfactual-result.json), [독립 재현 스크립트](../assessment/auto-panel-2026-10-07/counterfactual.py).

새 평가에는 다음 축이 필요하다.

| 축 | 확인 내용 |
|---|---|
| 추출 정확성 | 메서드·경로·키·필드의 실제 전후 사실이 맞는가 |
| 의무 판정 | 전제와 요구가 성립했는가; violated/satisfied/undetermined/not-applicable가 맞는가 |
| 검증 범위 | verified/partial/unverified가 증거의 범위와 맞는가 |
| 최종 조치 | 설정에 따른 pass/warn/fail이 맞는가 |
| 거짓 확신 | 모르는 입력을 verified로 출력한 건수 |
| 적용 범위 누락 | 의미 있는 입력을 unmatched로 버린 건수 |
| 의미 검증 커버리지 | 완전한 입력 중 실제로 내용을 확인한 비율 |
| 운영 비용 | 오탐·보류 비율, 실행 시간, 입력 수집·보고서 크기 |

전체 suite를 무조건 verified로 만드는 목표도 부적절하다. 동적 입력의 정당한 undetermined를 정답으로 인정해야 한다. 기존 v1은 역사적 비교용으로 유지하고, 기대 decision/verification/게이트 정책을 분리한 v2를 별도 만든다.

## 6. auto의 다음 구조

현재 auto의 문서 경로 이름과 route 정규식에 의존하는 선택을 계약 유형·입력 완전성 기반 선택으로 발전시키는 것을 권한다.

```text
규칙/교차 조건별 source 범위 확정
→ 관련 변경 후보 식별(확정·가능성·무관)
→ 완전한 전후 소스와 문서 확보
→ 계약 유형에 맞는 분석기 선택
→ 구조화된 변경 사실 + 확인 한계
→ 문서 형식에 맞는 비교
→ 규칙 판정·검증 범위
→ 설정에 따른 게이트 조치
```

분석기 결과는 `known delta`, `proved no delta`, `unknown`을 구분한다. 빈 set 하나로 세 상태를 표현하지 않는다. 알려진 위반과 국소적인 unknown은 partial로 집계하고, routing scope 자체가 모호하면 함부로 파일을 합치지 않는다.

호환성은 명시적으로 관리한다. 기존 auto를 즉시 다른 뜻으로 바꾸면 문서 변경만 요구하던 정책에서 새로운 차단이 생길 수 있다. 권고안은 기존 동작을 legacy 정책 버전으로 보존하고 새 정책 버전 또는 명시적 strict auto 설정을 도입하는 것이다. `paths`는 파일 조건 전용으로 유지한다. 이름과 마이그레이션 형식은 아직 구현되지 않은 제안이다.

안전한 YAML 도입은 adapters에서 수행하고 core에는 정규화된 객체를 넘긴다. 중복 키, alias/깊이/크기 제한, `$ref` 범위, source line과 provenance를 정의한다. Markdown과 구조화 문서를 같은 문자열 검색기로 처리하지 않는다. glob 문서 후보 수집에도 제한과 생략 사실을 남겨야 한다.

## 7. 검증 논리성 평가

### 근거가 충분한 부분

- 기존 판정과 검증 상태를 분리했다. unknown 차단과 실제 위반을 구분할 데이터가 있다.
- 과거 fixture·결과를 보존하고 현재 소스/근거의 해시를 남겼다. 이번에 source152개·evidence27개가 모두 일치함을 재확인했다.
- 진리표·순서 변형·해시 seed 검사는 결정론과 집계 규칙의 유효한 회귀 근거다.
- 실제 FastAPI가 OpenAPI 기대값을 생성하는 oracle은 제품의 정적 분석과 구현이 다르므로 유용한 독립 엔진 대조다.
- 캐시 전후 입력 고정과 보고서 전체 동일성 검사는 성능 변경이 의미를 바꾸지 않는지 확인하는 적절한 방법이다.

### 아직 부족한 부분

- cross_file 범위 연결 결함은 단위 검사 성공이 전체 정책 조합의 논리를 보증하지 않는다는 직접 반례다.
- 기존 평가기는 gate 문자열만 비교한다. B03은 미지원 문서를 verified 위반으로 오인하고, B05의 의도적 보수 차단은 확정 위반 탐지와 섞인다.
- 32 oracle은 8개 primitive/default 형태 × 4개 router 배치다. 모두 GET·added·단일 id 필드다. 32개 독립 실제 서비스나 전후 변경 32종이 아니다.
- oracle의 프레임워크 구현은 독립적이지만 fixture 선택·정책·helper는 개발 과정과 공유한다. blind/제3자 평가가 아니다.
- 실제 HTTP 요청, 실행 환경의 패키지 해석, 배포 prefix, middleware·권한·응답 검증은 oracle 범위 밖이다.
- 512상태·12,288순열은 유한 집계기 성질을 검사한다. 모든 분석기·입력 수집·정책 조합에 대한 형식 증명은 아니다.
- 성능의 반복 3/5회는 해당 고정 입력의 관측값이다. 일반 서비스의 60% 개선이나 p95를 주장할 근거가 아니다.

따라서 현재 평가는 **제한된 정적 계약 검사에 대한 회귀 근거는 강해졌지만, 일반적인 코드 검증의 논리적 완전성은 아직 입증되지 않았고 실제 연결 결함도 남아 있다**이다. 근거 없이 90점 같은 점수를 부여하지 않는다.

## 8. 권고 실행 순서와 완료 조건

1. **cross_file 내용 범위 수정**: 직접/관계 정책의 동등 입력 결과 일치, 반대 통제와 unknown 전파 포함.
2. **평가 v2 추가**: 기존 v1 보존, 완전한 Git 전후 저장소 입력과 의미 기대값 분리. 새 입력의 기대값은 제품 실행 전에 고정.
3. **강도 필터와 unknown 전파**: B04·B05·B06·B08을 무관 변경으로 탈락시키지 않음. comment/string·재할당·동일 구조·미등록 router 정상 통제를 함께 추가.
4. **OpenAPI YAML과 환경 getter 별칭**: 근거를 확정할 수 있는 범위부터 구현. 정상 YAML 오탐(B03)과 단순 정적 별칭(B06)을 먼저 해결.
5. **auto의 명시적 선택 규칙과 소스 확보**: 새 Python contract 기능을 opt-in auto에 연결하고 B01·B04·B07의 full-source 쌍 검사. patch-only는 unknown을 정확히 보고.
6. **JS/TS chained route와 oracle 확장**: 수집·등록 범위의 지원을 먼저 정의. 실제 프레임워크의 POST/PUT/DELETE, modified/deleted, 여러 필드·여러 모델·중복 경로·변경 없는 대조를 추가.
7. **개발에 사용하지 않은 평가 묶음**: 작성자와 판정 검토자를 분리하고 실제 PR 표본은 출처·선택 기준·수동 adjudication을 기록. 지원 범위 안/밖의 지표를 따로 보고.

완료 기준은 단순 8/8보다 **새로 정의한 지원 범위에서 거짓 verified 0, 알려진 위반 유실 0, unknown의 정당한 보존, 정상 통제 오탐 방지, 진입점·정책 조합 일치**다. 이는 유한 시험 묶음의 수용 기준이며 운영 전체에서 결함 0을 증명한다는 뜻은 아니다.

## 9. 재현과 변경 상태

[새 평가 자료](../assessment/auto-panel-2026-10-07/)에 원본 suite 재실행, counterfactual, cross_file 재현을 보존했다. 이번 턴은 운영 코드 수정·커밋·푸시를 하지 않았다. 이전 전체 테스트 1,101개를 이번 턴에 다시 실행했다고 주장하지 않는다. 그 검증 자료의 해시 일치와 이번 개별 실험을 확인했다.
