# 집중 논리 개선 근거

기준 HEAD `a76306f5636b64daa617e3f90158a79785e07ad1` + 작업 트리, 2026-10-13.
실행 환경·현재 코드 identity·wheel 영수증은 [validation.json](validation.json)에 있다.

| 파일 | 의미 |
|---|---|
| [probes-after.json](probes-after.json) | 기존 포트폴리오 반례 스크립트의 현재 실행. 이전 결과는 별도 원본 유지 |
| [focused-flow.json](focused-flow.json) | 실제 Git/CLI/증거 재실행 11개 통제 결과 |
| [wheel-focused-flow-final.json](wheel-focused-flow-final.json) | 새로 설치한 최종 wheel로 체크아웃 밖에서 실행한 11개 통제 결과 |
| [pytest-final.log](pytest-final.log) | 전체 2,064 passed·6 skipped·4 warnings |
| [post-review-regressions.log](post-review-regressions.log) | 최종 score 입력 검증 보완 뒤 관련 65개 회귀 |
| [react.log](react.log) | React 126개 |
| [ruff.log](ruff.log), [mypy.log](mypy.log) | 정적 검사 원본 |
| [docs-check.json](docs-check.json) | README 명령·필드 검사 |
| [self-check.json](self-check.json), [check_changes.py](check_changes.py) | 27개 변경/계약 경로의 임시 투영 자체 정책 검사 |
| [wheel-build.log](wheel-build.log) | 최종 wheel 빌드 로그 |
| sha256.json | 이 폴더의 결과·로그·환경·재현 파일 해시 |

`pytest.log`, `wheel-focused-flow.json`은 최종 보완 전 실행이며 원본을 보존했다.
최종 결과는 위 표에 표시한 파일이다.

다시 실행하려면 프로젝트에 설치한 환경에서 다음을 사용한다. 기존 결과를 보존하려면 새 출력 경로를 쓴다.

```sh
python docs/assessment/portfolio-review-2026-10-13/probes.py > /tmp/driftgate-probes-after.json
python scripts/check_focused.py --out /tmp/driftgate-focused-flow.json
python -m pytest -q drift_gate/tests/test_focused_logic.py drift_gate/tests/test_holdout_evaluation.py
```

검사 사례와 지표 입력 label은 합성 자료다. 독립 사람 평가나 실제 PR 정확도·시간 절감 근거가 아니다.
CLI 통제의 임시 저장소·증거 묶음은 정리되므로 기록한 hash만으로 원본 묶음을 다시 열 수는 없다.
실제 입력 보관과 replay는 제품의 `check --evidence-store`와 `bundle` 명령으로 수행한다.
투영 자체 검사도 원래 저장소 전체 PR·원격 CI를 대신하지 않는다.

[구현·한계 보고서](../../review/drift-gate-focused-logic-implementation-2026-10-13.md).
