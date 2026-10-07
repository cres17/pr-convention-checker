# 심화 논리 설계의 근거 묶음

대상 문서: [Drift Gate 논리 구조·검증 체계·운영 아키텍처 심화 설계](../../architecture/drift-gate-enterprise-logical-design-2026-10-07.md)

2026-10-07의 `d262ec2` 위 미커밋 작업 트리를 조사했다. 운영 코드는 이번 작성에서 수정하지 않았다. 전체 제품 테스트를 다시 실행한 보고서가 아니다.

| 파일 | 역할 |
|---|---|
| [reproduce.py](reproduce.py) | 세 결함 가설을 정상 통제와 함께 실행. 실제 임시 Git 수집, 타입스크립트 변환, JSON 파싱 |
| [results-final.json](results-final.json) | 최종 프로브 결과, 입력, 제품 보고서, TypeScript 변환 출력, 이전 영수증 해시 대조 |
| [results.json](results.json) | 앞선 탐색 실행. 최종본은 Express 실제 Git gate 관측을 추가했다. 최종 재현기는 results-final의 해시로 식별 |
| [check_model.py](check_model.py) | 논리표와 제안한 사실 하한·상한 모델의 유한 검사 |
| [model-check.json](model-check.json) | 18 진리표·216 법칙 대입·9 조건부·4,096 전후 사실 조합의 관측 |

확인한 결함:

- E01: 변경 없는 env 접근이 있는 Python API에서 `auto-strict`가 route 변경을 놓침. 명시 `api-routes` 및 env 접근 제거를 통제로 비교.
- E02: 주석이 삽입된 `import type`을 값 import로 인식. TypeScript 5.9.3 출력에서는 import가 제거되지만 제품은 `pass/verified`. 일반 type-only는 unknown, 값 import는 정상 인정.
- E03: JSON 확장 필드의 `1e999`를 무한대 float로 수락. NaN 거부, 유한 숫자 수락을 통제로 비교. 실제 gate 오판을 입증한 사례는 아님.

`reproduce.py`는 관측 수집기이므로 종료 0이 제품 결함 해결을 뜻하지 않는다. `check_model.py`는 모델 성질이 깨지면 종료 1을 반환한다. 두 스크립트 모두 기존 출력 파일을 덮어쓰지 않는다.

이전 검증 영수증의 소스 115개, 입력 5개, 테스트 44개, 근거 38개가 모두 현재 파일과 일치했다. 해시 일치는 해당 목록에 한정되며 독립 서명이나 전체 저장소 감사가 아니다.

재현 명령과 지원 환경은 상위 설계 문서 23절에 있다. 대상 저장소의 애플리케이션을 import하거나 실행하지 않는다. 작성한 합성 TypeScript 문자열만 컴파일 변환하며, HTTP 동작·전체 타입 검사를 수행하지 않는다. 최신 원격 CI·설치본·Windows/Linux 검증과 사람의 맹검 평가는 이번 범위에 없다.
