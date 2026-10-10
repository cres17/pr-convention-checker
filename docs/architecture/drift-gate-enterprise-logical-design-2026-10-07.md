# Drift Gate 논리 구조·검증 체계·운영 아키텍처 심화 설계

작성일: 2026-10-07 · 대상: `ver2`의 `d262ec2faff3b98c917e3e99f7b6260cf0514ff3` 위 **미커밋 작업 트리**

**문서 상태: 설계 및 반례 검증. 구현 완료·보안 인증·일반적 정확성 증명 문서가 아니다.**

이 문서는 [기존 아키텍처 v2](target-architecture-v2-2026-10-06.md), [제품 논리 발전안](../review/drift-gate-logical-development-2026-10-07.md), [최근 구현 보고](../review/drift-gate-auto-update-2026-10-07.md)를 이어 간다. 이전 자료를 덮어쓰지 않는다. 이번 작업은 운영 코드를 수정하지 않고 설계, 통제 사례, 재현 자료를 추가했다.

## 초록

Drift Gate의 다음 과제는 지원 언어나 탐지 규칙을 많이 추가하는 것보다, **어떤 입력과 가정으로 어느 범위의 의무를 입증했는지 추적 가능하게 만드는 것**이다. 현재 구현은 문서 변경 여부, 계약 내용, 불확실성, 게이트 조치를 분리하는 기반을 갖췄다. 그러나 이번 재검증에서 자동 분류의 검사 누락, TypeScript 타입 전용 import의 잘못된 런타임 해석, JSON 수치 범위 검증 누락을 재현했다. 기존 합성 테스트 통과만으로 논리 완결성을 주장할 수 없다는 직접적인 근거다.

목표 설계는 입력 스냅샷, 범위 완전성, 사실의 하한·상한, 정책 의무, 증거 회로, 실행 신뢰성, 운영 조치를 각각 독립된 모델로 만든다. `pass`는 정책상 진행 허용이고, `verified`는 명시한 명제에 충분한 근거가 있다는 뜻으로 제한한다. 코드 전체의 정확성, 서비스 정상 동작, 보안 안전성으로 확대하지 않는다. 구현은 작은 순수 판정 코어와 외부 입력·파서·저장 어댑터를 유지하며, 기업 운영에 필요한 신뢰 경계와 재현 가능성을 순차적으로 추가한다.

## 읽는 순서

- 제품 판단과 즉시 수정할 항목: 1–3절, 20절.
- 판정 논리와 데이터 모델: 4–10절.
- 실제 아키텍처와 운영 흐름: 11–16절.
- 객관적 평가와 출시 기준: 17–19절.
- 구현 작업 단위·의사결정·근거: 20–23절.

## 1. 목적, 비목표, 보장 수준

### 1.1 제품이 답해야 할 질문

> 고정된 코드 변경과 신뢰한 정책을 기준으로, 영향을 받는 계약이 요구하는 문서·설정·검증 근거가 충족되었는가? 답할 수 없다면 어느 입력·지원 범위·신뢰 조건이 부족한가?

명제의 주어는 ‘프로젝트 전체’가 아니라 `정책 × 계약 프로필 × 분석 범위 × 입력 버전`이다. 대상 코드가 실행되지 않는 정적 검사의 장점을 유지한다. 외부 프레임워크 실행은 검증용으로 작성한 통제 프로그램에 한정한다.

### 1.2 목표를 분리한다

| 목표 | 구체적 완료 의미 | 이를 증명하지 않는 것 |
|---|---|---|
| 논리적 건전성 | 선언한 가정 아래 충분한 근거가 없는 명제를 확정하지 않음 | 모든 언어·모든 프로그램 분석 가능 |
| 설명 가능성 | 판정 → 의무 → 사실 → 원문 위치 → 입력 해시를 추적 | 설명 문장이 자연스러우면 판정도 정확함 |
| 반복 가능성 | 동일한 의미 입력과 엔진 버전으로 같은 의미 결과 | 실행 시간·UUID까지 동일 |
| 운영 안전성 | 실패·취소·타임아웃·중복·역순 완료를 구분 | 네트워크·디스크 장애가 발생하지 않음 |
| 공급망 신뢰 | 결과와 검증기·정책·코드·실행 주체의 관계 확인 | 해시 또는 서명만으로 코드 품질 입증 |
| 평가 타당성 | 독립 정답·보류율·오판률·분모·지원 범위 공개 | 작성자 사례의 100%를 실제 PR 정확도로 일반화 |

### 1.3 도입 수준

| 수준 | 사용 형태 | 선행 조건 |
|---|---|---|
| L0 개발자 보조 | 로컬 설명·반례 탐색 | 입력 실패와 판단 불가가 표시됨 |
| L1 팀 권고 검사 | CI에서 결과를 알리되 병합은 사람이 결정 | 입력 버전·정책 버전·근거 보존, 담당자 지정 |
| L2 병합 차단 | 지정 계약 위반에 자동 차단 | 20절 P0 해소, 신뢰 검증기, 고정 입력, 정책 승인, 보류 처리, 복구 절차 |
| L3 조직 공용 서비스 | 여러 팀·저장소를 격리해 운영 | L2 + 접근 통제·자원 할당·감사·보존 정책·운영 지표 |

이는 이 문서가 제안하는 내부 도입 단계이며 외부 인증 등급이 아니다. 현재 상태를 L2/L3 완료로 판단하지 않는다. 멀티테넌트 서비스가 필요하지 않다면 L3 구현은 보류한다.

## 2. 근거의 수준과 현재 기준선

### 2.1 서술 규칙

| 표기 | 의미 |
|---|---|
| 재현 | 이번 턴에 실행하고 입력·관측값을 새 파일로 보관 |
| 기록 재확인 | 이전 원시 결과와 해시를 대조, 이번 턴에 해당 전체 검사를 재실행하지 않음 |
| 코드 확인 | 특정 구현에서 확인, 실제 장애 빈도·운영 영향은 미측정 |
| 설계 | 구현해야 할 규약·불변식·목표 |
| 가설 | 아직 반례 또는 정상 통제로 검증하지 않은 위험 |

이 문서의 수식과 불변식은 **목표 명세**다. 정리의 전제를 실제 추출기가 만족하는지 입증하기 전에는 제품의 보장으로 바꾸지 않는다.

### 2.2 기준선 재확인

이번 [원시 결과](../assessment/enterprise-logical-design-2026-10-07/results-final.json)는 이전 `verification-final.json`의 운영 소스 115개, 입력 5개, 테스트 44개, 근거 파일 38개의 SHA-256을 다시 계산했다. **202개 모두 일치**했다. 이는 해당 목록의 일치를 뜻하며, 전체 작업 트리나 모든 UI 파일이 목록에 포함됐다는 뜻은 아니다. HEAD만으로 미커밋 변경을 식별할 수 없다.

| 항목 | 이전 실행 기록 | 이번 해석 |
|---|---|---|
| Python | 1,228 통과, skip 0 | [최종 로그](../assessment/auto-update-2026-10-07/python-complete.log)와 영수증 재확인, 전체 재실행 아님 |
| React | 125 통과 | [기존 로그](../assessment/auto-update-2026-10-07/react.log) 재확인 |
| 원래 합성 평가 | 지원 24/24, 경계 gate 일치 5/8 | 원래 1/8 기준을 보존한 비교. 경계 중 verified이면서 gate까지 맞는 것은 2/8 |
| 새 의미 평가 | Python/Git 14, Express/Git 8, 네 축 각각 22/22 | 작성자 통제 사례. facts·decision·verification·gate를 구분 |
| 프레임워크 대조 | FastAPI OpenAPI 생성 64, Express HTTP 통제 4 | FastAPI 64회를 HTTP 실행으로 표현하지 않음 |
| 자체 Drift Gate | pass / unverified | 문서 변경 의무를 확인한 결과. 이 설계의 논리적 타당성 증명이 아님 |
| 이번 추가 검증 | 혼합 계약 3통제, import 3통제, 숫자 3통제 | 작고 목적이 정해진 반례 검사, 정확도 표본으로 계산하지 않음 |

이전 보고 본문의 ‘최종 성공 파일’ 문장에는 앞선 로그명이 남아 있다. 이 문서는 [최종 영수증](../assessment/auto-update-2026-10-07/verification-final.json)이 가리키는 `python-complete.log`를 기준으로 한다. 사람의 설명과 원시 증거 인덱스의 불일치도 자동 검증 대상이어야 한다.

## 3. 이번에 새로 확인한 논리 결함

재현 코드: [reproduce.py](../assessment/enterprise-logical-design-2026-10-07/reproduce.py). 최종 입력·결과·TypeScript 변환 결과: [results-final.json](../assessment/enterprise-logical-design-2026-10-07/results-final.json). 최초 결과 `results.json`도 보존한다. 최종 재현기의 해시는 최종 결과에 있다.

### E01 — 혼합 계약에서 변경 없는 환경 키가 API 의무를 가림

**재현, 우선순위 P0.** 전체 전후 소스를 실제 임시 Git 저장소에서 수집했다. 아래 코드의 `/old`만 `/new`로 바꾸고 OpenAPI에는 `/old`를 남겼다.

```python
from fastapi import FastAPI
import os
setting = os.getenv("EXISTING_KEY")
app = FastAPI()

@app.get("/old")
def endpoint():
    return {}
```

| 통제 | 관측 결과 |
|---|---|
| 환경 읽기 있음 + `auto-strict` | satisfied / not-applicable / pass |
| 같은 코드 + `api-routes` | violated / verified / fail |
| 환경 읽기 제거 + `auto-strict` | violated / verified / fail |

API 사실 추출은 세 경우 모두 `GET /new` 추가, `GET /old` 제거를 얻는다. 실패 지점은 [strict_auto_requirement](../../drift_gate/core/evaluation/routes.py)의 선택 로직이다. 환경 키 또는 응답 모델이 있으면 종류 집합에 넣지만, 응답 모델 없는 경로 계약은 같은 집합에 넣지 않는다. 환경 키가 바뀌지 않았다는 사실에서 전체 계약이 적용되지 않는다고 잘못 결론 내린다.

**요구사항:** 자동 모드는 ‘한 검사 선택’이 아니라 ‘적용 가능한 계약 의무 집합 구성’이어야 한다. 단기에는 혼합 종류를 보수적으로 undetermined로 처리하고 명시 그룹을 안내한다. 장기에는 각 종류를 독립 평가한 뒤 AND로 결합한다. 환경 키 불변이 API 경로 의무를 지울 수 없어야 한다.

### E02 — 타입 전용 import에 주석을 넣으면 존재하지 않는 런타임 근거를 인정

