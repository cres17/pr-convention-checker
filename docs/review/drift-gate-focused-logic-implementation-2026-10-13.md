# 집중 논리 개선: 구현과 검증

2026-10-13 · 기준 HEAD `a76306f5636b64daa617e3f90158a79785e07ad1` + 미커밋 작업 트리

[개선 계획](../architecture/drift-gate-focused-logic-plan-2026-10-13.md)의 P1~P4를 수정하고,
Python 환경 키·API 경로의 선택형 프리셋과 실제 Git/CLI 재현을 추가했다.
전체 계획을 완료한 상태는 아니다. 외부 파일럿·서비스 전체 소유 범위 인증·새 원격 배포 검증은 남아 있다.

## 현재 반례의 전후 결과

같은 [기존 재현 스크립트](../assessment/portfolio-review-2026-10-13/probes.py)를 다시 실행했다.
원래 입력·결과는 유지하고 새 출력은 [probes-after.json](../assessment/focused-logic-2026-10-13/probes-after.json)에 저장했다.

| 항목 | 이전 관찰 | 수정 후 관찰 |
|---|---|---|
| 겹치는 enum의 oneOf에서 1/1.0을 다르게 인식 | T·gate pass | F·gate fail |
| integer enum의 1.0을 가능한 값에서 제거 | T·gate pass | F·gate fail |
| 빈 객체만 허용하는 동등 schema를 무한 집합으로 판단 | F·gate fail | T·gate pass |
| 정책 두 규칙 중 기대값에 없는 위반 규칙 | 평가 단위 1개 | 평가 단위 2개, 빠진 기대값은 null |
| 정답 not-applicable에 verified/violated를 낸 합성 입력 | false_verified 0/1 | false_verified 1/1 |

마지막 행은 지표 API의 합성 입력 시험이다. 실제 사람 정답이나 제품 정확도 100%를 뜻하지 않는다.

## 운영 코드 변경

### JSON 값과 포함 관계

- `json_values.py`에 숫자 동등성·정수 판정·lossless decimal decoding을 모았다.
  1과 1.0, 중첩 값의 같은 숫자는 같고 bool은 숫자와 다르다.
- enum canonicalization과 oneOf 겹침 판정이 같은 의미론을 사용한다.
  Decimal context를 낮춰도 숫자를 반올림하지 않으며 큰 지수를 풀어 거대한 문자열로 만들지 않는다.
- NaN·Infinity·중복 JSON key는 정상 호환 판정에 사용하지 않는다.
- 닫힌 유한 객체와 빈 항목 스키마 배열의 가능한 값 전체를 비교한다.
  열거 상한을 넘는 객체·미해결 재귀는 열거 인증을 잃는다. 이를 빈 집합이나 위반으로 처리하지 않는다.
- 불가능한 필수 속성·추가 속성 때문에 생기는 빈 언어를 고려하고, number/integer allOf의 타입 교집합을 바로잡았다.

기존 일반·composite 대조에 숫자 표현, bool, 빈 객체·배열, enum, oneOf, allOf의 고정 경계 격자를 추가했다.
지원 범위의 명확한 T/F를 유지했다. 샘플에서 반례를 못 찾는 것으로 일반적인 포함 관계를 증명했다고 주장하지 않는다.

### 평가 분모와 판정 모델

- 기대값 대신 정책의 모든 규칙을 단위·검토 packet으로 만든다.
- 기대값 없는 규칙의 실제 위반도 결과에 남기며 미라벨·미기대 수를 명시한다.
- holdout은 제품 `RuleDecision.decision/verification`을 그대로 사용한다. gate status의 별도 변환을 제거했다.
  warn 정책이 허용한 undetermined를 satisfied로 잘못 해석하는 경로도 없앴다.
- `holdout-metrics-v2`에 모든 결정×label 행렬을 넣고, not-applicable과의 불일치를 확정 오판에 포함한다.
  undecidable은 평가 불가로 분리하며 미라벨·오류·생략을 숨기지 않는다.
- 중복 사례·단위·label과 잘못된 사례/항목 연결을 거부한다. CLI는 지표 입력 오류도 공통 오류 계약으로 반환한다.

지표 v1과 v2는 정의가 다르다. 과거 파일을 덮어쓰거나 동일 정의의 수치처럼 직접 비교하지 않는다.
[현재 평가 절차](../ops/holdout-evaluation.md)에 분모·label·이동 계약을 적었다.

