# S2-d: 실행 상태·취소·재시도·최신 결과·게시 복구 (W15)

2026-10-08 KST · 기준 커밋 `ed9f904` 위 미커밋 작업 트리 · commit·push·원격 CI 미수행

[심화 설계](../architecture/drift-gate-enterprise-detailed-design-2026-10-07.md) 10장(W15)의
상태 기계·게시 fencing·결과를 모르는 쓰기를 구현한다. 남은 항목 목록의 1~4번에 해당한다.
신뢰 검증기 분리(W09), 인증된 엔진 재실행, 분석 worker 프로세스 격리(W12)는 범위 밖이다.

## 구현 범위

| 코드 | 역할 |
|---|---|
| `core/execution/lifecycle.py` | 순수 상태 기계. 전이표·제어 주체·종료 불변·복구 규칙·재시도 허용 |
| `core/execution/latest.py` | 순수 target ledger fold. generation·ticket 기반 compare-and-set 판정 |
| `core/execution/publication.py` | 응답 유실 후 조회 결과의 판정표 |
| `adapters/run_store.py` | hash chain append-only journal·ledger, no-replace hard link CAS, heartbeat, 복구 |
| `adapters/run_coordinator.py` | 실행 소유자: 단계 기록, 마감 시간, 운영자 취소, 늦은 응답 폐기 |
| `adapters/github/publication.py` | PR 댓글 게시: 전후 HEAD 확인, 실행 순서 비교, idempotency key 조회 |
| `adapters/cli/runner.py` | `check/report`의 `--run-store`·`--timeout-seconds`·`--retry-of`·`--latest-target`, `run`·`publication` 명령 |
| `adapters/github_action/runner.py`·`action.yml` | Action 실행 journal, 게시 기록·출력 추가 |

core에는 시각·파일·네트워크·subprocess 호출이 없다. 시간·ID·저장은 adapter가 공급한다.

## 1. 실행 상태와 종료 기록

```text
requested → validated → captured → planned → analyzing → evaluated
          → result-validated → persisted → publish-pending → published
persisted 이전 단계 → rejected-input / cancelled / timed-out / internal-error / abandoned
persisted → publication-skipped
publish-pending → published / publication-stale / publication-rejected / publication-unknown
publication-unknown → published / publication-stale / publication-rejected (조회 결과로만)
```

- 설계의 `aborted`는 원인별로 `cancelled`·`timed-out`·`abandoned`로 나눴다. 영구 기록에서
  사람·마감·비정상 종료를 구분하기 위해서다.
- 의미 결과의 완료 시점은 `result-validated`다. `persisted` 이후에는 실패 상태로 전이할 수 없다.
  게시 실패가 이미 저장된 결과를 지우거나 바꾸지 않는다.
- 각 event는 `runs/<run_id>/journal/NNNNNNNN.json`에 canonical JSON으로 기록하고 이전 entry의
  SHA-256을 포함한다. 중간 entry 수정·번호 누락·외부 파일은 읽기에서 거부한다.
  **마지막 entry들을 통째로 삭제한 경우는 외부 기준점 없이 검출할 수 없다.**
- 비정상 종료: 소유자가 lease(`--stale-after`, 기본 600초) 동안 event·heartbeat를 남기지 않으면
  `run recover`가 종료 상태를 기록한다. 분석 중이면 `abandoned`, 게시 요청 기록 뒤라면
  `publication-unknown`이다. 게시 요청 전 저장 완료 상태는 목표가 없으면 `publication-skipped`,
  있으면 전송 전이므로 `publication-rejected`로 닫는다.
- 복구가 아직 살아 있는 느린 소유자를 닫을 수 있다. 이 경우 소유자의 다음 기록은 거부되고
  결과는 폐기된다. 안전 쪽(결과 미채택)으로 실패하는 설계다.