**재현, 우선순위 P0.** [Express 어댑터](../../drift_gate/adapters/ast/express_routes.py)는 타입 전용 import를 문자열 접두어 `import type `로 거부한다.

```typescript
import /* retained comment */ type express from 'express';
const app = express();
app.get('/catalog', (req, res) => res.end());
```

| 통제 | 추출 및 실제 Git 검사 | TypeScript 5.9.3 변환 |
|---|---|---|
| `import type express` | unknown → fail / unverified | import 제거 |
| 주석 삽입 후 같은 type import | 경로 인정 → pass / verified | import 제거 |
| 일반 값 import | 경로 인정 → pass / verified | import 유지 |

문법은 파싱 가능하지만 타입 전용 이름을 런타임 함수처럼 쓰므로 올바른 실행 바인딩의 근거가 아니다. `transpileModule`의 diagnostics가 비어 있어도 전체 타입 검사 성공을 뜻하지 않는다. 이 시험은 **타입 제거 동작**을 대조했으며 HTTP 서버를 실행하지 않았다. TypeScript 공식 설명도 타입 전용 import가 출력에서 제거됨을 명시한다. [TypeScript 3.8 문서](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-3-8.html)

**요구사항:** AST의 토큰·필드로 import 의미를 판별한다. 공백·탭·줄바꿈·주석 변형을 동일 의미로 처리한다. 검증기는 프로젝트 전체 타입 오류를 잡을 필요는 없지만, 자신이 사용하는 런타임 바인딩의 성립 조건은 확인해야 한다.

### E03 — JSON 숫자의 지수 오버플로가 유한성 제한을 벗어남

**재현, 우선순위 P1.** [load_openapi](../../drift_gate/core/evaluation/openapi_document.py)에서 다음을 비교했다.

| 값 | 관측 |
|---|---|
| `1` | 수락, 유한 값 |
| `NaN` | 거부 |
| `1e999` | 수락, Python 내부에서는 무한대 |

`parse_constant`는 `NaN` 같은 특수 토큰을 처리하지만 유효한 JSON 숫자 표기인 큰 지수가 binary64 범위를 넘는 것까지 막지 않는다. 검사는 `x-number` 확장 필드로 재현했다. **이 사례가 실제 스키마 위반을 pass로 만들었다는 주장은 하지 않는다.** 수치 표현·정규화 계약의 일관성이 깨진다는 근거다.

**요구사항:** raw JSON 문법 적합성과 제품 수치 도메인을 분리한다. 제품이 유한 binary64를 채택하면 모든 float의 유한성을 재검사하고 거부 사유를 `unsupported_numeric_range`로 남긴다. 정밀 십진수를 지원하려면 파싱·정규화·해시·모든 진입점을 함께 변경한다.

## 4. 연구 질문과 증명 의무

| ID | 질문 | 필요한 근거 | 반증 조건 |
|---|---|---|---|
| RQ1 | verified 명제는 명시한 분석 범위에서 참인가? | 지원 문법 명세, 추출 정리, 독립 엔진 대조 | 지원한다고 선언한 사례에서 거짓 verified 1건 |
| RQ2 | 판단 불가와 실제 위반을 구분하는가? | 세 값 논리 시험, 누락 입력 통제 | 입력 부재를 위반 확정 또는 정상으로 숨김 |
| RQ3 | 자동 선택·관계·강도 필터가 의무를 누락하지 않는가? | 조합·순서·혼합 범위 시험 | E01 같은 무관한 사실 추가로 의무 소실 |
| RQ4 | 보고서가 실제 검증한 코드·정책·검증기에 묶여 있는가? | 스냅샷·버전·해시·신뢰 실행 검증 | 다른 commit 또는 검증기 결과를 재사용 |
| RQ5 | 장애·경합·자원 부족에서 정직하게 종료하는가? | 상태 기계·장애 주입·부하 실험 | 늦은 결과가 최신 판정을 덮어씀, 실패가 pass가 됨 |
| RQ6 | 실제 팀에서 유용한가? | 외부 PR 표본, 사람 정답, 보류·오탐·수정 시간 | 차단만 늘고 근거 확정·수정 행동이 개선되지 않음 |

RQ1–RQ5는 기술적 검증 의무다. RQ6는 실제 사용자 자료가 필요하며 현재 회귀 테스트로 답할 수 없다. 언어·프레임워크·구문을 확장할 때마다 RQ1의 증명 범위를 다시 열어야 한다.

## 5. 형식 모델: 입력, 가능한 해석, 사실의 범위

### 5.1 검사 입력

의미 입력을 다음 튜플로 정의한다.

```text
I = (RepositoryIdentity, B, H, Manifest, Scope,
     TrustedPolicy, ContractProfiles, EngineIdentity,
     EvaluationContext, VerifiedAuthorizations)
```

- `B`, `H`: 실제 비교한 불변 소스 버전. PR에서는 기준 ref, head ref, merge-base와 실제 비교 기준을 모두 기록한다.
- `Manifest`: 코드·문서·설정·의존 메타데이터의 경로, 타입, 크기, 원문 해시, 수집 상태.
- `Scope`: 정책 selector와 영향 범위. 파일 목록만이 아니라 진입점·계약 종류·제외 사유를 포함한다.
- `ContractProfiles`: 지원 문법, 프레임워크 의미, 비교 의미, 자원 상한을 묶은 버전.
- `EvaluationContext`: 평가 기준 시각·시간대·기능 플래그·규약 버전. core가 현재 시각을 직접 읽지 않는다.
- `VerifiedAuthorizations`: commit·의무·만료 시각에 묶인 외부 검증 완료 승인. PR 본문 문자열과 분리한다.

전체 소스가 존재하는 것과 분석 범위가 완전한 것은 다르다. 변경 파일 하나의 원문을 읽었어도 외부 router, 모델, 진입점, 미변경 import의 영향을 모르면 범위는 열려 있다.

### 5.2 가능한 해석 집합

`Ω(I, p)`를 입력과 계약 프로필 `p`의 가정에 부합하는 가능한 해석들의 집합으로 둔다. 목표는 실제 해석이 이 집합에 포함되도록 보수적으로 구성하는 것이다.

```text
KnownTrue(q)  : 모든 w ∈ Ω에서 q(w)가 참
KnownFalse(q) : 모든 w ∈ Ω에서 q(w)가 거짓
Unknown(q)    : 위 둘 중 어느 것도 입증되지 않음
```

중요한 전제는 `Ω ≠ ∅`이다. 문법 오류·불가능한 바인딩·상충된 입력으로 집합이 비었다고 참과 거짓을 동시에 ‘증명’하지 않는다. 이러한 입력은 `invalid_input` 또는 `unsupported_semantics`로 별도 처리한다. E02는 검증기가 사용할 바인딩에 대한 전제를 확인하지 않은 사례다.

