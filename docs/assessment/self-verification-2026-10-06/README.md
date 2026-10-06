# 2026-10-06 Drift Gate 자기 검증 재현 자료

검증 대상: `01e28e1620941a539d3e9c14972201b30adafd3b`, 비교 기준: `729a3cde70c3457b633798bb50273d815d4d2c12`.

[판단·AI 제안 거절 사례·개선 설계](../../review/drift-gate-self-verification-2026-10-06.md).

## 실행

프로젝트 루트에서 `.[dev,desktop]` 및 현재 프로젝트의 문법 분석 의존성이 설치된 Python을 사용한다. 실제 실행 환경은 `/private/tmp/driftgate-final-review-venv/bin/python`(3.11.15)이었다. Node 의존성은 `desktop-ui`에 준비돼 있었다. 설치 과정이나 파서 캐시 첫 준비는 네트워크를 사용할 수 있으며 이번 실험은 오프라인 설치 검증을 대신하지 않는다.

```bash
python docs/assessment/self-verification-2026-10-06/verify.py --out build/self-verification-rerun/product
python docs/assessment/self-verification-2026-10-06/probes.py --out build/self-verification-rerun/probes
python docs/assessment/self-verification-2026-10-06/trace_behavior.py --out build/self-verification-rerun/baseline-test-execution.json
python -m pytest -q
python -m ruff check --select E9,F drift_gate
```

`desktop-ui`에서:

```bash
npm test -- --run
npx tsc --noEmit
```

출력 폴더가 이미 있으면 harness는 실패한다. 기존 결과를 덮어쓰지 않고 새 이름으로 재실행한다. `verify.py`는 고정된 두 commit을 임시 checkout에서 비교한다. `probes.py`는 현재 작업 트리의 운영 모듈을 사용하고 HEAD를 기록하므로 운영 파일이 바뀐 상태에서 실행하면 이 결과와 같은 소스로 간주하면 안 된다.

## 자료

- `product-run/manifest.json`: 비교 SHA·명령·종료 코드·실행 시각·harness hash.
- `product-run/gate.stdout`, `gate.html`: 제품 CLI 규칙 검사 원본.
- `product-run/review.stdout`: 결정론적 코드 리뷰 원본, 일반 지적 0·테스트 연결 후보 31.
- `product-run/docs-check.stdout`: README 명령/정책 필드 점검 원본.
- `product-run/generalization.json`: 기존 고정 합성 32개 재실행 및 소스 hash. 새로운 holdout이 아니다.
- `product-run/summary.json`: 원본에서 추출한 집계와 불일치 사례.
- `probe-run/results.json`: 실패한 비교 기준, 초안 정리 제안, 기본 정책의 문서 통제, MCP 손상 바이트, 정책 경로 적용 범위.
- `probe-run/*.stdout`, `*.stderr`: 실제 CLI/프로세스 응답. 실패 로그는 결함의 재현 자료다.
- `baseline-test-execution.json`, `baseline-behavior-test.log`: 기존 행동 테스트가 `baseline_id`를 실제 호출한 추적. 전체 테스트 수에 추가 합산하지 않는다.
- `python-tests.log`, `react-tests.log`, `typescript.log`, `ruff.log`: 이번 소스 검증 로그. TypeScript 성공 로그는 비어 있다.
- `validation.json`: 검증 대상·테스트 결과·파일 hash·한계.

## 해석 제한

초안 삭제 실험은 폐기 가능한 임시 Git 저장소와 별도 data 디렉터리에서 수행했다. 실제 제품에 자동 삭제 기능을 추가하지 않았다. 과거 AI 제안의 자동 선택 조건을 harness에서 시뮬레이션하고 현재 서비스 API로 결과를 확인했다.

MCP의 잘못된 UTF-8 입력은 정상/잘못된 JSON 통제와 별도 프로세스에서 비교했다. 이번 OS 외의 동일 동작을 주장하지 않는다. 패키지·원격 CI 기록은 앞선 턴에서 확인했으며 이번 실행 수에 합산하지 않는다.