- SIGTERM과 Ctrl-C는 `cancelled`로 기록한다. SIGKILL·전원 차단은 기록할 수 없으므로 복구 경로로만 닫힌다.

## 2. 취소·재시도 계약

- 실행마다 `run_id`와 별도의 소유자 token을 둔다. 진행 event는 같은 token의 소유자만 기록한다.
  취소는 소유자나 운영자(`run cancel`), `abandoned`는 복구 주체만 기록한다.
- 분석은 daemon thread에서 실행하고 소유자는 마감·취소를 감시한다. 종료된 실행에 도착한
  응답은 `evaluated`로 기록되지 않고 `late-response-discarded` 주석만 남긴다.
  응답이 취소 직후 도착하는 경쟁도 같은 방식으로 거부한다.
- **Python thread는 강제 종료할 수 없다.** 마감 이후에도 분석 thread는 프로세스 종료 전까지
  계산을 계속할 수 있다. CLI는 종료 코드 3으로 끝나며 그 thread를 함께 종료한다.
  수집 단계 Git subprocess는 기존 호출별 30초 timeout을 따른다. 기존 PR API 수집 요청에는
  timeout이 없어 마감 이후 thread가 남을 수 있다. 프로세스 격리는 W12 과제다.
- 마감은 `evaluated`까지의 단계에만 적용한다. 검증된 결과를 마감 때문에 버리지 않는다.
- 재시도는 `--retry-of`로 **새 run**을 만든다. 이전 실행이 종료 상태여야 하고
  (`publication-unknown`은 미종료), 새 실행에 `retry_of`·`attempt`를 기록하며 이전 journal에는
  `retry-created` 주석만 추가한다. 이전 상태·결과·증거 묶음은 그대로다.
  수집 후 입력 digest를 비교해 `same-input`·`different-input`·`previous-not-captured`를 남긴다.

## 3. 최신 결과의 조건부 갱신

`--latest-target`은 immutable `--head`와 `--evidence-store`를 함께 요구한다.
수집 직후 target ledger에 `(head OID, authority digest)` 관찰을 기록하고 ticket을 받는다.

- authority digest: 정책 원문·정책 의미·drift-ignore·신뢰 정책 anchor·base OID·비교 방식·평가 날짜·proof 옵션.
- generation은 관찰한 HEAD나 authority가 직전 관찰과 다를 때만 증가한다.
  A→B→A는 세 번째 관찰에서 generation 3이 되므로 첫 A 실행(generation 1)은 갱신되지 않는다.
- 같은 generation 안의 역순 완료는 ticket 비교로 거부한다.
- 갱신 조건: 발급된 ticket의 관찰과 요청이 일치, 현재 generation·HEAD·authority 일치,
  실행이 의미 완료, 저장된 receipt를 다시 읽어 `completed` 확인, 기존 latest보다 큰 ticket.
- ledger entry는 private 파일을 fsync한 뒤 `os.link`로 다음 번호에 공개한다. 이미 있으면
  실패하므로 두 writer가 같은 번호를 가질 수 없다. 충돌 시 다시 읽고 다시 판정한다.
- **보장 범위:** 같은 호스트의 로컬 파일 시스템이다. 분산 lock이나 원격 provider의 CAS가 아니다.
  관찰은 실행이 시작될 때만 생기므로 provider의 실제 현재 HEAD와 다를 수 있다
  (`freshness_scope: last-observation-by-a-run-not-provider-head`).

## 4. 외부 게시의 불확실한 결과 복구 (PR 댓글)

GitHub issue comment API에는 조건부 쓰기와 idempotent create가 없다. 따라서 CAS를 구현했다고
주장하지 않는다. 대신 다음으로 경쟁 구간을 줄이고 남은 구간을 기록한다.

