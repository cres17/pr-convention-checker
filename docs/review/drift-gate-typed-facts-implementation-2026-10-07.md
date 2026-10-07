# 심화 설계 S1-a: typed facts 구현과 호환 검증

2026-10-07 · `ver2`, `d262ec2` 위 미커밋 작업 트리

[심화 구현 설계](../architecture/drift-gate-enterprise-detailed-design-2026-10-07.md)의 첫 변경 묶음 S1-a를 구현했다. 전체 S1 또는 W05–W17을 완료한 보고서가 아니다. 기존 편집과 문서 삭제를 보존했으며 이번 턴에는 커밋·푸시하지 않았다.

## 구현 내용

- [facts.py](../../drift_gate/core/models/facts.py): `ExactFacts`, `BoundedFacts`, `UnknownFacts`, 해당 변화 타입, scope/family/profile/version과 근거 참조를 가진 `FactBasis`를 추가했다. 불변 집합·튜플로 보관하고 구조를 검증한다.
- [delta.py](../../drift_gate/core/contracts/delta.py): 같은 범위·계약·프로필끼리만 변화의 하한/상한을 비교한다. unknown 상한은 top(`None`)이며 공집합으로 바꾸지 않는다. 여러 실행이나 프로필에 걸친 cache·registry는 추가하지 않았다.
- [routes.py](../../drift_gate/core/evaluation/routes.py): 실제 기존 route 검사 경로가 typed facts를 거치게 했다. 지원 불가를 UnknownFacts로 유지하고 기존 `complete_route_delta`는 동일한 set/예외 계약으로 반환한다.
- [environment.py](../../drift_gate/core/evaluation/environment.py): Python 전체 소스의 env 분석을 typed observation으로 연결한다. 기존 집계 알고리즘과 외부 `EnvironmentFacts` 계약은 유지한다. 새 typed observation에서 patch 입력은 항상 unknown이며 휴리스틱 키를 must로 승격하지 않는다.
- [test_typed_facts.py](../../drift_gate/tests/test_typed_facts.py): 새 회귀 54개. 일반 CI의 전체 수집과 [Desktop 명시 목록](../../.github/workflows/desktop-build.yml)에 포함한다.
- [게이트 계약](../contracts/gate-and-inputs.md), [검사 운영 계약](../ops/drift-gate-self-check.md): 내부 타입의 의미와 구현 한계를 기록했다.

## 막는 잘못된 상태

확정 사실과 판단 불가의 빈 하한을 구분한다. 잘못된 identity, `must ⊄ may`, 이유 코드 누락, 다른 scope/family/profile 비교, 확정 추가와 확정 삭제의 중복을 거부한다. 같은 빈 must가 반복돼도 may가 열려 있으면 확정 no-delta로 바꾸지 않는다.

생성자의 검증은 분석기 주장의 구조 검사다. 분석기가 잘못된 Exact를 반환하는 의미 오류까지 자동으로 증명해 주지는 않는다. 증거 참조도 문자열만으로 인증되는 것은 아니다.

## 호환성과 보장 범위

현재 gate·YAML·외부 JSON의 의미를 바꾸지 않았다. mixed auto의 기존 보류 동작도 유지한다. 완전 소스 env 집계는 파일 간 키 이동이 새 키 의무가 되지 않는 기존 규칙을 보존한다.

route의 Exact는 선택된 모듈 집합 안에서 기존 지원 부분집합의 정체성을 완전히 추출했다는 주장이다. 서비스 전체 discovery나 dependency closure의 인증이 아니다. Express adapter 사실은 원문 hash처럼 표시하지 않고 별도 opaque 참조를 사용한다. 추가/삭제 상태의 부재는 legacy 입력이 선언한 부재이며 Git tree의 부재를 독립 인증하는 certificate가 아니다.

`ExactDelta.is_empty`도 해당 basis 안의 정체성 무변화만 뜻한다. 전체 범위의 NoDeltaCertificate, 원문 manifest, profile registry, 의무 집합, proof DAG, 새로운 결과 projection은 이 단계에서 구현하지 않았다. env의 기존 patch heuristic 경로는 유지하며 새 typed API와 혼동하지 않는다.

## 직접 실행한 검증

| 검사 | 결과 | 근거 |
|---|---|---|
| Python 전체 최종 | **1,355 통과, skip 0** | [최종 로그](../assessment/typed-facts-implementation-2026-10-07/python-final.log) |
| 집중 검사 | **127 통과** | [로그](../assessment/typed-facts-implementation-2026-10-07/targeted-first.log). 새54 + 기존 enterprise73 |
| Python 정적 검사 E9,F | 통과 | [로그](../assessment/typed-facts-implementation-2026-10-07/ruff.log) |
| 고정 기능 fixture | **21/21** | [결과](../assessment/typed-facts-implementation-2026-10-07/fixed-evaluation.json) |
| Python/Git v2 | 네 축 각각 **14/14** | [결과](../assessment/typed-facts-implementation-2026-10-07/python-git.json) |
| Express/Git v1 | 네 축 각각 **8/8** | [결과](../assessment/typed-facts-implementation-2026-10-07/express-git.json) |
| 이전 22개 의미 사례의 actual | 변경 없음 | [최종 비교 기록](../assessment/typed-facts-implementation-2026-10-07/verification.json) |
| 자체 Drift Gate | **pass / unverified** | [결과](../assessment/typed-facts-implementation-2026-10-07/self-check.json), [입력](../assessment/typed-facts-implementation-2026-10-07/self-check-inputs.json) |

새 회귀에는 세 사실 universe의 Exact/Bounded/Unknown과 가능한 구체 전후 집합을 모두 열거해 실제 운영 `compare_facts`의 하한·상한을 대조하는 검사가 있다. 이는 유한한 모델의 변화 계산 검증이며 parser 건전성이나 실제 PR 정확도 증명이 아니다.

최초 전체 실행은 네 HTTP oracle이 sandbox의 루프백 포트 제한으로 실패했고, 문서 편집 중 저장소를 수집한 temporal CLI 검사도 변경 감지로 중단됐다. [최초 로그](../assessment/typed-facts-implementation-2026-10-07/python-full.log)를 남겼다. 편집을 끝내고 루프백 시험을 허용한 환경에서 전체 검사를 다시 실행해 최종 통과했다. 이 실패를 없애려고 테스트나 기대값을 약화하지 않았다.

자체 게이트 입력은 HEAD 대비 tracked 변경과 명시 수집한 untracked source/test31개를 합친 총78개다. Git index는 바꾸지 않았다. 미분류 운영 경로는0이다. 자체 정책의 pass는 문서 변경 의무의 충족이며 내용 전체의 정확성 보장이 아니다.

## 다음 변경 묶음

S1-b는 계약 profile registry와 discovery다. 이어서 S1-c에서 모든 적용 계약 의무를 구성하고 미탐지/open 범위 guard를 유지한다. S1-d–e에서 증명 DAG·검사 범위·기존 출력 연결을 구현한다. 현재 타입을 도입했다고 혼합 계약을 자동으로 각각 판정한다고 말하지 않는다.

이번에는 UI 소스를 수정하거나 React/tsc를 다시 실행하지 않았다. Python 전체에는 기존 Qt·Desktop 회귀가 포함된다. 새 원격 CI, Windows/Linux, 최종 설치본, 사람 blind holdout 검증은 수행하지 않았다. 현재 실행은 Mac 로컬 검증이다.
