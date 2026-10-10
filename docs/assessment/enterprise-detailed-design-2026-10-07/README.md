# 심화 구현 설계의 참조 검증

2026-10-07. [설계 문서](../../architecture/drift-gate-enterprise-detailed-design-2026-10-07.md)의 유한 참조 모델과 검증 기록이다. 운영 코드·기존 평가 입력·이전 실행 결과를 바꾸지 않았다.

- `check_design.py`: 운영 코드와 독립적인 제안 논리의 실행 모델.
- `model-check.json`: 최초 탐색 실행. 당시 script hash를 보존하며 현재 script와 다르다.
- `model-check-final.json`: 네 기각 대안의 명시 반례 검사까지 포함한 최종 실행.
- `verification.json`: 최종 문서·모델 hash, 링크 검사, 이전 source/근거 hash 대조, 범위 한계.

최종 모델은 집합 구간729개(구체 world4,096개), 중첩 회로 할당297개, witness 보완692개, scope guard6개, publication event sequence46,656개, 기각 대안4개를 검사했다. 각 분모는 서로 다른 검사 단위이므로 합쳐 테스트 정확도나 성공률로 표현하지 않는다.

publication 모델은 atomic CAS와 generation 무효화를 가정한다. 운영 publisher·실제 동시성·진행성·parser 건전성·실제 PR 정확도·CI·설치본을 검증한 자료가 아니다. 제품 전체 테스트는 이번 설계 작업에서 재실행하지 않았다.

재실행은 존재하지 않는 새 출력 경로를 사용한다.

```sh
python docs/assessment/enterprise-detailed-design-2026-10-07/check_design.py \
  --out /private/tmp/drift-gate-detailed-model-new-run.json
```

기존 결과 파일을 지정하면 종료 코드2로 거부한다.