이 관점은 추상 해석의 보수적 근사에서 설계 방향을 가져온다. 현재 코드 전체가 추상 해석 정리를 만족한다고 주장하는 것은 아니다. [Cousot & Cousot, 1977](https://www.di.ens.fr/~cousot/COUSOTpapers/POPL77.shtml)

### 5.3 사실의 하한·상한

각 범위의 사실 집합 `F`를 `(L, U)`로 근사한다. `L`은 반드시 존재하는 사실, `U`는 존재할 수 있는 사실이다.

```text
모든 w ∈ Ω에 대해 L ⊆ F(w) ⊆ U
정확한 사실: L = U
완전히 모름: L = ∅, U = TOP
```

`TOP`은 무한 목록을 메모리에 펼치라는 뜻이 아니다. 표현상 ‘현재 도메인에서 상한을 열어 둠’이라는 표시다. 원인·영향 범위·이미 확정된 사실은 따로 보존한다.

변경 전후 근사에서 다음 안전한 근사를 얻는다.

```text
추가 사실 하한 L+ = L_after \ U_before
추가 사실 상한 U+ = U_after \ L_before
제거 사실 하한 L- = L_before \ U_after
제거 사실 상한 U- = U_before \ L_after
```

이 식은 전후의 상관관계를 잃을 수 있어 보수적이며 항상 가장 정밀한 것은 아니다. `U+ = U- = ∅`이면 변경 없음이 입증된다. 반대 방향은 필수가 아니다. 동일 표현이라는 별도 관계 증거로도 변경 없음이 입증될 수 있다.

예를 들어 이전 코드가 `getenv(name)`이면 이전 사실의 상한이 열려 있다. 이후 `getenv('PORT')`를 찾았다는 이유만으로 프로젝트에 PORT가 새로 도입됐다고 단정할 수 없다. 반면 ‘이 위치에서 PORT 리터럴 읽기가 추가됨’이라는 다른 명제는 입증 가능하다. **전역 새 키, 새 사용 위치, 문서에 필요한 전체 키를 정책에서 구별해야 한다.**

### 5.4 `no-delta`의 엄격한 조건

변경 없음의 근거에는 최소한 다음이 필요하다.

1. 비교 대상 계약 종류가 빠짐없이 선택되었다.
2. 해당 계약의 영향 범위와 입력 버전이 고정되었다.
3. 누락·초과·미지원·분석 실패가 변화의 부재로 바뀌지 않았다.
4. 전후 사실 비교 또는 동등성 증거가 변경 없음을 입증한다.

`찾은 사실 0개`, `문서에 키워드 없음`, `AST 파싱 성공`은 각각 위 네 조건의 대체물이 아니다. 특히 `env delta = ∅`에서 `API delta = ∅`를 유도할 수 없다.

## 6. 의무 논리와 증거 대수

### 6.1 결과 축을 분리한다

| 축 | 제안 값 | 의미 |
|---|---|---|
| 입력 상태 | valid / invalid / unavailable | 입력 계약 성립 여부 |
| 적용 상태 | applicable / not-applicable / undetermined | 검사 의무가 생기는가 |
| 명제 결과 | true / false / unknown | 정의한 명제가 충족되는가 |
| 증거 범위 | complete / partial / unavailable | 범위의 어느 부분을 알 수 있는가 |
| 허가 | enforced / waived / waiver-invalid | 승인된 예외 여부 |
| 운영 조치 | allow / warn / block / error | 조직이 취할 행동 |
| 실행 상태 | completed / cancelled / timed-out / failed | 검사가 끝났는가 |

현재 `decision`, `verification`, `result`를 바로 삭제하지 않는다. 내부 모델을 먼저 도입하고 기존 필드는 호환 projection으로 만든다. `not-applicable`은 진리값이 아니고, `waived`는 사실이 참으로 바뀐 것이 아니다.

### 6.2 논리 결합

기본 결합은 Strong Kleene의 세 값 논리를 사용한다. `T=true`, `F=false`, `U=unknown`이다.

| AND | T | F | U |
|---|---|---|---|
| T | T | F | U |
| F | F | F | F |
| U | U | F | U |

| OR | T | F | U |
|---|---|---|---|
| T | T | T | T |
| F | T | F | U |
| U | T | U | U |

논리 부정은 `¬T=F`, `¬F=T`, `¬U=U`로 둔다. 빈 AND는 T, 빈 OR는 F라는 수학적 항등값과 **잘못된 빈 정책 입력을 허용하는지**는 별개의 문제다. 정책에 필수 그룹이 비어 있으면 입력 검증에서 거부하고 항등값으로 정상 처리하지 않는다.

현재 [content_result.combine](../../drift_gate/core/evaluation/content_result.py)의 기본 결합은 이 방향이다. 다만 문자열 enum과 `partial` 하나만으로 의무별 근거를 모두 복원할 수 없으므로 구조화된 증거를 추가한다.

### 6.3 적용 조건과 요구 조건

의무 `o`를 `(A, R)`로 정의한다. `A`는 적용 조건, `R`은 요구 조건이다.

| A | R | 의무 충족 명제 | 표시 |
|---|---|---|---|
| F | 임의 | T | 적용 대상 아님 |
| T | T | T | 충족 |
| T | F | F | 위반 |
| T | U | U | 요구 사항 판단 불가 |
| U | T | T | 요구는 충족했으나 적용 범위 불확실 |
| U | F 또는 U | U | 적용 여부부터 판단 불가 |

논리식은 `¬A ∨ R`이다. `A=U, R=T`에서는 이 의무를 만족한다는 명제만 참이다. ‘검사 범위 전체를 이해했다’고 표시하지 않는다. 특정 임계값을 넘었는지 모르는 파일에서 문서가 없다는 이유만으로 확정 위반을 만들지 않는다.

### 6.4 결정에 필요한 증거와 전체 범위 증거

- AND에서 한 의무의 위반은 전체 위반을 입증한다. 다른 의무가 unknown이어도 이미 알려진 위반을 숨기지 않는다.
- OR에서 충분한 하나의 참 증거는 충족을 입증한다. 사용하지 않은 대안의 unknown 때문에 그 명제를 취소하지 않는다.
- 두 경우 모두 ‘전체 범위를 다 분석했다’는 별도 주장을 추가하지 않는다.
- 현재 AND의 `violated / partial`은 결정의 확실성과 범위의 불완전성을 한 쌍으로 나타낸다. 새 모델에서는 `decision_proven=true`, `scope_complete=false`처럼 분리할 수 있다.

증거 구조의 노드는 `atom`, `all`, `any`, `conditional`로 제한한다. 각 노드에는 안정 ID, 자식 ID, 판정, 사용한 증거, 미사용 대안, reason code를 둔다. 이유 문자열을 합쳐서 최종 근거를 재구성하지 않는다.

### 6.5 입증할 성질

가정: 각 원자 판정이 5절의 해석에 대해 건전하고, 의무 집합이 범위 내에서 완전하며, 입력과 프로필이 고정되어 있다.

**목표 정리:** 위 AND/OR/conditional 규칙으로 결합한 T/F 판정도 같은 해석에서 건전하다. 구조적 귀납으로 원자 → 결합 노드 순서의 증명을 구성할 수 있다. 단, 이 정리는 원자 추출기의 건전성이나 의무 누락 부재를 대신 증명하지 않는다. E01은 의무 완전성 전제를, E02는 원자 건전성 전제를 깨뜨린다.

## 7. 정책 언어와 자동 분석의 재설계

### 7.1 단일 강도 순서와 계약 종류를 분리

현재 [intensity.py](../../drift_gate/core/classification/intensity.py)는 환경 키·함수 시그니처 등을 숫자 순위로 비교하고 여러 계약 종류에 같은 순위를 준다. 이는 호환용 휴리스틱으로 이해할 수 있지만 ‘환경 변경이 API 변경보다 작다’는 의미 증명은 아니다.

새 정책은 다음 세 축을 별도로 갖는다.

```text
selector       : 어떤 경로·진입점·변경을 볼 것인가
contract_kind  : routes / response-schema / env-references / ...
trigger        : added / removed / modified / possible-change
severity       : 조직이 정한 운영 영향
```

기존 `min_change_intensity`는 legacy 프로필에 남기고 새 의미로 조용히 재해석하지 않는다. 정책 미리보기에서 해당 설정 때문에 제외된 파일과 불확실한 후보를 표시한다.

### 7.2 자동 모드의 의무 집합

1. 설정된 프로필들의 applicability를 각각 계산한다.
2. T인 프로필은 사실 추출·변경 비교를 실행한다.
3. U인 프로필은 자신의 불확실성을 남기며, 다른 종류의 결과로 덮지 않는다.
4. 각 프로필의 문서 형식과 명시 경로를 연결한다. OpenAPI를 환경 예제 파일로 임의 해석하지 않는다.
5. 생성한 의무들을 정책에 따라 AND/OR로 결합한다.
6. 모든 대상 프로필의 변경 없음이 입증된 경우에만 전체 not-applicable을 허용한다.

‘모든 프로필’은 세상의 모든 계약 종류가 아니라 정책에 선언한 닫힌 목록이다. 선언되지 않은 지원 영역은 `not-evaluated`로 노출한다. 자동 탐지기가 아무 종류도 찾지 못했다면 ‘아무 의무도 없다’와 ‘종류를 식별하지 못했다’를 나눈다.

### 7.3 파일 집합과 관계 의미

규칙 `r`의 상위 트리거 범위를 `S_r`, 관계 `j`의 자체 범위를 `S_j`로 둔다. 상위 적용 조건이 성립하고 `S_j`에 관계를 촉발하는 변화가 있을 때, 요구 내용은 **관계의 계약 범위 `C_j`**에서 추출한다. `C_j`는 필요한 의존 파일까지 포함할 수 있으며 `S_r`로 대체하지 않는다.

현재 관계별 `source_files`를 분리한 개선은 유지한다. 문서의 수신 범위, 트리거 파일, 사실 추출에 읽은 의존 파일을 각각 기록해야 한다. rename은 이전·이후 경로와 정체성을 모두 고려하고 ignore가 양쪽에 어떻게 적용되는지 정책 버전으로 고정한다.

### 7.4 문서 대안과 조각 합치기

`any`가 ‘문서 A 또는 B 중 하나가 완전하면 됨’인지, ‘A와 B의 내용을 합쳐 완전하면 됨’인지 구분한다. 기본 대안 모델에서는 서로 불완전한 두 문서를 합쳐 하나의 완전한 문서라고 판정하지 않는다. 분할 명세를 허용하려면 별도 `document_bundle`과 중복·충돌 해결 규약이 필요하다.

## 8. 계약별 지원 프로필과 의미 확장

### 8.1 지원 선언을 실행 가능한 계약으로 만든다

| 프로필 | 현재 근거 | 명시할 제한 | 확장 시 필수 시험 |
|---|---|---|---|
| Python 정적 route | 같은 모듈 FastAPI/APIRouter·리터럴 경로·지원 mount | 외부 router, 동적 호출, entrypoint 미확정 | 직접/중첩/미등록/중복/호출 순서/그림자 이름 |
| Python 응답 schema | 단순 BaseModel 필드와 일부 primitive | 외부 모델, validator, 복합 타입, 상태 코드·미디어 다양성 | 모델 이름만 변경, 값 구조 변경, defaults, nullable, 필수성 |
| Express 정적 route | 기본 ESM 값 import·직접 const·같은 모듈 mount·체인 | CommonJS, type-only, 조건부 등록, path pattern, middleware | AST 토큰 변형, 실제 HTTP 경로, import 제거 대조 |
| 환경 키 | Python 별칭·일부 정적 접근, JS 리터럴 접근 | 동적 키, scope, 외부 설정 라이브러리 | 새 위치/새 전역 키/전체 요구 키 구분 |
| OpenAPI 문서 | bounded JSON·안전 YAML·제한된 operation/schema 해석 | 표준 전체·외부 ref·복잡한 JSON Schema | 중복 키, 참조 순환, unsupported dialect, 수치·깊이 경계 |
| Markdown 경로 표기 | 정해진 표기의 메서드·경로 추출 | 부정문·예시·과거 설명의 자연어 의미 | 명시 블록 밖 표기와 현재 계약 선언 구분 |

지원 목록은 설명 문구에만 남기지 않고 parser/profile 버전과 fixture 목록으로 연결한다. 새로운 프로필은 기존 프로필의 의미를 넓히지 않고 독립 버전으로 도입한다.

### 8.2 경로 동일성과 서비스 범위

정규화 키는 최소 `(service_id, entrypoint_id, method, effective_path)`로 설계한다. 단일 서비스 모드에서는 앞 두 값을 고정할 수 있다. 두 마이크로서비스의 `GET /health`를 전역 중복으로 처리하지 않는다. 반대로 같은 앱에 두 번 등록된 경로는 의미가 프레임워크·순서에 따라 달라질 수 있으므로 집합으로 조용히 합치지 않는다.

현재 정적 route는 URL 매개변수·정규식·암묵적 HEAD/OPTIONS·라우터 옵션을 전부 모델링하지 않는다. 지원하지 않는 차원은 프로필 범위 밖이라고 표시한다. GET 경로 일치가 인증·오류 응답·트랜잭션·HTTP 전체 동작을 검증했다는 뜻은 아니다.

### 8.3 계약 동기화와 호환성은 다른 명제

`문서가 현재 구현과 일치한다`와 `변경이 기존 소비자에게 호환된다`를 분리한다. 전자는 전후 구현 및 현재 문서 관계이고, 후자는 이전·이후 소비자/생산자 허용 집합의 관계다.

```text
요청 호환성의 한 조건: 이전에 받던 요청 ⊆ 새 구현이 받는 요청
응답 호환성의 한 조건: 새 구현의 응답 ⊆ 기존 소비자가 처리 가능한 응답
```

이는 단순 타입 집합 모델에서의 조건이다. 실제 호환성에는 상태 코드, 순서·부작용, 인증, 기본값, 단위, 성능, 의미 변화가 추가된다. 스키마 필드 개수가 같다고 호환을 확정하지 않는다. request와 response의 required/enum/nullable 비교 방향을 같은 규칙으로 처리하면 안 된다.

OpenAPI는 API 기술 형식을 정의한다. 이 제품의 제한된 필드 비교를 OpenAPI 전체 적합성 또는 API 호환성 검증으로 부르지 않는다. 새 dialect를 수용할 때는 별도 적합성 자료가 필요하다. [OpenAPI 3.1.2](https://spec.openapis.org/oas/v3.1.2.html)

### 8.4 자연어 문서는 독립적인 증거 수준

Markdown에 경로가 한 번 등장했다는 것은 ‘이 표기가 있다’는 증거다. 실제 현재 계약이라는 증거로 승격하려면 명시 선언 블록 또는 구조화 명세가 필요하다. `예전에는 GET /old를 사용했다` 같은 문장은 제거된 경로의 현재 존재를 뜻하지 않는다.

LLM은 관련 문장·의무 후보·설명을 제안할 수 있다. 모델의 자신감이나 다른 모델의 동의로 verified를 만들지 않는다. 자연어 승인에는 사람이 선택한 원문, 판단, 이유, 적용 범위, 버전, 승인 시각을 남긴다.

## 9. 범위 완전성과 의존 그래프

### 9.1 정체성과 closure

계약 범위가 닫혔다는 증거 `ClosureWitness`를 도입한다. 여기에는 시작 진입점, 탐색한 import·등록·참조 간선, 분석하지 못한 간선, 제외 규칙, graph digest, 자원 사용량이 들어간다.

단순히 모든 import 파일을 읽는 것으로 충분하지 않다. 동적 import, 런타임 재등록, 외부 프레임워크 설정이 있으면 그래프가 열려 있을 수 있다. 프로필이 허용한 해석 안에서만 closure를 주장한다.

### 9.2 영향 범위 계산

1. 전후 그래프를 별도로 구성한다. 삭제된 간선을 이후 그래프만으로 추적하지 않는다.
2. 변경 노드에서 관련 계약의 역방향 의존성을 따라 소비 진입점을 찾는다.
3. 선택된 진입점에 필요한 전후 사실을 수집한다.
4. 읽지 못한 의존성과 범위 상한을 unknown으로 전달한다.
5. 미변경 파일의 사실도 전역 key/route 부재 판정에 필요하면 포함한다.

환경 키 비교는 ‘각 파일에서 얻은 추가 집합의 합’과 ‘전체 전후 집합의 차’가 다를 수 있다. 현재 [environment_delta](../../drift_gate/core/evaluation/environment.py)의 혼합 unknown·전역 키 의미는 추가 명세와 통제가 필요하다. 이를 이번 실행으로 확정 결함이라고 부르지는 않는다.

### 9.3 비용 제어

그래프 캐시는 `(원문 해시, 프로필 버전, parser 해시, 의미 설정)`에 묶는다. 경로만으로 캐시하지 않는다. 음성 결과인 ‘사실 없음’에도 같은 버전과 closure 근거가 필요하다. 사이클은 SCC 또는 명시 순환 처리로 종료하고, 상한 초과는 범위가 비었다고 처리하지 않는다.

## 10. 결과 IR과 외부 계약

다음은 **제안 구조**이며 현재 지원하는 설정 파일 예제가 아니다. 프로덕션 스키마 버전 번호는 마이그레이션 검토 후 확정한다.

```text
InspectionResult
  schema_id, run_id, semantic_input_digest
  engine: artifact_digest, source_digest, profiles[], parser_digests[]
  subject: repository_id, base_oid, head_oid, comparison_mode, manifest_digest
  context: evaluated_at, timezone, policy_digest, authorization_digest
  scopes[]: id, selectors, entrypoints, included, excluded, closure
  facts[]: id, kind, identity, before/after, certainty, evidence_refs
  obligations[]: id, applicability, proposition, truth, proof_ref, reason_codes
  proof_nodes[]: id, operator, children, witnesses, unresolved
  coverage: complete_scopes, open_scopes, excluded_scopes
  enforcement: action, blocking_obligations, unresolved_obligations, waivers
  execution: status, limits, usage, diagnostics, publication_status
```

`EvidenceRef`는 원문 해시와 범위, 인코딩, byte/line 좌표 규약, 분석기 버전을 가리킨다. 문서 표시를 위해 잘라 낸 excerpt는 원문의 대체물이 아니다. git rename과 path 표시의 정규화는 원문 정체성과 분리한다.

핵심 타입은 immutable dataclass와 enum/union으로 좁힌다. `Unknown(reason_code, scope, retained_facts)`와 `ExactDelta(added, removed, witness)`를 구분해 빈 집합에 여러 의미를 얹지 않는다. 모든 값에 interface를 추가할 필요는 없다. 파서·clock·snapshot store·publisher처럼 실제 교체·장애 주입 경계에만 port를 둔다.

reason code는 `missing_source`, `unsupported_binding`, `open_dependency_scope`, `mixed_contract_scope`, `unsupported_numeric_range`, `resource_limit`, `invalid_policy`, `stale_authorization`, `evidence_mismatch`처럼 안정적인 기계 값으로 정의한다. 사용자 문장은 별도 번역 계층에서 만든다. CLI·MCP·Desktop·HTML은 동일 IR의 projection이어야 하며 자체적으로 pass를 추론하지 않는다.

## 11. 목표 아키텍처와 모듈 경계

### 11.1 데이터 흐름

```text
CLI / MCP / Desktop / GitHub Action
                 │
         Inspection Application
                 │
       Request & Authority Validation
                 │
    Immutable Snapshot + Trusted Policy
                 │
      Scope Planner / Profile Registry
                 │
    Bounded Analyzer Workers / Document Decoders
                 │
          Normalized Contract Facts
                 │
    Pure Obligation Evaluator + Proof Builder
                 │
      Enforcement Policy + Result Validator
                 │
      Receipt Store ── Publisher / UI Projection
```

현재 [inspection.py](../../drift_gate/adapters/inspection.py)의 공통 진입점은 유지하고 단계별 불변 입력과 결과를 도입한다. CLI·Qt·MCP가 각각 별도 판정기를 갖지 않게 한다. 초기 구현은 하나의 애플리케이션 안에서 모듈을 분리한다. 파서 자원 격리가 필요할 때만 프로세스를 분리하고, 그 이유만으로 여러 네트워크 서비스로 나누지 않는다.

### 11.2 소유권과 금지 의존성

| 영역 | 소유하는 책임 | 들어가면 안 되는 책임 |
|---|---|---|
| 입력 adapter | Git·원문·API·정책 읽기, 크기·경로 검증 | 정책 의미를 별도로 결정 |
| 분석 adapter | 문법 파싱·프레임워크 바인딩·문서 decode | 최종 조직 조치·승인 권한 결정 |
| domain/core | 사실 비교·의무·증거 결합·불변식 | 파일·네트워크·현재 시각·Qt 접근 |
| application | 단계 순서·deadline·취소·복구·영수증 | 언어별 AST 노드 상세 |
| store | 원자 기록·CAS·검증된 schema·보존 | 성공 화면 문구·정책 예외 판단 |
| presentation | 판정과 한계를 사용자에게 전달 | 증거 없는 확정 문구 생성 |

Python AST 처리가 현재 core 일부에 존재한다. 이를 단순히 경로 이동으로 개선했다고 주장하지 않는다. 먼저 입력 문자열 → 정규화 사실의 순수 계약을 고정하고, native parser·Python AST·문서 decode의 오류 계약을 일치시킨 뒤 이동한다. 리팩터링 전후 동일 입력의 IR을 비교한다.

### 11.3 응집도 기준

- 함수 길이보다 변경 이유를 본다. profile 선택과 env/API 의미 비교와 reporter 문장 생성이 한 함수에서 바뀌면 분리 대상이다.
- `ChangedFile`에 모든 분석기의 선택 필드를 계속 추가하는 방식은 한계가 있다. 공통 `SourceArtifact`와 계약별 `FactBundle`을 구분한다.
- 전역 캐시·환경변수 변경은 parser adapter 경계에 가두고 동시 실행·예외 시 복구를 검증한다.
- `except Exception → empty facts`를 금지한다. 운영 오류, 미지원 구문, 확정 부재를 다른 타입으로 반환한다.
- 사용하지 않는 추상 class나 단순 함수마다 factory를 추가하는 작업은 우선순위에 넣지 않는다.

## 12. 입력 수집·동일성·재현 가능성

### 12.1 두 수집 모드

**불변 CI 모드:** Git 객체의 기준·대상 commit을 먼저 고정하고, 코드와 문서를 같은 버전에서 읽는다. 정책은 신뢰한 별도 ref 또는 승인된 정책 digest에서 읽는다. 태그·브랜치 이름은 표시값일 뿐 실제 OID로 치환한다.

**로컬 편집 모드:** 미저장·미추적·working tree 파일을 포함하는지 선언한다. 선택한 파일을 별도 스냅샷으로 복사하고 해시 목록을 완성한 뒤 분석한다. 수집 도중 바뀐 파일은 다시 수집하거나 `snapshot_unstable`로 거부한다. ‘읽기 전후 status가 같다’는 검사만으로 전체 수집 원자성을 증명하지 않는다.

원문이 A→B→A로 바뀌는 ABA나 읽은 파일들의 시점 혼합을 줄이려면 분석 입력은 최종 확보한 불변 사본이어야 한다. 작업 폴더와 사본이 수집 종료 시 일치하는지는 별도 상태다. 파일시스템 전체의 순간 스냅샷을 보장하지 못하면 그 한계를 명시한다.

### 12.2 manifest 상태

```text
present(bytes, digest)     # 실제 확보한 내용
absent(witness)           # 해당 버전에 없음을 확인
unavailable(reason)       # 권한·I/O·원격 오류
unsupported(reason)       # 파일 형식·경로 표현 미지원
limited(bound, observed)  # 크기·개수·시간 제한
excluded(policy_reason)   # 명시 정책에 의해 제외
```

문서 absent는 정책에 따라 위반을 입증할 수 있다. unavailable은 부재의 증거가 아니다. 빈 파일과 수집하지 못한 파일을 모두 빈 문자열로 만들지 않는다. 삭제된 파일의 이후 상태는 부재, 변경 전 상태는 확보해야 할 근거다.

### 12.3 실행 해시와 의미 해시

현재 입력 해시는 원문 snapshot·정규화 문서·route facts를 포함하는 장점이 있다. 그러나 파일 배열 순서·표현 규약·엔진 버전까지 묶는 재현 프로토콜은 따로 명세해야 한다.

- `raw_digest`: 원문 bytes. 줄바꿈·공백·Unicode를 임의 정규화하지 않는다.
- `manifest_digest`: 정해진 순서·경로 표현·수집 상태를 가진 manifest.
- `semantic_input_digest`: manifest, 정책 의미, profile, 엔진, parser, 평가 context, 승인 근거.
- `result_digest`: 시간·UUID·실행 시간 같은 비의미 필드를 제외한 결과 projection.
- `receipt_digest`: 실행 메타데이터와 결과·아티팩트 digest를 모두 포함한 영수증.

순서 없는 집합만 정렬한다. 라우트 등록 순서·정책 우선순위·JSON 배열처럼 의미 있는 순서는 보존한다. 숫자는 허용 도메인을 먼저 고정한다. `json.dumps(sort_keys=True)`를 다른 언어와 호환되는 표준 canonical JSON 구현이라고 부르지 않는다. RFC 8785는 재현 가능한 JSON 해시 형식을 선택할 때 참고할 수 있지만, 수치·문자열 규약까지 적합성 시험해야 한다. [RFC 8785](https://www.rfc-editor.org/info/rfc8785/)

### 12.4 재현 영수증의 필수 조건

정확한 입력 해시뿐 아니라 원문을 다시 얻을 수 있는 보존 위치 또는 Git 객체가 필요하다. 해시만 남기고 원문·비공개 정책을 잃으면 동일 입력 재실행은 불가능하다. 원문 보관은 접근 통제·보존 기한과 함께 설계한다. 비밀 값의 단순 해시도 저엔트로피 값의 노출 위험을 완전히 없애지 않는다.

## 13. 신뢰 모델과 공급망

### 13.1 행위자·자산·경계

| 행위자/입력 | 기본 신뢰 | 보호할 대상 |
|---|---|---|
| PR 작성자의 코드·문서·설정 | 분석 대상, 비신뢰 | 검사기 실행 환경·정책·조직 비밀 |
| PR 안의 정책 변경 | 검토 후보 | 기존 의무의 무단 약화 방지 |
| 승인된 정책 관리자 | 정책 변경 권한 | 승인 범위·감사 기록 |
| 고정 검증기 빌드 | 검증된 출처의 실행물 | 대상 코드가 검증기를 바꾸지 못함 |
| GitHub 승인 API·주체 | 인증 후 해당 승인만 신뢰 | commit 바인딩·권한·만료 |
| 문법 라이브러리·패키지 | 공급망 의존성 | 해시·버전·출처·격리 |
| 모델이 쓴 설명·PR 텍스트 | 참고 데이터 | 도구 실행·승인 권한으로 전환 금지 |

악성 PR뿐 아니라 우발적 도구 버전 변경, 잘못된 정책 경로, 오래된 결과 게시, 캐시 오염도 포함한다. OS 관리자·신뢰 빌더 자체의 완전한 침해까지 현재 단일 도구가 방어한다고 주장하지 않는다.

### 13.2 후보가 검증기를 바꾸는 자기 검증 문제

제품 자신의 PR에서 후보 버전으로 테스트하는 것은 정상적인 개발 활동이다. 그러나 **후보가 수정할 수 있는 엔진·정책·워크플로만으로 그 후보의 병합을 승인하는 것**은 독립적인 신뢰 검증이 아니다.

검사를 둘로 나눈다.

1. 후보 테스트: 수정된 엔진이 기존·새 회귀와 독립 oracle을 만족하는지 본다.
2. 신뢰 검사: 승인된 고정 엔진과 보호된 정책으로 후보 입력·약화 변경·필수 근거를 확인한다.

두 결과의 도구 digest와 역할을 함께 기록한다. 신뢰 검사도 미래 버그가 없음을 증명하지 않으므로 외부 평가·사람의 검토를 대체하지 않는다. privileged workflow가 PR 코드를 실행하지 않도록 경계를 유지한다. GitHub도 비신뢰 코드와 권한 있는 실행의 분리를 강조한다. [GitHub Actions secure use](https://docs.github.com/en/actions/reference/security/secure-use)

### 13.3 실행 격리

- 분석 worker는 원문 read-only, 출력 전용 디렉터리, 비밀 없는 환경, 네트워크 차단을 기본으로 한다.
- 대상 코드의 import, 설치 hook, 빌드 script, Git hook, 외부 diff/textconv를 자동 실행하지 않는다.
- parser는 네이티브 코드이므로 파일 크기 검사만으로 안전이 완성되지 않는다. 프로세스별 시간·메모리·출력 상한을 둔다.
- symlink, 경로 이탈, 대소문자 충돌, 비UTF-8 경로는 OS 차이를 고려한 명시 계약으로 처리한다. 지원하지 못하면 진단한다.
- 원격 OpenAPI `$ref`를 임의 URL로 따라가지 않는다. 도입 시 허용 호스트·프로토콜·응답 크기·깊이·캐시·SSRF 방어가 별도 필요하다.

### 13.4 해시·서명·출처 증명의 역할

해시는 동일성, 서명은 특정 키/주체의 진술, 출처 증명은 빌드·입력·절차의 관계를 제공한다. 어느 하나도 판정 내용의 참을 보장하지 않는다.

공급망 결과를 검증할 때는 아티팩트 digest, 서명 주체, 신뢰한 빌더, 저장소, 빌드 종류, 외부 인자가 기대와 일치하는지 확인해야 한다. 이는 SLSA의 검증 절차를 참고한 설계다. 이 문서를 작성했다고 SLSA 수준을 달성한 것은 아니다. [SLSA 1.2 artifact verification](https://slsa.dev/spec/v1.2/verifying-artifacts)

장기 영수증은 in-toto Statement의 subject digest와 predicate 구조에 연결할 수 있다. Drift Gate의 결과 schema를 그대로 SLSA provenance라고 이름 붙이지 않고, 빌드 출처와 논리 검사 결과를 다른 predicate로 둔다. [in-toto Statement v1](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md)

## 14. 실행 상태 기계·실패·동시성

### 14.1 상태 전이

```text
received → validated → captured → analyzed → evaluated → persisted → published
               └── rejected
어느 실행 단계 → failed / timed-out / cancelled
persisted → publication-pending → published / publication-failed
```

판정 완료와 외부 게시 완료를 분리한다. 게시 API 실패가 이미 계산·보관한 판정을 바꾸지 않게 한다. 입력이 invalid라면 결과를 `pass`로 직렬화하지 않는다. 취소 후 늦게 돌아온 worker 결과는 현재 세대의 결과로 채택하지 않는다.

### 14.2 안전성 불변식

| ID | 목표 불변식 | 검증 방법 |
|---|---|---|
| INV-01 | 판정의 모든 증거가 동일한 의미 입력에 속함 | 서로 다른 head/doc digest 혼합 거부 |
| INV-02 | unknown·에러가 빈 사실 또는 no-delta로 변환되지 않음 | 누락·parser failure·limit 장애 주입 |
| INV-03 | 알려진 위반이 무관한 unknown 때문에 사라지지 않음 | AND/OR·조건부 조합 전체표 |
| INV-04 | 무관한 계약의 변경 없음이 다른 의무를 삭제하지 않음 | E01 및 혼합 종류 조합 |
| INV-05 | 오래된 run이 최신 head의 결과를 대체하지 않음 | 완료 순서 역전·push 중 재검사 |
| INV-06 | 같은 command ID의 다른 입력은 거부됨 | idempotency key 충돌 |
| INV-07 | 승인된 예외가 사실 결과를 덮어쓰지 않음 | 위반·waiver·action의 독립 검증 |
| INV-08 | core의 의미 결과는 숨은 시각·I/O에 의존하지 않음 | 고정 context replay, clock 경계 |
| INV-09 | 모든 수락 실행은 성공 또는 명시 종결 상태를 남김 | crash·timeout·응답 유실 |
| INV-10 | reporter·cache가 원 판정보다 강한 보장을 만들지 않음 | 진입점·직렬화·캐시 왕복 비교 |
| INV-11 | 문서·정책·승인 오류를 코드 위반과 구분 | exit code·JSON schema 통제 |
| INV-12 | 제한 때문에 분석하지 못한 범위를 coverage에서 숨기지 않음 | 개수·깊이·bytes 상한 ±1 시험 |

### 14.3 진행성 조건

‘결국 완료된다’는 속성에는 작업 시간이 유한하고, worker가 스케줄되며, 저장소가 복구되는 등의 환경 가정이 필요하다. deadline을 두면 성공을 보장하는 대신 시간 안에 `timed-out`을 포함한 종결 상태로 간다는 목표를 세울 수 있다. 출력 경로 자체가 고장 나면 중앙 영수증을 남기지 못할 수 있으므로 프로세스 종료 상태와 별도 운영 로그로 보완한다.

상태 모델은 TLA+/PlusCal 같은 도구로 유한 인스턴스를 모델 검사할 수 있다. 처음에는 run 2개, head 2개, worker 2개, 취소·중복·게시 실패를 포함해 INV-05/06/09를 검증한다. 모델 검사 범위와 환경 가정을 기록하며, 모델 통과를 Python 구현의 자동 증명으로 표현하지 않는다. [Lamport, Specifying Systems](https://lamport.azurewebsites.net/tla/book.html)

### 14.4 쓰기·재시도 계약

`run_id`는 실행 식별자, `semantic_input_digest`는 입력 식별자, `command_id`는 쓰기 의도 식별자다. 서로 대체하지 않는다. 게시·저장 시 응답이 유실되면 같은 idempotency key로 상태를 조회하고, 기록 여부를 확인한 뒤 재시도한다. ‘오류를 받음’과 ‘저장되지 않음’을 동일하게 취급하지 않는다.

기존 초안·CAS·세션 수명 잠금의 개선은 유지한다. 논리 검사 리팩터링을 이유로 편집 데이터를 삭제하거나 기존 복구 형식을 바꾸지 않는다. 저장 성공 후 history·cleanup·게시 실패는 후속 상태로 분리하는 기존 설계 방향을 계승한다.

## 15. 정책 변경·예외 승인·시간

### 15.1 정책 변경도 계약 변경

검증기는 trusted policy와 candidate policy를 모두 읽을 수 있지만, 승인 전에 candidate가 자신에게 적용될 의무를 약화시키지 못하게 한다. 변경 유형을 `selector 축소`, `severity 완화`, `unknown 조치 완화`, `content mode 변경`, `예외 권한 확대`, `프로필 교체`로 분류한다.

정책의 의미적 포함 관계는 glob·조건부·내용 검사까지 있으면 단순 문자열 비교로 완전히 결정하기 어렵다. [현재 policy guard](../../drift_gate/core/policy/guard.py)의 패턴 검출을 완전한 약화 증명이라고 부르지 않는다. 정적으로 포함 관계를 입증하지 못한 변경은 검토 대상으로 남긴다.

### 15.2 예외 승인 envelope

```text
Waiver = (policy_digest, obligation_ids, subject_commit,
          issuer, verified_authority, reason, issued_at, expires_at,
          evidence_digest, revocation_state)
```

예외는 정확한 commit과 의무에 적용한다. 새 push가 오면 필요한 승인을 다시 확인한다. 팀·경로 소유권이 바뀌면 승인자가 지금도 권한을 갖는지 정책으로 정한다. PR 본문의 `approved_by` 문자열은 권한 증거가 아니다.

### 15.3 시각의 명시적 주입

**코드 확인:** [evaluator](../../drift_gate/core/evaluation/evaluator.py)의 ignore 만료 처리는 `date.today()`를 직접 읽는다. 같은 파일과 정책도 실행 날짜에 따라 달라질 수 있으므로 ‘core는 완전히 순수하다’는 표현은 현재 성립하지 않는다.

설계는 `EvaluationContext.evaluated_at`을 trusted application이 주입하고 영수증에 포함하는 것이다. 과거 결과 재현은 당시 context로, 현재 병합 가능 여부 판단은 현재 신뢰 시각으로 별도 실행한다. 과거 승인 재현을 현재 유효 승인으로 오인하지 않는다. 날짜 경계·시간대·만료 순간의 포함 규칙을 명세하고 시험한다.

## 16. 자원 제한·운영 지표·정보 보호

### 16.1 전역 자원 예산

현재 일부 파서에는 파일 약 1 MB, AST/문서 노드 20,000, 문서 깊이 20, router 확장 상한 등이 있다. 이는 좋은 시작이지만 파일별 제한 합계와 parser 생성 전 할당 비용을 제어하는 전역 실행 예산과는 다르다.

| 예산 | 초과 결과 | 측정 항목 |
|---|---|---|
| 전체 수집 bytes·파일 수 | capture limited | 대상/수집/제외 bytes와 파일 수 |
| AST 메모리·CPU·wall time | analyzer timed-out/limited | 언어·profile별 최대값·분위수 |
| 의존 그래프 노드·간선·깊이 | open scope | 미탐색 frontier와 관련 의무 |
| 문서 refs·노드·배열 길이 | unsupported/limited | 제한 종류와 임계값 |
| 결과·로그·증거 크기 | bounded output | 잘린 표시와 원 증거 위치 |
| 대기열·동시 실행 | queued/rejected | 대기 시간·취소·우선순위 |

구체적 제한 수치는 실제 workload를 측정해 versioned profile로 결정한다. 측정 없이 ‘대기업 저장소도 수초 내 처리’ 같은 목표를 완료 수치로 기재하지 않는다. 제한에 걸린 파일을 생략하고 남은 결과만 전체 verified로 내보내면 안 된다.

### 16.2 운영 지표의 정의

| 지표 | 분자 / 분모 또는 정의 | 주의 |
|---|---|---|
| 완결 실행률 | 종결 영수증이 있는 수락 run / 수락 run | 논리 판정 성공률과 다름 |
| 분석 보류율 | unknown 의무 / 적용 또는 적용 불확실 의무 | unsupported·입력 실패·limit 원인별 분리 |
| 불필요 차단률 | 사람 확인 정상인데 block된 PR / 확인 정상 PR | 표본 선택 편향 공개 |
| 검증 판정 오류율 | verified 명제가 틀린 의무 / 독립 검토한 verified 의무 | gate 일치율과 별도 |
| 결과 최신성 위반 | 다른 head에 게시된 결과 수 | 목표 0, 실제 관측 별도 |
| 결정 지연 | 수락 → persisted 시간의 p50/p95/p99 | 큐 대기와 분석 시간 분리 |
| 조치 시간 | 발견 → 담당자 수정/승인 완료 시간 | 도구 실행 시간과 다름 |

SLO는 파일 수·언어·변경량이 고정된 소/중/대 workload를 먼저 정의한 뒤 정한다. 최소 3회 반복은 변동 확인의 시작일 뿐 p99 추정에 충분하지 않다. cold/warm cache, OS, CPU, 메모리, 병렬 수, 타임아웃을 기록한다. 다중 팀 서비스가 도입되면 팀별 할당량과 장애 격리를 추가한다.

### 16.3 보존·감사·비밀

보고서에서 전체 source snapshot을 생략해도 patch와 excerpt에 비밀이 있을 수 있다. 공개 artifact와 비공개 증거를 분리하고, 기본 reporter는 필요한 최소 문맥을 사용한다. 비밀 탐지가 완전한 제거를 보장한다고 주장하지 않는다.

원문 삭제 기한, 영수증 보존 기한, 민감 자료 접근자, 삭제 감사 기록을 운영 정책에 둔다. ‘무조건 영구 보관’과 ‘재현에 필요한 자료 자동 삭제’ 모두 피한다. Desktop 단독 사용자와 조직 호스팅의 보존 요구는 다르므로 같은 기본값을 강제하지 않는다.

## 17. 객관적 평가 설계

### 17.1 평가 단위와 정답

PR 하나에 여러 의무가 생긴다. 다음 단위를 섞지 않는다.

1. 사실 추출 단위: route, key, schema field와 source span.
2. 의무 단위: 적용 여부·요구 충족·unknown.
3. PR 단위: 최종 gate와 차단 이유.
4. 실행 단위: 수집·시간·오류·재현성.

정답 레코드는 `base/head`, 정책, profile, 영향 범위, 사실 변화, 의무, 기대 검증 상태, 기대 조치, 판단 근거, 평가자, 불일치 해결 기록을 가진다. 입력이 잘린 사례의 정답도 ‘완전한 소스를 아는 사람의 정답’과 ‘주어진 입력으로 입증 가능한 정답’을 분리한다.

### 17.2 데이터 분리

| 집합 | 역할 | 변경 규칙 |
|---|---|---|
| 기존 v1 | 과거 수치와 실패 경계 보존 | 삭제·기대값 사후 조정 금지. 명세 오류는 새 버전으로 정정 |
| 개발 회귀 | 수정한 결함과 정상 통제 | 개발 중 반복 사용 가능, 일반화 점수 제외 |
| metamorphic | 의미 보존/변경 변환 관계 | 변환 전제와 seed·generator 버전 보존 |
| framework oracle | 다른 실행 의미와 대조 | 작성한 안전 fixture만 실행, 프레임워크 고정 |
| 저장소 holdout | 개발에 쓰지 않은 프로젝트/PR | 저장소 단위 분리, 튜닝에 쓰면 더 이상 holdout 아님 |
| 시간 holdout | 특정 시점 이후 변경 | 훈련·튜닝 종료 시각과 표본 추출 규칙 선등록 |
| 외부 사람 평가 | 독립 정답과 사용성 | 도구 출력 가림, 불일치 기록, 별도 최종 판정 |

현재 22개 평가의 사실 확인도 [audit_auto_contracts.py](../../scripts/audit_auto_contracts.py)에서 운영 추출 함수를 사용한다. 수작업 기대값과 비교하는 회귀로 유효하지만, 사실 추출기의 독립 구현을 사용한 검증으로는 세지 않는다. FastAPI 생성 결과와 TypeScript import 제거처럼 독립 실행 계층의 대조를 보강한다.

### 17.3 다자 평가의 독립성

‘여러 AI가 동의했다’는 것은 독립적인 정답의 수가 아니다. 같은 문서·코드·전제·오답을 공유할 수 있다. 평가 역할을 다음과 같이 분리한다.

- 명세 평가자: 요구 조건과 지원 범위가 모호하지 않은지 판단.
- 반례 평가자: 명세를 깨는 최소 입력 탐색, 정상 통제도 함께 작성.
- 실행 평가자: 기대값을 바꾸지 않고 별도 환경에서 재현.
- 사용자 평가자: 경고가 실제 수정 행동으로 이어지는지 확인.

가능하면 두 사람 이상이 도구 결과를 가린 상태에서 라벨링하고 제3자가 불일치를 조정한다. 사람을 확보하지 못한 AI 다중 관점 평가는 ‘AI 검토’로 명시한다. 이번 문서는 단일 작성자의 코드 검토·프로브이며 인간 다자 맹검 평가를 수행했다고 주장하지 않는다.

### 17.4 지표와 분모

진짜 위반인 의무 수를 `N_v`, 진짜 정상인 의무 수를 `N_s`로 두고 unknown 정답은 별도 집계한다.

```text
violation_precision = 올바른 위반 판정 / 모든 확정 위반 판정
violation_recall_all = 올바른 위반 판정 / N_v
decision_coverage   = T 또는 F로 답한 의무 / 평가 가능한 정답 의무
selective_error     = 틀린 확정 판정 / 확정 판정
false_verified      = 충분한 증거를 주장했으나 명제가 틀린 건수와 비율
abstention_rate     = U로 답한 의무 / 전체 대상 의무
gate_accuracy       = 기대 조치와 일치한 PR / 전체 평가 PR
```

분모가 0이면 `N/A`와 건수를 표시한다. 보류한 위반을 recall 분모에서 조용히 빼지 않는다. 확정 판정 중 recall을 따로 제시할 수 있지만 이름과 분모를 구별한다. precision/recall은 지원 종류별·언어별·입력 완전성별로도 공개한다.

항상 pass, 항상 fail, 변경 경로만 보는 정책, 기존 legacy auto를 baseline으로 둔다. 원래 경계 사례의 항상 fail은 6/8이고 현재 gate 일치는 5/8이다. 이는 gate 일치 하나로 분석 품질을 평가하면 왜곡될 수 있다는 예다. 보류를 늘려 확정 오류를 줄인 변화와 실제 의미 추출의 개선을 따로 측정한다.

### 17.5 통계적 한계

서로 독립이고 대표성 있는 Bernoulli 표본 `n`개에서 오류 0건일 때, 오류율의 단측 95% 상한은 `1 - 0.05^(1/n)`이다. 가령 n=22라면 약 12.7%다. **현재 22개는 작성자 선택·상관된 합성 사례이므로 이 값을 실제 PR 오류율의 신뢰구간으로 사용할 수 없다.** 식은 표본 설계가 갖춰져도 ‘0건 관측 = 0% 오류’가 아님을 설명한다.

실제 평가는 저장소 단위 군집 상관을 고려한다. 표본 크기·추출 규칙·제외 규칙·주요 지표를 먼저 정하고, repository-level bootstrap이나 계층별 구간 등 적합한 방법을 선택한다. 사람 라벨 불일치·미지원 정답·실패한 실행도 결과 표에 남긴다.

## 18. 테스트·모델 검사·반례 계획

### 18.1 시험 계층

| 계층 | 검사 대상 | 실패 시 의미 |
|---|---|---|
| 타입·입력 계약 | enum, 수치, 누락, 중복, 경로, schema | 수락 도메인이 명세와 다름 |
| 순수 의미 단위 | 사실 차이, 적용 조건, 논리 결합 | 알고리즘 또는 명세 오류 |
| 속성·변형 | 순서·주석·독립 변화·정보 손실 | 표면 표현이나 무관한 사실에 의존 |
| 독립 oracle | framework/TypeScript 생성·HTTP 통제 | 실제 지원 의미와 불일치 |
| 실제 Git 수집 | base/head·rename·전체 문서·미추적 정책 | adapter와 core 연결 오류 |
| 진입점 동등성 | CLI/MCP/Desktop/Action | 전달·직렬화·보고 차이 |
| 패키지/OS | 설치 아티팩트·오프라인·parser 해시 | 소스 검증이 배포물에 이어지지 않음 |
| 운영 장애 | 시간 제한·취소·중복·crash·storage failure | 잘못된 완료·복구·신뢰 상태 |

### 18.2 변형 성질과 전제

| 성질 | 전제 | 기대 |
|---|---|---|
| 배열 순서 불변 | 집합 의미의 파일·독립 그룹 | 판정과 의미 해시 동일 |
| 주석·공백 불변 | 언어 의미와 참조·문자열 값이 동일 | E02처럼 바인딩 판정 변화 없음 |
| 무관한 사실 추가 | import·scope·runtime side effect가 없음이 확인 | 기존 의무 소실 없음 |
| 정보 손실 | 원문을 누락·잘린 patch로 바꿈 | 새 근거 없이 더 강한 확정 주장 금지 |
| rename 보존 | 모듈 해석·정책 selector가 동일 | 계약 사실 보존, 출처만 갱신 |
| 알려진 위반 보존 | AND에 unknown 형제를 추가 | 확정 위반 유지, coverage는 부분일 수 있음 |
| 충분한 대안 보존 | OR에 검증된 참 대안이 있음 | 다른 unknown 대안으로 참 증거 취소 금지 |
| 숫자 표현 도메인 | 지정한 수치 정책 | 지수 오버플로·비유한 값 일관 거부 |
| replay | 의미 입력·시각·엔진·profile 동일 | 비의미 필드 제외 결과 동일 |

모든 추가 코드가 ‘무관’하거나 모든 rename이 의미 보존인 것은 아니다. 정책이 경로를 기준으로 하거나 프레임워크가 import 위치를 사용하면 전제가 깨진다. 변형 시험에는 전제 검증도 필요하다.

### 18.3 추가해야 할 반례 묶음

1. env + route, env + schema, route + schema, 셋 모두, 종류별 변경/불변/unknown의 조합.
2. `import type`의 주석·탭·줄바꿈, named type import, 값 import의 alias, shadowing, type-only 재수출.
3. JSON `1e999`, `-1e999`, `NaN`, duplicate key, surrogate, 깊이·노드·bytes 경계, YAML alias/merge/ref.
4. route 이동·삭제·중복, 같은 경로의 서비스 분리, 모델 이름만 변경, 다른 파일 모델 변경, 미변경 소비자.
5. 파일별 정확 사실과 다른 파일 unknown 혼합, 기존 전역 키의 다른 파일 새 사용, 문자열 속 가짜 env 접근.
6. 정책 mode 전환, source scope 축소, glob/명시 경로 대체, trusted policy 읽기 실패, 만료 경계.
7. 파일 수 폭증·parser hang·메모리 제한·worker 강제 종료, 취소 직후 완료, 결과 게시 중 새 head.
8. 같은 입력으로 CLI/MCP/Desktop/Action을 실행하고 시간·run ID를 제외한 IR 비교.

### 18.4 실패를 데이터로 남긴다

기대값을 실패 뒤에 바꾸는 경우에는 원래 기대, 변경 이유, 승인, 새 fixture 버전을 모두 남긴다. 출력 이름에는 실행 ID 또는 digest를 포함하고 기존 결과를 덮어쓰지 않는다. 빈 suite는 성공률 100%로 처리하지 않고 입력 오류로 거부한다. oracle 설치 실패·skip은 통과와 분리한다.

### 18.5 이번 문서의 유한 모델 검사

[check_model.py](../assessment/enterprise-logical-design-2026-10-07/check_model.py)를 실행한 [결과](../assessment/enterprise-logical-design-2026-10-07/model-check.json)는 다음과 같다.

| 검사 | 실행 수 | 관측 |
|---|---|---|
| 현재 `combine`의 두 피연산자 AND/OR 진리표 | 18 | 명세와 일치 |
| 교환·결합·드모르간·분배 법칙의 유한 대입 | 216 | 반례 없음 |
| 6.3절 적용 조건/요구 조건 조합 | 9 | 표와 일치 |
| 사실 3개 우주에서 `L ⊆ F ⊆ U`인 모든 전후 조합 | 4,096 | 5.3절 추가·제거 하한/상한 포함 관계 성립 |
| 위 조합 중 no-delta 충분조건 해당 | 8 | 모두 전후 사실 동일 |

이 검사는 수식·표의 작은 모델을 실제 계산했다는 근거다. 하한·상한 모델이 현재 분석기에 구현됐다는 뜻이 아니며, parser 건전성·범위 완전성·복잡한 evidence coverage·시간적 진행성을 검증하지 않는다. TLA+ 모델 검사는 아직 계획이다. 테스트 개수를 기존 제품 회귀 수에 합산하지 않는다.

## 19. 배포·호환·최종 사용 검증

### 19.1 점진적 전환

1. 기존 `auto`의 의미와 결과 형식을 고정한다.
2. 새 프로필을 shadow mode로 실행해 기존 결과와 차이를 기록한다.
3. 차이를 ‘위반 탐지 향상’, ‘새 보류’, ‘오탐’, ‘정책 의미 변경’, ‘입력 문제’로 검토한다.
4. 팀 정책 소유자가 explicit profile과 unknown 조치를 선택한다.
5. 프로필·결과 schema 변경을 버전으로 고정해 배포한다.
6. 되돌릴 때 이전 정책·검증기·영수증을 함께 사용하고 새 결과를 옛 형식으로 오해하지 않게 한다.

현재 `auto-strict`는 E01 때문에 이름만으로 엄격성을 보장할 수 없다. 해당 결함이 해결되기 전에는 혼합 계약을 explicit group으로 지정하는 우회만 제한적으로 안내한다. E02가 남은 Express 프로필은 독립적인 배포 차단의 유일 근거로 채택하지 않는다.

### 19.2 출시 수락 조건

| Gate | 완료 기준 | 필수 증거 |
|---|---|---|
| 의미 | E01/E02/E03 정상·반례 통제, INV-01–12 해당 시험 | 고정 입력, 기대값, 결과·코드 digest |
| 회귀 | 전체 Python/React/타입/린트 및 기존 suite | 최종 소스에 대응하는 로그, skip 사유 |
| 독립 대조 | 선언한 프레임워크 버전의 oracle | engine/profile/parser 버전과 대조 결과 |
| 원격 | 같은 commit의 CI 성공 | run ID·attempt·head SHA·실제 내려받은 결과 JSON |
| 패키지 | 배포할 artifact의 offline 계약 분석·UI·오류 경로 | artifact SHA, OS/arch, 빈 cache, 차단 증거 |
| provenance | source → build → installer → receipt 연결 | 신뢰 빌더·서명/해시·정책 바인딩 검증 |
| 운영 | 취소·timeout·역순·복구·승인 만료 | 장애 주입 결과와 담당자 절차 |

‘설치 프로세스가 살아 있음’, ‘소스 환경에서 sys.frozen만 흉내 냄’, ‘CI 초록색’은 각각 설치된 앱이 해당 입력을 분석했다는 완전한 근거가 아니다. 실제 설치본을 내려받아 새 cache와 네트워크 차단 조건에서 실행하고 결과 JSON을 소스·아티팩트와 연결해야 한다.

### 19.3 릴리스 중단 조건

선언한 지원 범위에서 거짓 verified 또는 누락된 필수 의무가 재현되면 해당 프로필의 강제 적용 확대를 중단한다. 결과의 head/policy/engine 바인딩 오류, 비신뢰 코드 실행, 입력 오류의 pass 변환도 중단 사유다. 기존 통과 개수가 많다는 이유로 상쇄하지 않는다. 보류 증가만으로 곧바로 출시 실패로 판단하지는 않되, 사용성 영향과 원인을 검토한다.

## 20. 개발 작업표: 우선순위·수정 위치·완료 조건

P0는 이 문서에서 ‘신뢰하는 강제 검사로 확대하기 전 해결’이라는 의미다. 실제 발생 빈도나 금전 손실을 측정한 심각도 점수는 아니다. 공수는 근거가 없으므로 날짜를 임의 약속하지 않고 S(국소), M(여러 계층), L(새 모델/운영)로만 표시한다.

| ID | 우선·규모 | 개발 내용 | 시작 위치 | 수락 조건 |
|---|---|---|---|---|
| W01 | P0/S→M | 혼합 계약의 의무 누락 방지 | `evaluation/routes.py`, `evaluator.py` | E01 3통제 및 혼합 변경/불변/unknown에서 다른 의무 소실 0 |
| W02 | P0/S | type-only 의미를 AST로 판별 | `adapters/ast/express_routes.py` | 값 import만 런타임 근거, 주석·탭·줄바꿈 변형 일치, TS 제거 대조 |
| W03 | P1/S | 유한 수치 도메인·진단 통일 | `evaluation/openapi_document.py`, `adapters/docs/structured.py` | E03·음수 오버플로·경계·nested·모든 진입점 동일 |
| W04 | P1/M | 시각과 승인 context 주입 | `evaluation/evaluator.py`, entrypoint adapters | 고정 시각 replay, 만료 경계, 과거 결과와 현재 허가 분리 |
| W05 | P1/M | 타입화한 사실 결과·이유 코드 | `content_result.py`, `analysis_session.py`, models | exact/unknown/absent/limited 혼동 불가, 기존 결과 호환 |
| W06 | P1/M | 계약 프로필 registry와 적용성 | `routes.py`, `contracts.py`, policy schema | 자동 의무 목록과 explicit 그룹 의미 대조, 미탐지 종류 진단 |
| W07 | P1/M | 스냅샷·입력 manifest 강화 | Git/GitHub/docs adapters, `inspection.py` | 같은 버전의 코드·문서, missing/unavailable 구분, 순서 규약 |
| W08 | P1/M | 증거 회로·판정/coverage 분리 | `content_result.py`, result model, reporters | 세 값 전수표·중첩·직렬화·UI projection 동일 |
| W09 | P1/M | 신뢰 실행과 후보 테스트 분리 | workflows, policy guard, packaging | 후보가 checker/policy를 바꿔도 trusted 검사 우회 불가 |
| W10 | P1/M | 독립 평가 프로토콜·증거 인덱스 | `audit_auto_contracts.py`, contracts, assessment | 빈 suite 거부, 각 축 분모·skip·해시·최종 로그 자동 확인 |
| W11 | P2/L | 영향 closure·전후 의존 그래프 | source scope, static routers, API/env analyzers | 미변경 소비자 영향·삭제 간선·순환·한도·미지원 명시 |
| W12 | P2/M | 전역 자원 예산·worker 격리 | inspection application, parser boundary | timeout/메모리/출력 한도에서 명시 종결·부분 coverage |
| W13 | P2/M | typed trigger와 정책 migration | intensity, policy validator/guard | legacy 의미 보존, 종류와 심각도 독립, shadow 차이 보고 |
| W14 | P2/L | schema 의미·호환성 프로필 확장 | API schema + OpenAPI decoder | request/response 방향성·status/media/ref별 독립 oracle |
| W15 | P2/M | 재현 영수증·게시 최신성·캐시 키 | execution, history, publishers | head 역전 거부, 엔진/profile 변경 시 캐시 무효, idempotency |
| W16 | P2/M | artifact 실사용·OS 대조 반복 가능화 | packaging/workflows | 최종 아티팩트 hash와 offline JSON 다운로드·검증 |
| W17 | 조건부/L | 조직 서비스 운영 | 별도 service boundary | tenant 격리·RBAC·quota·감사·보존·복구 요구가 실제 확인됨 |

### 20.1 의존 순서

```text
W01 + W02 + W03 → 안전한 현재 프로필
W04 + W05 → W06 + W08
W07 + W09 → W15 + W16
W10은 모든 단계의 수락 증거에 적용
W06 + W07 → W11 → W14
W07 + W12 + W15 → 필요할 때만 W17
```

W01을 작은 임시 분기 하나로 끝내지 않는다. 단기 혼합 감지 보수화는 허용하지만 W06의 의무 집합 모델로 이어져야 한다. W02 역시 접두어 정규식만 더 복잡하게 만들면 같은 계열의 구멍이 남는다.

### 20.2 가장 먼저 제출할 변경 묶음

1. **정확성 묶음:** W01–03. 원래 실패 fixture를 고정하고 정상 통제를 먼저 작성한다. core + 실제 Git + oracle의 세 수준을 연결한다.
2. **의미 계약 묶음:** W04–06·W08. 호환 adapter를 두고 타입·시간·증거를 분리한다. UI와 기존 출력에 불필요한 일괄 변경을 만들지 않는다.
3. **재현·신뢰 묶음:** W07·W09·W10·W15·W16. 고정 검증기, manifest, 최종 artifact까지 증거를 연결한다.
4. **범위 확대 묶음:** W11–14. holdout과 profile 명세를 먼저 준비하고 실제 수요가 확인된 언어·계약부터 확장한다.

각 묶음은 별도 리뷰 가능한 변경으로 유지한다. 현재 미커밋 변경이 많으므로 구현에 들어가기 전 적용 기준의 파일 해시와 사용자 변경을 보존한다. 사용자가 삭제한 과거 문서 두 개를 무단 복구하지 않는다.

## 21. 주요 설계 선택과 기각한 대안

| ADR | 선택 | 기각한 대안 | 이유·비용 |
|---|---|---|---|
| A01 | 명제·coverage·action 분리 | pass=정확함 | 한계 표시와 운영 제어를 동시에 유지, 출력 복잡도 증가 |
| A02 | 명시 프로필 + 의무 집합 | 첫 탐지 종류 하나 선택 | E01 재발 방지, 혼합 문서 routing 설계 필요 |
| A03 | 미지원은 scoped unknown | 휴리스틱을 verified로 승격 | 오판 확정을 줄임, 초기 보류 증가 가능 |
| A04 | 사실 하한·상한·closure | empty set만 반환 | 부재 입증을 추적, 모델·메모리 비용 증가 |
| A05 | 순수 코어·불변 입력 | UI별 자체 판정 | 진입점 의미 통일, adapter migration 필요 |
| A06 | 작은 모듈형 앱 + 필요 시 worker | 초기부터 다수 서비스 | 배포·복구 복잡도 억제, 향후 격리 경계는 유지 |
| A07 | 신뢰 엔진과 후보 테스트 병행 | 후보의 자기 검사만 승인 근거 | 자기 검증 순환 완화, CI 시간·관리 비용 증가 |
| A08 | 구조화 증거와 사람 승인 | 모델 다수결을 최종 진실로 사용 | 검증 가능한 책임 경계, 인간 검토 비용 발생 |
| A09 | 원래 suite 보존 + 별도 holdout | 경계 점수만 높이기 위한 기대값 변경 | 개선 비교의 정직성 유지, 낮은 과거 점수도 남음 |
| A10 | profile/version별 확장 | 범용 API 정확성 보장 | 명제 크기를 통제, 기능 홍보 범위를 제한 |

일률적으로 fail하는 정책은 강제 차단 수를 늘리지만 사실 이해를 개선하지 않는다. 일률적으로 unknown을 반환하는 분석기도 거짓 확정을 줄일 수 있지만 제품 유용성이 낮다. 목표는 **동일한 오판 위험 수준에서 근거 있는 판단 범위를 넓히는 것**이며, 위험과 coverage를 함께 보고 선택한다.

## 22. 완료 판단과 남는 불확실성

이 설계의 구현 완료는 ‘모든 코드에 오류가 없다’는 선언이 아니다. 선언한 프로필과 버전에서 수락 조건·불변식·반례·정상 통제·독립 대조·배포 검증을 만족하고, 미지원 범위를 사용자가 확인할 수 있는 상태다.

현재 아직 확인되지 않은 것은 실제 팀 PR 분포에서의 오류율, 사용자 조치 시간, 장기 부하·대형 저장소 성능, 조직 환경의 권한·보존 요구, 최신 변경의 원격 CI와 설치본 동작이다. 이번에는 전체 1,228/125 테스트를 다시 돌리지 않았고, 기존 증거와 파일 해시를 재확인한 뒤 좁은 새 반례를 실행했다.

새 반례를 찾았다고 이전 22개 통과 결과가 거짓이 되는 것은 아니다. 그 결과가 말할 수 있는 범위가 22개 작성자 사례에 한정된다는 뜻이다. 마찬가지로 이 문서의 수학적 형식과 참고 문헌이 구현을 자동으로 정확하게 만들지는 않는다. 코드 변경마다 가정·증거·반례를 다시 연결해야 한다.

## 23. 재현 방법·추적 인덱스·참고 문헌

### 23.1 이번 재현 실행

저장소 루트에서 프로젝트 Python 의존성과 `desktop-ui/node_modules/typescript`가 준비된 환경으로 실행한다. Node/TypeScript가 없으면 import 제거 oracle을 완전 재현했다고 주장하지 않는다. 출력 파일은 새 경로여야 한다.

```sh
python docs/assessment/enterprise-logical-design-2026-10-07/reproduce.py \
  --out /tmp/drift-gate-enterprise-probes-new.json
python docs/assessment/enterprise-logical-design-2026-10-07/check_model.py \
  --out /tmp/drift-gate-enterprise-model-new.json
```

macOS에서 사용한 Python은 3.11.15, TypeScript는 5.9.3이다. 실제 환경 정보·원시 결과·최종 재현기 SHA는 [결과 파일](../assessment/enterprise-logical-design-2026-10-07/results-final.json)에 있다. 재현기는 파일을 수정하는 대신 임시 Git 저장소를 만들고, 작성한 TypeScript 통제를 변환하며, 현재 운영 파일과 이전 근거 해시를 읽는다. 향후 운영 코드를 수정하면 이번 결함 관측값과 달라지는 것이 정상이고, 새 결과로 개선을 비교한다.

### 23.2 주장 → 코드 → 증거 → 작업

| 주장/설계 | 핵심 코드 | 근거 | 후속 |
|---|---|---|---|
| 자동 분류 의무 누락 | [routes.py](../../drift_gate/core/evaluation/routes.py) | results-final의 mixed_contract_dispatch | W01/W06 |
| type-only 주석 우회 | [express_routes.py](../../drift_gate/adapters/ast/express_routes.py) | express_type_imports + TS output | W02 |
| 수치 도메인 누락 | [openapi_document.py](../../drift_gate/core/evaluation/openapi_document.py) | json_numeric_domain | W03 |
| hidden clock | [evaluator.py](../../drift_gate/core/evaluation/evaluator.py) | date.today 코드 확인 | W04 |
| 논리 결합 | [content_result.py](../../drift_gate/core/evaluation/content_result.py) | 기존 논리 계약 시험, 이번 목표 진리표 | W05/W08 |
| 전역 환경 범위의 명세 필요 | [environment.py](../../drift_gate/core/evaluation/environment.py) | 코드 확인, 전역 unknown 반례는 미실행 | W11 |
| 강도와 종류의 혼합 | [intensity.py](../../drift_gate/core/classification/intensity.py) | INTENSITY_ORDER 코드 확인 | W13 |
| 실행 입력 해시 | [inspection.py](../../drift_gate/adapters/inspection.py) | execution_metadata, 이전 영수증 일치 | W07/W15 |
| 평가 독립성 제한 | [audit_auto_contracts.py](../../scripts/audit_auto_contracts.py) | facts에서 운영 추출기 재사용 | W10 |
| 저장·복구 연속성 | [기존 아키텍처](target-architecture-v2-2026-10-06.md) | 기존 계약 계승, 이번 재검증 아님 | W15 |

### 23.3 외부 1차 자료

다음 자료는 설계 원칙과 표준 의미를 확인하기 위한 것이다. 그 문헌이 현재 Drift Gate 구현을 평가하거나 승인한 것은 아니다. 열람일: 2026-10-07.

1. [Cousot & Cousot (1977), Abstract interpretation](https://www.di.ens.fr/~cousot/COUSOTpapers/POPL77.shtml): 보수적 의미 근사의 배경. 5–6절의 제품 모델·정리는 이 문서의 설계다.
2. [Lamport, Specifying Systems](https://lamport.azurewebsites.net/tla/book.html): 상태 기반 명세와 모델 검사 접근. 이번에 TLA+ 검사를 실행한 것은 아니다.
3. [RFC 8785, JSON Canonicalization Scheme](https://www.rfc-editor.org/info/rfc8785/): 언어 간 반복 가능한 직렬화 선택의 참고. 현재 표준 적합성을 인증하지 않는다.
4. [OpenAPI Specification 3.1.2](https://spec.openapis.org/oas/v3.1.2.html): 선택한 버전의 API 기술 의미. 최신 모든 버전 지원을 주장하지 않는다.
5. [SLSA 1.2, Verifying artifacts](https://slsa.dev/spec/v1.2/verifying-artifacts): digest·신뢰 주체·기대 빌드 조건의 검증. 논리적 정확성 평가와 별개다.
6. [in-toto Statement v1](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md): 아티팩트와 진술을 연결하는 형식.
7. [GitHub Actions secure use](https://docs.github.com/en/actions/reference/security/secure-use): 비신뢰 입력과 권한 있는 실행 분리.
8. [TypeScript 3.8, Type-Only Imports and Export](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-3-8.html): 타입 전용 import의 런타임 제거 의미. 이번 실행 oracle 버전은 5.9.3이다.
