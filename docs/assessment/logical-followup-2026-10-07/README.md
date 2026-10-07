# 논리 후속 보완 검증 자료

[결과와 지원 범위](../../review/drift-gate-logical-followup-2026-10-07.md)를 먼저 확인한다. 기준은 `d262ec2` 기반 미커밋 작업 트리다. 과거 검증 결과는 덮어쓰지 않았다.

- `oracle.py`, `oracle-results.json`: 실제 FastAPI 생성 OpenAPI와 정적 결과의 정상 32개·변조 통제 및 부분 판정 예시. 고정 테스트 소스만 실행한다.
- `benchmark.py`, `benchmark-before.json`, `benchmark-final.json`: 동일한 모듈 24개·규칙 8개 입력의 전후 비교. `benchmark-after.json`은 중간 측정이며 최종 보고에는 final을 사용한다.
- `capacity_benchmark.py`, `capacity-results.json`: 모듈 32개·필드 80개·규칙 8개의 최종 코드에서 캐시 on/off 대조. 보고서 전체 값이 같다.
- `python-full.log`, `focused-final.log`, `ruff.log`: 전체 및 관련 테스트와 린트 결과.
- `fixed-evaluation.json`, `generalization-audit.json`: 기존 고정 평가. 경계 미지원 1/8을 유지하여 한계를 숨기지 않는다.
- `metamorphic-results.json`, `after-seed*.json`: 앞선 논리 재검증의 고정 입력을 새 코드로 다시 실행한 결과.
- `docs-check.json`, `self-check.json`, `self-check-inputs.json`, `self-check.log`: 문서·격리 후보 자체 게이트와 수집 입력 해시.
- `verification.json`: 최종 소스·근거 해시와 측정 환경 및 범위.

저장소 개발 환경에 oracle 의존성을 설치한 뒤 실행한다. 운영 코어에는 FastAPI/Pydantic을 필수 의존성으로 넣지 않았다.

```sh
python -m pip install -e '.[dev,oracle]'
python -m pytest -q drift_gate/tests/test_contract_followup.py drift_gate/tests/test_fastapi_oracle.py
python docs/assessment/logical-followup-2026-10-07/oracle.py --out /tmp/new-oracle-result.json
python docs/assessment/logical-followup-2026-10-07/benchmark.py --out /tmp/new-benchmark-result.json
python docs/assessment/logical-followup-2026-10-07/capacity_benchmark.py --out /tmp/new-capacity-result.json
```

각 결과 스크립트는 기존 파일 덮어쓰기를 거부한다. 현재 코드로 benchmark를 실행하면 현재 성능이 측정된다. before는 수정 전에 보존한 측정값이며 현재 코드로 과거 성능을 재현했다고 주장하지 않는다.

네이티브 설치본·실제 HTTP 요청·원격 CI·실제 PR 정확도 결과는 포함하지 않는다. 프레임워크 실행은 고정 버전의 통제된 OpenAPI 생성 범위다.
