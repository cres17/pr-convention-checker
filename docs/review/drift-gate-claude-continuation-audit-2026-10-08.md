# 클로드 작업 인수 확인과 실행 복구 시간 입력 보완

2026-10-08 KST. 확인한 작업 경로는 `/Users/moon/Documents/pr-convention-checker`다.
이 문서는 전달된 진행 보고와 실제 코드의 차이를 기록하며, 이전 검증 결과를 덮어쓰지 않는다.

## 확보한 코드와 확보하지 못한 코드

인수 시 로컬 `ver2` HEAD는 `5cd00ed119e7b5e1c236fa288b225941a1d058df`다.
원격 브랜치를 실제 조회했을 때 `ver2`는 `b5c52ab281ed550b1e645bf000834f7c012f050f`였다.
`fd9b1c2`·`b5c52ab`·`5cd00ed`의 운영 변경과 테스트, W15 구현 보고서는 이 폴더에 있다.

| 전달된 보고 | 이 작업 공간에서 확인한 상태 |
|---|---|
| 목록 1~4번, 실행 상태·취소·재시도·최신 결과·게시 복구 | 코드·테스트·보고서 확보. 표적 테스트 40개 통과 |
| W09 고정 엔진 manifest·materialize, 승인 인증, 엔진 재실행 | 후속 코드·중간 커밋 미확보. 기존 explicit policy pin 및 CODEOWNERS 검증과 구분 |
| interval 문서 평가·사실별 byte range·service identity·dependency closure | 후속 코드 미확보. 기존 typed facts/planner/proof를 완성된 후속 구현으로 계산하지 않음 |
| 전체 Git 수집 예산·worker 격리·versioned proof gate·방향별 schema 호환성 | 후속 코드 미확보. 기존 개별 상한·daemon thread·shadow proof와 구분 |
| 독립 평가 도구·영구 캐시·조직 서비스 | 후속 코드 미확보. 독립 평가 자료와 사람 정답 검토도 미확보 |
| 설치본 bundle 실행 검증·Intel 종료 진단 추가 | 이번 인수 단계에서 수행하지 않음 |

일반 Git 상태뿐 아니라 무시된 파일, 전체 ref/reflog, 등록 worktree, 연결이 끊긴 commit도
확인했다. 발견한 연결이 끊긴 commit은 2026-10-01의 기존 현황 화면 수정이며 이번 후속
구현이 아니다. 원격에는 `main`·`ver2` 두 브랜치만 있었다. 이 확인은 인수 당시 관찰이며,
다른 환경에 후속 작업이 존재하지 않는다는 주장은 아니다.

사용자는 같은 프로젝트 폴더에서 작업했다고 설명했다. 그러나 후속 코드가 이 Mac 작업
트리에 도착했다는 증거는 확보하지 못했다. 원본 commit 또는 patch가 확보되기 전에는
5~23번을 완료 처리하거나, 존재할 수 있는 작업을 추정하여 덮어쓰지 않는다.
W17 조직 서비스와 영구 캐시는 설계상 조건부 항목이다. 독립 holdout·사람의 독립 검토는
평가 도구 코드만 추가한다고 완료되지 않는다.

## 재현한 결함과 수정

`run recover --stale-after nan`은 기존 `duration <= 0` 검사를 통과했다.
`now - last_activity < NaN`은 false여서, 방금 생성한 정상 실행도 lease가 만료된 것으로
처리했다. 임시 저장소에서 `requested → abandoned`를 직접 재현했다.

수정은 순수 lifecycle 모듈의 유한 시간 검증을 통해 duration과 비교 시각을 확인한다.
복구 adapter는 저장소를 순회하기 전에 요청 전체를 검증한다. 실행 controller도 시작 전에
비유한 timeout을 거부한다. boolean과 float 표현 범위를 넘는 정수도 거부한다.

회귀 테스트는 다음을 검증한다.

- NaN·Infinity·음수·0·boolean·표현 범위 초과 입력이 기존 journal을 바꾸지 않음.
- 직접 core 호출에서도 비유한 현재 시각·활동 시각·lease가 전이를 허가하지 않음.
- CLI 오류 종료 2, 잘못된 timeout에서 Git 수집과 새 저장소 생성을 하지 않음.
- 정상 유한 소수 lease는 경계 이전에는 유지하고 경계에서만 복구함.

원문 테스트·수치는 [근거 폴더](../assessment/claude-continuation-audit-2026-10-08/)에 기록한다.

| 실제 실행 | 결과 |
|---|---|
| 수정 전 전체 Python | 1,841 통과·5 skip |
| 수정 후 전체 Python | 1,882 통과·5 skip |
| 실행 상태·게시·신규 시간 입력 테스트 | 81 통과 (신규 41개) |
| 전체 Ruff E9,F | 통과 |
| 자체 Drift Gate, `5cd00ed` 이후 작업 트리 | pass |
| README docs-check | 경고 0 |
| 고정 `5cd00ed` 원본 lifecycle 대 현재 코드 비교 | NaN lease: 이전 abandoned, 현재 LifecycleError |

환경은 이 Mac의 Python 3.11이며, 클로드가 보고한 Linux VM의 1,789·12 skip 수치를
현재 코드의 기준선으로 대체 인용하지 않았다. UI 코드는 수정하지 않았고 React·UI 빌드는
이번에 다시 실행하지 않았다. 수치는 작성한 회귀 사례 결과이며 운영 정확도를 뜻하지 않는다.
원격 CI·설치본·실제 GitHub 게시 검증은 이번 수정에서 수행하지 않았다.
기존 사용자 삭제 파일 두 개는 그대로 유지했다. 이번 작업은 commit·push하지 않았다.