### 실제 사용 흐름과 코드 구성

- [focused-python](../focused-python.md) 프리셋은 환경 키와 API 경로를 명시적으로 연결한다.
  기존 정책·기본 프리셋은 유지하며 현재 문서 내용이 맞으면 동반 수정 자체를 강요하지 않는다.
- 결과에 누락 키, 문서에 없는 추가 경로, 문서에 남은 제거 경로를 표시한다.
  읽기 실패와 확인된 파일 부재를 구분한다.
- 동적 입력은 review로 남긴다. `on_unverified: warn`의 CLI 0은 자동 병합 승인과 다르다.
- CLI의 parser·presets·output·holdout_command·org_command를 분리했다.
  이전 help를 대조해 init/setup의 프리셋 추가 외 공개 명령·옵션 변화가 없음을 확인했다.
  기존 entrypoint와 `_build_parser`·POLICY_PRESETS 호환 import를 유지했다.
- 새 숫자 모듈의 mypy strict 검사를 CI 필수 단계로 넣었다.
  전체 core 타입 검사를 강제한 것은 아니며 검사 수명주기 조정과 Desktop 제어 모듈의 추가 분리는 남는다.

## 검증 결과

| 실행 | 관찰 |
|---|---|
| Python 전체 / macOS arm64 / Qt offscreen | 2,064 passed, 6 skipped, 4 warnings, 97.69초 |
| 최종 score 입력 검증 보완 후 관련 회귀 | 65 passed |
| React | 126 passed, 11 files |
| TypeScript | 통과 |
| Ruff E9,F / drift_gate·packaging·scripts | 통과 |
| mypy 1.18.2 strict / JSON 값 의미론 모듈 | 통과 |
| README docs-check | warning_count 0 |
| 실제 Git 객체·정책 pin·CLI·증거 재실행 | 통제 사례 11/11 통과 |
| 체크아웃 밖 설치한 wheel로 같은 흐름 | 통제 사례 11/11 통과 |
| 자체 정책의 변경 파일 투영 검사 | pass, 27개 경로. 새 모듈 포함, 사용자 index 미변경 |

전체 회귀 후 score의 사례/항목 식별자 연결 검증을 마지막으로 보완하고 관련 65개를 다시 통과시켰다.
그 후 운영 코드 수정은 없었다. jsonschema 버전 조회 관련 warning 4개는 기존 독립 validator 시험의 deprecation 경고다.
raw 로그·환경·패키지 영수증은 [근거 폴더](../assessment/focused-logic-2026-10-13/README.md)에 있다.

자체 정책 검사는 원본 저장소 전체 PR 판정이 아니다. 미커밋 새 모듈을 포함하기 위해 수정 경로와 필수 계약 문서를
임시 저장소로 투영했다. Gate pass는 문서 동반 수정 정책 충족이며 동작 정확성 인증이 아니다.
반례·회귀·CLI 실행은 별도 근거다.

wheel의 변경 Python 파일 14개를 작업 트리 bytes와 직접 대조했다.
새 환경의 site-packages import와 `/private/tmp` 실행을 확인했다.
wheel SHA-256: `027676d1db3a2068746522fd5be3d0b4ed88eb6ff4537c0f867d358e1bc021e9`.
wheel은 로컬 확인용이며 네이티브 설치 프로그램이나 공개 릴리스가 아니다.

## 남은 항목

1. 선택 모듈 밖의 경로 소유자·동적 의존성을 포함한 서비스 전체 분석과 엄격 프리셋 연결.
   현재 프리셋은 정책 작성자가 문서·선택 모듈 소유 범위를 맞춰야 한다.
2. 검사 수명주기 조정의 추가 책임 분리, 더 넓은 core 타입 검사, Desktop 제어 분리.
3. 개발에 사용하지 않은 실제 PR과 독립 정답을 이용한 파일럿·검토 부담 측정.
4. 이번 구현 commit의 원격 CI, 세 플랫폼 네이티브 설치본, 공개 다운로드 버전의 갱신.

이번 변경은 커밋·푸시하지 않았다. 기존 사용자 삭제 파일과 이전 검토 산출물은 건드리지 않았다.
SK AX 자기소개서의 6/3/3은 당시의 판단 기록으로 보존하며 이번 통제 시험과 합쳐 성능 수치로 만들지 않는다.