1. 쓰기 전 PR HEAD가 평가한 HEAD와 다르면 쓰지 않고 `publication-stale`.
2. 기존 Drift Gate 댓글의 metadata(`workflow`, `GITHUB_RUN_NUMBER`, `GITHUB_RUN_ATTEMPT`)가
   더 나중 실행이면 덮어쓰지 않는다. 다른 workflow 소유 댓글도 덮어쓰지 않는다.
   두 값은 GitHub 문서상 실행·재실행마다 증가한다.
3. 댓글에 idempotency key(저장소·PR·HEAD·workflow·run id/number/attempt·결과 digest의 SHA-256)와
   보이는 본문 SHA-256을 숨은 줄로 넣는다.
4. 응답 유실(timeout·연결 오류·5xx·해석 불가 응답)은 key로 조회한다.
   key와 digest가 일치하면 `published`, key만 같고 digest가 다르면 `publication-rejected`.
   기존 댓글 수정이 반영되지 않았으면 같은 내용의 PATCH를 한 번 재시도한다.
   새 댓글이 보이지 않거나 조회도 실패하면 `publication-unknown`을 유지하고 **다시 게시하지 않는다.**
5. 쓰기 후 HEAD가 바뀌었으면 `publication-stale`(`published: true`)로 기록한다.
6. `drift-gate publication reconcile --record ... --repo ... --pr ...`는 조회만 하며 원본 기록을
   덮어쓰지 않는다. 로컬 latest의 unknown은 `run reconcile`로 조회하며, entry가 없으면
   unknown을 유지한다.

읽기-비교-쓰기 사이의 동시 실행 경쟁은 남는다(`race_window`). `GITHUB_RUN_NUMBER` 등이 없으면
순서를 비교할 수 없으므로 댓글을 쓰지 않고 `publication-rejected`로 기록한다. 이전 버전의
마커만 있는 댓글은 순서 정보가 없어 덮어쓸 수 있다.

## 사용

```sh
drift-gate check --base BASE --head HEAD \
  --trusted-policy-ref POLICY_COMMIT --trusted-policy-sha256 POLICY_SHA256 \
  --evidence-store .drift-gate-evidence --run-store .drift-gate-runs \
  --latest-target owner/repo#12 --timeout-seconds 300 --json
drift-gate run show RUN_ID --run-store .drift-gate-runs
drift-gate run cancel RUN_ID --run-store .drift-gate-runs --reason superseded
drift-gate run recover --run-store .drift-gate-runs --stale-after 600
drift-gate run latest owner/repo#12 --run-store .drift-gate-runs
```

placeholder 값은 실제 commit·hash·run ID로 치환한다. 종료 코드: gate 0/1, 입력·검증 오류 2,
취소·시간 초과로 의미 결과 없음 3. `--run-store` 없이 기존 명령을 쓰면 동작이 이전과 같다
(로컬 모드 내부는 `inspect()`와 같은 수집→검사 순서를 명시적으로 호출하도록 바뀌었다).

## 검증 기록

실행 환경: Cowork Linux VM(aarch64, Python 3.10.12), 사용자 Mac 폴더 마운트. **macOS·Windows에서
실행하지 않았다.** `os.link`는 NTFS·APFS에서 지원되지만 이번에 두 OS에서 확인하지 않았다.

| 실제 실행 | 결과 |
|---|---|
| 신규 테스트 2개 파일 | 38 통과 |
| 신규 테스트 20회 반복 | 20/20 통과 (수정 전 1회 실패 원인: journal 디렉터리 생성과 첫 entry 공개 사이 test 대기 경쟁. `run list`도 같은 상태를 처리하도록 수정) |
| 전체 Python (3개로 나눠 실행) | 1,723 통과·13 skip·0 실패 |
| Ruff `E9,F` | 통과 |
| `docs-check README.md` | 경고 0 |
| 저장소 자체 정책 `check --base HEAD` | pass |

