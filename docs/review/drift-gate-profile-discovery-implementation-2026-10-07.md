# 심화 설계 S1-b: profile registry와 discovery 구현

2026-10-07 · `ver2`, `d262ec2` 위 미커밋 작업 트리

[심화 설계](../architecture/drift-gate-enterprise-detailed-design-2026-10-07.md)의 S1-b를 구현했다. [S1-a](drift-gate-typed-facts-implementation-2026-10-07.md)에서 도입한 사실 타입 위에 계약별 분석 범위와 후보 탐지를 연결했다. 전체 S1이나 엔터프라이즈 설계 전체의 완료 보고서는 아니다. 기존 편집과 문서 삭제를 보존했으며 커밋·푸시하지 않았다.

## 운영 코드의 변경

| 파일 | 변경과 목적 |
|---|---|
| [profiles.py](../../drift_gate/core/contracts/profiles.py) | 불변 `ContractProfile`·`ProfileRegistry`. 프로필 ID/버전, 계약 종류, 언어, 분석 경계와 입력 요구를 명시한다. 중복 참조와 모호한 언어/계약 선택을 거부한다. |
| [discovery.py](../../drift_gate/core/contracts/discovery.py) | 선택 파일 × 요청 계약의 모든 domain을 보존한다. 후보 활성화와 open/closed를 분리하며 누락된 domain을 생성자에서 거부한다. |
| [routes.py](../../drift_gate/core/evaluation/routes.py) | 실제 `auto-strict` 선택 경로가 discovery를 호출하고 기존 호환 힌트를 소비한다. 이전 판정 계약을 유지하며 새로운 전체 coverage를 기존 verified로 승격하지 않는다. |
| [facts.py](../../drift_gate/core/models/facts.py) | `API_RESPONSE` 종류를 추가하되 응답 구조를 route/env identity 집합으로 표현하는 잘못된 사용은 거부한다. 전용 응답 fact 모델은 후속 단계다. |
| [test_profile_discovery.py](../../drift_gate/tests/test_profile_discovery.py) | 신규 회귀 76개. 일반 CI의 전체 수집과 [Desktop 명시 목록](../../.github/workflows/desktop-build.yml)에 포함한다. |

새 코어는 소스 실행·파일 읽기·네트워크 접속을 하지 않는다. Express 등록 사실은 adapter가 제공하며 코어는 그 구조와 불완전 상태를 검사한다. 분석 세션의 캐시는 분석 종류와 소스 내용으로 구분하고 파일별 domain의 범위를 재사용하지 않는다.

## 판단 규칙과 직접 확인한 사례

후보가 없다는 것과 계약이 없음을 확인했다는 것을 구분한다. 분석할 수 없는 domain은 후보가 없어도 open으로 남는다. 후보가 있다는 것도 코드 변화나 문서 갱신 의무가 확정됐다는 뜻은 아니다.

| 사례 | 실제 결과와 의미 |
|---|---|
| Python API + literal env | route와 env 후보를 동시에 보존한다. 하나가 다른 하나를 지우지 않는다. |
| 명시 `response_model` | route와 response 후보를 별도로 보존한다. 지원하는 primitive 응답 부분집합만 닫힌다. |
| `list[int]` 응답 필드 | route domain은 닫히고 response domain은 open이다. 국소 미지원이 다른 domain의 관찰까지 지우지 않는다. |
| 동적 env getter | env domain이 open이다. 키를 얻지 못한 것을 확정 공집합으로 취급하지 않는다. |
| 외부 모듈의 app 등록 | route와 response domain이 open이다. 명시 response 힌트가 없어도 미확인 영역을 남긴다. |
| Go 입력 | 세 domain 모두 profile 미지원으로 open이다. 빈 후보를 완전성으로 해석하지 않는다. |
| Express 전체 세 계약 요청 | route만 닫히며 env/response는 open이다. |
| Express 명시 route-only 요청 | 그 요청 부분집합에서만 닫힌다. 서비스 전체나 다른 계약의 인증이 아니다. |
| 빈 파일 선택 | `complete_within_selection=false`. 빈 입력을 성공 인증으로 바꾸지 않는다. |

위 9개는 [실제 함수 실행 결과](../assessment/profile-discovery-implementation-2026-10-07/discovery-examples.json)에 입력·기대 상태·관찰 상태를 함께 기록했다. [재현 스크립트](../assessment/profile-discovery-implementation-2026-10-07/probe_discovery.py)는 새 출력 경로를 요구하고 기존 파일을 덮어쓰지 않는다. 저자가 만든 비맹검 사례이며 실제 PR 정확도 평가가 아니다.

추가 회귀는 미사용 import·주석·문자열, 불완전 전후 입력, 잘못된 adapter identity, 분석기가 설치되지 않은 profile 선언, 빠진 파일/계약 domain, 중복 경로와 입력 순서 변경을 검사한다.

