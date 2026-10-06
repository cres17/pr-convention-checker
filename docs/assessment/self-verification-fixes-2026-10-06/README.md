# 자기 검증 수정의 재현 자료

[수정 보고서](../../review/self-verification-fixes-2026-10-06.md). 수정 전 자료는 [이전 폴더](../self-verification-2026-10-06/README.md)에 보존했다.

기준 HEAD는 `01e28e1`이며 이 폴더는 그 위의 로컬 후보를 검증한 결과다. 고정된 commit의 결과라고 해석하지 않는다. 최종 후보는 `validated-candidate-run/manifest.json`과 `validation.json`의 파일 해시로 식별한다. `candidate-run`과 `final-candidate-run`은 중간 기록이다.

## 재실행

프로젝트 루트에서 프로젝트 dev/desktop Python 환경으로 실행한다. 출력 폴더는 새 이름을 사용한다.

```bash
python -m pytest -q
python -m ruff check --select E9,F drift_gate scripts/check_self.py
python docs/assessment/self-verification-2026-10-06/probes.py --out build/self-fixes-probes-rerun
python scripts/audit_generalization.py --source-root . --revision WORKING_CANDIDATE --out build/self-fixes-audit-rerun.json
python docs/assessment/self-verification-fixes-2026-10-06/validate_candidate.py --out build/self-fixes-candidate-rerun
```

`desktop-ui`에서는 `npm test -- --run`, `npx tsc --noEmit`을 실행했다. 테스트 추적의 추가 실행은 전체 테스트 수에 합산하지 않는다.

## 결과 파일

- `validated-candidate-run/own-policy.json`: 이번 후보의 자체 정책 판정과 경로 적용 목록.
- `validated-candidate-run/own-policy-full-review.json`: `729a3cd` 이후 전체 범위의 자체 정책 판정.
- `validated-candidate-run/review.stdout`: Drift Gate 코드 리뷰 지적 원본.
- `validated-candidate-run/manifest.json`: 복사한 운영 코드·정책·문서 해시 및 실제 명령/종료 코드.
- `probes/results.json`: 기존 재현 harness로 수정 후 재측정한 CLI/MCP와 초안 보존 실험. 이 파일의 기본 정책 coverage는 예시 `.drift-gate.yml`에 대한 것이며 새 자체 정책의 적용 범위와 다르다.
- `generalization-final.json` (이전 실행은 `generalization.json`): 동일 고정 합성 입력의 새 결과. 소스 hash·입력 hash·개별 결과 포함.
- `behavior-trace.json`, `behavior-trace.log`: 행동 테스트에서 리뷰 연결 후보 4개 함수가 실행됨을 확인한 기록.
- `python-tests-final.log` (이전 실행은 `python-tests.log`), `git-tests-final.log`, `react-tests.log`, `typescript.log`, `ruff.log`: 이번 로컬 검사 로그.

`validate_candidate.py`는 현재 tracked 변경과 명시한 새 소스/정책/계약 파일을 임시 checkout에 복사한다. 검사용 index는 임시 checkout에만 구성하며 기존 사용자 삭제 2건을 제외한다. 범위를 바꿀 때는 `NEW_PATHS` 목록도 함께 검토해야 한다.

원격 CI·새 설치본 검증 결과는 이 폴더에 없다. 새 워크플로가 원격에서도 통과했다고 보고하지 않는다.
