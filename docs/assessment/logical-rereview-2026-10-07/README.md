# 논리 구조 재검증 실행 근거

대상은 `ver2`의 `d262ec2` 기반 미커밋 작업 트리다. 상세 해석과 남은 한계는 [검토 문서](../../review/drift-gate-logical-rereview-2026-10-07.md)에 있다. 이전 평가 입력과 결과는 변경하지 않았다.

## 자료

- `cases.json`: 수정 전 최초 9개 입력. 오류 반례 7개·정상 통제 2개.
- `before-seed1.json` ~ `before-seed8.json`: 위 입력의 수정 전 결과. R3의 판정이 seed에 따라 바뀐다.
- `threshold-case.json`, `threshold-before.json`: 실제 Git 형식 필드 삭제의 입력과 수정 전 전체 결과.
- `before-source-hashes.json`: 최초 검사 시 핵심 운영 코드 5개의 해시.
- `final-cases.json`: 최종 10개 입력. 기대값은 수정 전부터 고정한 계약을 사용한다.
- `after-seed1.json` ~ `after-seed8.json`: 최종 10개 입력이 모두 기대값과 일치.
- `metamorphic.py`, `metamorphic-results.json`: 유한 논리 512상태·12,288순열, 정책 강화 10쌍, 파일 순서 20회 검사.
- `python-full.log`, `react.log`, `tsc.log`, `ruff.log`: 최종 전체 검증 결과.
- `fixed-evaluation.json`, `generalization-audit.json`: 기존 고정 입력 재실행. 경계 1/8은 남아 있다.
- `self-check.json`, `self-check-inputs.json`, `self-check.log`: 사용자 index를 변경하지 않고 별도 임시 checkout에 후보를 stage하여 실행한 자체 게이트.
- `docs-check.json`: README CLI 문서 검사 결과.
- `verification.json`: 최종 운영/시험 코드와 실행 근거 파일 해시, 환경·검증 범위.

## 재현

저장소 루트에서 실행한다. Python 환경은 저장소의 개발 의존성이 설치되어 있어야 한다. 각 출력 파일은 새 경로를 사용해야 한다. 스크립트는 기존 결과를 덮어쓰지 않는다.

```sh
python docs/assessment/logical-rereview-2026-10-07/reproduce.py \
  --cases docs/assessment/logical-rereview-2026-10-07/final-cases.json \
  --out /tmp/logical-rereview-new-result.json
python docs/assessment/logical-rereview-2026-10-07/metamorphic.py \
  --out /tmp/logical-rereview-new-metamorphic.json
python -m pytest -q drift_gate/tests/test_logical_rereview.py drift_gate/tests/test_logical_entrypoints.py
```

`metamorphic.py`는 결과 파일과 같은 폴더에 `after-seed1.json`부터 `after-seed8.json`도 생성한다. 같은 경로에 기존 파일이 있으면 재실행을 거부하므로 새 출력 폴더를 사용하는 것이 좋다.

GitHub Action 입력 수집은 테스트에서 대체했다. 실제 PR·원격 CI·새 설치본·Windows/Linux 실행 결과는 이 자료에 포함되지 않는다. 지원 입력의 회귀 결과와 기존 미지원 경계 결과를 분리해서 해석한다.
