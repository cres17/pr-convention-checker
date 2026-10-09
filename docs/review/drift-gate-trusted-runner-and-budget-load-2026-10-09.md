# 후보 코드를 실행하지 않는 신뢰 엔진 job과 자원 예산 부하 시험

2026-10-09 KST · 기준 `a4b0219`

[791565f 검토](drift-gate-enterprise-791565f-review-2026-10-08.md)의 권고 순서 5 중 "신뢰 runner 분리"와 "자원 예산 부하 시험"을
다룬다. 앞의 것은 일부만 해결했고 남은 경계를 아래에 적었다.

## 신뢰 엔진 job

기존 self-check의 `trusted-check`는 신뢰 엔진을 별도 interpreter로 실행하지만, 그 실행을 지휘하고 판정을 결합하는 코드는
후보 commit의 `drift_gate`다. 새 CI job `trusted-engine`은 다음 순서로 실행한다.

1. 후보 저장소를 checkout하되 Git 객체 저장소로만 쓴다(`persist-credentials: false`).
2. `git archive ed9f9046cca46c79b379ccdbafaa08feaa8241d6`로 pin한 commit의 파일을 꺼내 비 editable로 설치한다.
3. `python -I`에서 `drift_gate`가 site-packages에서 import되는지 확인한다. checkout에서 import되면 실패한다.
4. 그 설치본으로 grammar를 준비하고, immutable Git 경로로 후보 commit을 pin한 정책(`ae0028d`, SHA-256 `3b703eaf…`)으로 검사한다.

후보 commit의 파일은 Git 객체로 읽힐 뿐 import·실행되지 않는다. pass·warn은 통과, fail과 입력 오류는 job 실패다.

| 확인 | 결과 | 근거 |
|---|---|---|
| 같은 단계를 컨테이너에서 실행(`791565f`..`a4b0219`) | site-packages import 확인, 검사 pass | [요약](../assessment/trusted-runner-and-budget-load-2026-10-09/local-trusted-engine-verdict-summary.json) |
| 원격 CI | push 후 실행 기록으로 확인 | 이 보고서에 포함하지 않음 |

**남은 경계:** push와 `pull_request` 이벤트는 후보 branch의 workflow 파일을 실행한다. 후보가 이 job을 지우거나 바꾸면 그 실행에서는
보호되지 않는다. 막으려면 저장소 ruleset에서 이 job을 required status check로 지정하거나 조직의 required workflow를 써야 한다.
이 설정은 저장소 파일로 할 수 없고, 현재 설정 여부는 확인하지 않았다. grammar 다운로드 cache는 후보 코드를 실행하는 다른 job과
같은 key를 쓰므로 후보가 채울 수 있다. 신뢰 엔진의 `prepare_parsers.py`가 자신의 `parser_hashes.json` pin과 SHA-256을 대조해
다르면 실패하므로, 바뀐 grammar는 판정에 쓰이지 않고 job 실패로 드러난다. GitHub-hosted runner와 action 자체를 신뢰한다는
가정은 남는다.

## 자원 예산 부하 시험

`scripts/measure_budget.py`가 합성 저장소를 만들고 `scope`를 별도 process로 두 번 실행한다. 같은 commit을 base와 head로 써서
module을 두 번 읽는다.

| 조건 | 결과 | 시간 | peak RSS | 근거 |
|---|---|---:|---:|---|
| module 4,000개 × 약 20,000 bytes, 기본 예산 | 완료, bytes 160,193,061 사용 | 4.48초 | 284,336,128 bytes | [결과](../assessment/trusted-runner-and-budget-load-2026-10-09/budget-load-4000x20000.json) |
| 같은 저장소, `max_total_bytes: 20000000` | `resource_limit`(bytes, `scope-batch-read`), 종료 2 | 0.23초 | 35,684,352 bytes | 같은 파일 |
| module 200개 × 약 5,000 bytes, 두 조건 | 완료 / `resource_limit` | 1.49초 / 0.08초 | 35,647,488 / 32,231,424 bytes | [결과](../assessment/trusted-runner-and-budget-load-2026-10-09/budget-load-200x5000.json) |

예산 초과 실행의 peak RSS는 interpreter 기동 수준에 머물렀다. 크기 조회 단계에서 예산을 청구해 내용을 읽기 전에 멈췄다는
뜻이다. 기본 예산 실행에서는 읽은 bytes의 약 1.8배가 peak RSS였다.

이 수치는 Linux 컨테이너(Python 3.11.17)의 합성 저장소 한 형태에 대한 측정이다. 실제 저장소, 다른 OS, `check`의 diff·patch
수집 경로에서는 다를 수 있으며 용량 보장으로 쓰지 않는다. `max_memory_bytes`는 여전히 `--isolated-workers`의 worker에만
적용되고 주 process의 memory 상한은 아니다.