## 호환성과 검증 결과

| 검사 | 결과 | 근거 |
|---|---|---|
| Python 전체 | **1,431 통과, skip 0** | [로그](../assessment/profile-discovery-implementation-2026-10-07/python-full.log) |
| 집중 회귀 | **251 통과** | [최종 로그](../assessment/profile-discovery-implementation-2026-10-07/targeted-final.log). profile/enterprise/typed-facts/auto-development 4개 파일 |
| Python 정적 검사 E9,F | 통과 | [로그](../assessment/profile-discovery-implementation-2026-10-07/ruff.log) |
| 고정 기능 fixture | **21/21** | [결과](../assessment/profile-discovery-implementation-2026-10-07/fixed-evaluation.json) |
| Python/Git v2 | 네 축 각각 **14/14** | [결과](../assessment/profile-discovery-implementation-2026-10-07/python-git.json) |
| Express/Git v1 | 네 축 각각 **8/8** | [결과](../assessment/profile-discovery-implementation-2026-10-07/express-git.json) |
| 이전 22개 의미 사례 | actual·입력 digest·suite hash 변경 없음 | [비교 및 해시 기록](../assessment/profile-discovery-implementation-2026-10-07/verification.json) |
| 자체 Drift Gate | **pass / unverified** | [결과](../assessment/profile-discovery-implementation-2026-10-07/self-check.json), [입력 메타데이터](../assessment/profile-discovery-implementation-2026-10-07/self-check-inputs.json) |

고정 Git 평가의 네 축은 facts/decision/verification/gate다. 실행 ID·시각·소요 시간의 동일성을 주장하지 않는다. 과거 suite와 결과 파일을 수정하지 않았고 보존 입력 5개의 해시를 대조했다. 기존 `auto` 경계 평가 1/8을 이번 단계에서 다시 실행하거나 개선했다고 보고하지 않는다.

전체 Python 실행에는 기존 Qt/Desktop 회귀와 FastAPI/Express oracle이 포함된다. Express의 로컬 HTTP 시험을 허용한 환경에서 실행했다. UI 소스가 이번 단계에서 바뀌지 않아 React·tsc는 다시 실행하지 않았다.

자체 게이트는 HEAD 대비 tracked 변경에 명시 수집한 untracked source/test 34개를 합친 총81개를 사용했다. Git index를 바꾸지 않았으며 미분류 운영 경로는0이다. 이 입력에는 이전 턴들의 변경도 포함된다. 자체 정책 pass는 요구된 문서 변경의 충족이며 코드 의미 전체의 정확성 보장이 아니다. 정책이 경로 의무를 사용하므로 verification은 unverified다.

## 아직 보장하지 않는 범위

현재 프로필은 Python env literal, 기존 FastAPI 등록, 명시 primitive response_model, Express 등록이라는 제한된 부분집합을 설명한다. 명시 response_model이 없는 임의 응답 본문의 스키마를 추론하지 않는다. metadata만 추가한다고 분석기 구현이나 새 버전 지원이 생기지 않는다.

`closed`와 `complete_within_selection`은 선택 모듈·프로필 부분집합에 대한 기존 분석기의 주장이다. 서비스 전체 탐지, imported consumer의 dependency closure, parser 건전성의 수학적 증명, 독립적인 원문 인증이 아니다. 결과에 `service_scope_certified=false`를 명시한다. 근거 참조는 아직 opaque label이며 인증된 manifest 증명이 아니다. 추가/삭제 파일의 부재도 legacy 입력의 선언이다.

이번 단계는 호환 연결이다. discovery에서 모든 domain을 보존하지만 기존 gate는 여전히 호환 selector를 사용한다. 따라서 Express의 legacy route 판정이 verified여도 전체 세 계약의 discovery coverage는 open일 수 있다. 두 결과를 하나의 완전성 점수로 합치지 않는다.

S1-c의 전체 적용 의무 구성·문서 배정·필수 open guard, S1-d의 proof DAG, S1-e의 새 결과 projection은 남아 있다. profile/parser/engine digest 인증과 서비스 dependency closure도 후속 과제다. 새 원격 CI·세 플랫폼 설치본·실사용 PC·독립 holdout 검증은 이번에 수행하지 않았다.

## 다음 단계

S1-c에서 계약 후보를 실제 변화와 구분하고, 모든 적용 계약의 의무를 각각 구성한다. 문서의 계약 종류와 배정 관계를 명시하며, 후보가 없어도 남아 있는 open domain의 필수 guard를 유지한다. 이미 확인한 위반을 다른 영역의 unknown이 덮어쓰지 않게 한다. 이후 proof DAG와 결과 projection을 연결한 뒤 기본 gate 전환 여부를 검증한다.