skip 13건은 PySide6 미설치(desktop 2개 모듈), FastAPI oracle 미설치, Express oracle 경로 미설정 4건,
Windows junction 전용 1건 등 이 환경 조건이다. 이전 보고서의 Mac 1,805건과 수치를 비교하지 않는다.
VM 제약으로 백그라운드 전체 실행이 중단되어 같은 파일 목록을 세 번에 나눠 실행했다.

| 신규 시험 | 반례·조건 |
|---|---|
| 상태 전이 전수표 | 19 상태 × 19 대상 × 4 제어 주체 = 1,444쌍. 종료 상태에서 전이 0건 |
| latest 유한 모델 | 관찰 3종·발급 ticket 게시의 길이 7 이하 전체 sequence. 불변식 위반 0, head만 비교하는 기각 대안은 과거 세대를 되살리는 경우를 실제로 포함 |
| CLI 동시 HEAD 변경 | 분석 중 다른 실행이 B→A를 관찰하도록 주입 → `publication-stale`/`generation-changed`, 결과 자체는 의미 완료 유지 |
| 프로세스 강제 종료 | 실제 child process를 분석 중 kill → lease 내 미복구, lease 후 `abandoned` |
| SIGTERM | 실제 child process → `cancelled`, 종료 코드 3 |
| 취소·마감 후 응답 | `evaluated` 미기록, `late-response-discarded` 주석 |
| 8개 writer 경쟁 | 같은 번호 공개 1건만 성공 |
| 게시 응답 유실 | 반영됨→key 조회로 `published`, 미반영 create→unknown·재게시 없음, 미반영 update→PATCH 1회 재시도 |
| Action 전체 경로 | fake provider로 `main()` 실행, journal 10단계 완료와 댓글 key 일치 |

유한 모델과 fake provider 시험은 실제 GitHub의 일관성·동시성, 다른 파일 시스템의 원자성,
전원 장애 durability를 증명하지 않는다. 실제 GitHub에서 게시 경로를 실행하지 않았다.

[근거 폴더](../assessment/run-lifecycle-implementation-2026-10-08/)에 실행 로그와 변경 파일 hash를 둔다.

## 남은 범위

- MCP·데스크톱 검사는 아직 journal을 쓰지 않는다. CLI `check/report`와 GitHub Action만 해당한다.
- 원격 CI·세 OS 검증, 실제 GitHub PR에서의 게시·재조회 확인.
- Action journal은 runner 임시 경로에 있으며 artifact 업로드로만 보존된다. Action 안의
  `publication-unknown`을 journal에 다시 반영하는 경로는 없고, 기록 파일 재조회만 제공한다.
- 분석 worker 프로세스 격리(W12), 신뢰 검증기·승인 인증(W09), 인증된 엔진 재실행.

## 최초 원격 검증에서 발견한 보완 (2026-10-08)

`fd9b1c2`의 push·PR CI에서 lint·self-check·benchmark와 Ubuntu 3개 job은 통과했다. macOS·Windows
6개 job은 각각 `test_cli_timeout_retry_and_lineage` 1건만 실패했다
(macOS 3.10: 1 failed·1,793 passed·5 skipped, Windows 3.11: 1 failed·1,787 passed·11 skipped).
[push CI](https://github.com/cres17/pr-convention-checker/actions/runs/37717210478),
[PR CI](https://github.com/cres17/pr-convention-checker/actions/runs/37717213526).

원인은 시험의 시간 가정이다. 마감 0.3초가 느린 runner의 Git 수집 단계 안에서 끝나
`captured`가 기록되지 않았고, 재시도의 입력 관계는 설계대로 `previous-not-captured`였다.
제품 동작이 아니라 시험 기대가 틀렸다. 마감을 5초로 늘리고 분석이 그보다 오래 걸리게 하며,
종료 단계가 `analyzing`임을 함께 확인한다. 같은 가정에 기대던 coordinator 마감 시험도
0.15초에서 2초로 늘렸다. 위의 로컬 검증 기록과 `validation.json`의 hash는 보완 전 상태이며
덮어쓰지 않는다.
