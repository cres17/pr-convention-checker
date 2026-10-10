# 구현 계획의 전제 재검증

운영 코드 `ae0028d`에서 계획 전제 13조건을 확인했다. 재현은 임의 정책 YAML과 순수 엔진 입력을 사용하며 제품 파일을 수정하지 않는다. 외부 네트워크·파서 다운로드를 요구하지 않는다.

- `plan-before.md`: 재검증 전 계획 원본. 이전 hardening-audit의 validation에 기록된 계획 hash와 동일하다.
- `probe.py`, `results.json`: 13조건과 현재 관측. 결함 수정의 회귀 성공 결과가 아니다.
- `local-refs.json`: 로컬 remote-tracking ref의 두 경로 부재. 원격 실시간 조회가 아니다.
- `related-tests.log`: 관련 기존 테스트 161개 결과.
- `validation.json`: 이번 계획·결과·probe hash와 링크 점검 기록.

재현 시 저장소 루트에서 개발 의존성이 있는 Python으로 실행한다. 기존 결과를 덮어쓰지 않도록 새 출력 경로를 사용한다.

```sh
python docs/assessment/plan-revalidation-2026-10-06/probe.py --out /tmp/drift-gate-plan-probe-new.json
python -m pytest drift_gate/tests/test_engine.py drift_gate/tests/test_validator.py drift_gate/tests/test_intensity_classifier.py -q
```

probe는 실행 시 workspace 소스를 읽으므로 수정 후 결과가 바뀌면 assertion이 실패할 수 있다. 동일 기준 재현에는 `ae0028d`의 별도 checkout과 이 probe를 사용한다. 이전 Git 44조건 및 외부 재현 12개와 독립 정확도 표본처럼 합산하지 않는다.
