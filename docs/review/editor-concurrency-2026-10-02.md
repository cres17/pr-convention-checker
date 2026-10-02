# 충돌 저장·편집 세션 최종 검토

검증일: 2026-10-02 · 검토 기준: `3a57e1e` · 수정 소스: `295a41dd03f368990aced04def41c89bf165a077`

## 수정한 문제와 재검토

| 문제 | 수정 | 검증 |
|---|---|---|
| 오래된 편집기로 저장하면 다른 편집이 사라짐 | 동일 저장 파일의 읽기·비교·쓰기를 OS 잠금으로 보호하고 기준 버전을 검사함. 같은 내용의 재시도는 버전을 올리지 않음 | 순차 충돌 및 별도 Python 프로세스의 동시 최초 저장·갱신 |
| 저장소를 떠나면 저장·자동 보관 응답을 버림 | `EditorSessions`가 저장소별 상태와 요청 수명을 함께 관리함. 돌아오기 전의 성공·실패도 반영하고 저장 중 입력 잠금을 유지함 | 늦은 보관 완료·저장 성공·실패·이전 응답 재생·추출 응답 |
| 90일 지난 초안을 일시적인 경로 부재로 삭제함 | 자동 삭제 제거. 사용자 선택과 확정 저장에서만 해당 사본을 정리함 | 폴더를 잠시 옮긴 뒤 다른 초안 보관·원래 폴더 복귀 |
| 기준 잠금만 고쳐도 두 앱의 초안이 서로 덮어써짐 | 실행별 UUID로 초안 분리. 복구 사본 선택과 삭제 시 수정 여부 검사 추가 | 두 Qt 브리지의 보관·한쪽 저장 성공·다른 쪽 충돌·선택 이후 새 편집 |
| 합치면서 새 조건에 이전 검증을 붙일 수 있음 | 완료 조건·구현·근거·수동 검증을 한 묶음으로 선택. 문서 출처도 함께 선택하고 이전 문서 검토 경계를 보존함 | 조건 수정 대 검증 완료, 서로 다른 근거 필드 수정, 문서 해시 변경 |

충돌을 표시하는 것에서 끝내지 않고, 원래 읽었던 기준·내 편집·최신 기준을 비교하는 합치기 흐름을 연결했습니다. 독립적인 변경은 모두 보존하며, 겹치는 부분은 사용자가 선택합니다. 합친 뒤에는 다시 검토하고 저장해야 합니다. 초안에는 원래 기준도 보관해 재시작 뒤 비교할 수 있습니다. 원래 기준이 없는 이전 초안은 차이가 있는 부분을 보수적으로 충돌로 표시합니다. 문서 10개·기능 120개 상한은 유지하며 초과 결과를 잘라내지 않습니다.

초안 삭제는 표시된 파일의 수정 시각·크기와 현재 파일을 잠금 안에서 비교합니다. 다른 편집이 보관된 파일은 보존합니다. 확정 저장 후 현재 실행의 사본과 변경되지 않은 복구 원본만 정리하고 다른 실행의 사본은 유지합니다. 선택 키는 해당 저장소의 사본 이름만 허용하며 경로 이탈을 거부합니다.

구조 검토에서는 잠금(`store_lock.py`), 저장소 세션(`editorSessions.ts`), 순수 합치기(`rebase.ts`)를 각각 분리했습니다. React 상태 전이를 서버 I/O와 섞지 않았습니다. 읽기 요청은 저장소를 떠날 때 취소하고, 쓰기 결과는 해당 저장소에 반영합니다. 저장·추출·복구에 따라 오래된 자동 보관 응답이 최신 초안을 보관 완료로 표시하지 않도록 요청을 무효화합니다. 잘못된 자동 보관 응답도 저장 전체의 오류로 취급하지 않습니다.

## 로컬 검증

- Python 전체 **742 통과**. [실행 로그](../assessment/editor-concurrency-2026-10-02/local/python.log)
- React 전체 **100 통과**, TypeScript·화면 빌드·Ruff `E9,F` 통과. [화면 테스트 로그](../assessment/editor-concurrency-2026-10-02/local/react.log)
- 실제 소스 Qt 호스트와 빌드된 React 화면, QWebChannel, 임시 Git 저장소, 실제 로컬 저장을 연결해 충돌 안내 → 내 편집 선택 → 재저장을 실행했습니다. 버전 3에서 내 제목과 다른 편집기의 영역 변경이 모두 보존됐습니다. [원본 이벤트·결과](../assessment/editor-concurrency-2026-10-02/local-qt/result.json) · [재현 코드](../assessment/editor-concurrency-2026-10-02/local-qt/conflict_harness.py) · [충돌 화면](../assessment/editor-concurrency-2026-10-02/local-qt/conflict.png) · [저장 화면](../assessment/editor-concurrency-2026-10-02/local-qt/saved.png)
- 실제 Qt 브리지의 초안 조회·삭제 호출도 화면에서 확인했습니다. 실행별 사본 3개 중 하나를 선택해 삭제한 뒤 다른 사본을 복구·저장했고, 선택하지 않은 사본은 유지됐습니다. [원본 이벤트·결과](../assessment/editor-concurrency-2026-10-02/local-recovery/result.json) · [재현 코드](../assessment/editor-concurrency-2026-10-02/local-qt/recovery_harness.py) · [복구 화면](../assessment/editor-concurrency-2026-10-02/local-recovery/recovery.png)
- 같은 로컬 의존성에서 변경 전 소스의 진입 JS는 950,608바이트였습니다. 변경 후 진입 JS는 958,620바이트로, 복구 선택·충돌 합치기 화면을 포함해 8,012바이트 늘었습니다. 비교용 변경 전 소스는 별도 임시 경로에 추출했으며 기존 평가 원본은 바꾸지 않았습니다. 과거 529KB 측정과 의존성 환경이 달라 직접 비교하지 않습니다.
- 고정 32개 합성 평가: 지원 **21/24**, 경계 **1/8**, 실행 오류 0. [원본](../assessment/editor-concurrency-2026-10-02/generalization.json)
- 고정 12개 Git 변경: **12/12**, 연속 두 번의 결과 동일. v1은 기존 가짜 응답기를 사용했고 실제 모델·API·PR 댓글은 실행하지 않았습니다. [원본](../assessment/editor-concurrency-2026-10-02/controlled/result.json)

## 원격 검증

`295a41d`를 `ver2`에 푸시했습니다. [일반 CI(push)](https://github.com/cres17/pr-convention-checker/actions/runs/36952740811), [일반 CI(PR)](https://github.com/cres17/pr-convention-checker/actions/runs/36952744830), [Desktop build](https://github.com/cres17/pr-convention-checker/actions/runs/36952740986)가 모두 성공했습니다. Windows·Intel Mac은 attempt 1, ARM Mac은 attempt 2입니다. ARM 첫 실행은 앱 자체 검사가 통과한 뒤 `hdiutil attach`가 `Resource temporarily unavailable`로 실패했고, 소스 변경 없이 실패한 작업만 재실행해 DMG 검사까지 통과했습니다.

세 플랫폼의 실제 frozen 앱과 배포 경로(Windows 설치본·macOS 읽기 전용 DMG) 검사 **6/6** 결과 JSON을 직접 내려받았습니다. 모두 화면·브리지 연결, 8개 파일의 `grammar+heuristic`, 문서 누락 `warn`, 숫자 IP 두 곳의 권한 거부, 빈 파서 캐시 유지를 확인했습니다. 원본 파서 해시 8개도 플랫폼별 저장소 고정값과 같습니다. Windows 설치·제거와 macOS 첫 실행 뒤 엄격한 서명 검사도 성공했습니다. [검증 요약](../assessment/editor-concurrency-2026-10-02/ci/summary.json)과 같은 폴더의 원본 JSON을 보존했습니다.

일반 CI는 Qt가 없어 Linux·macOS에서 707 passed / 3 skipped, Windows에서 706 passed / 4 skipped입니다. Qt가 있는 로컬 전체 검사는 742개입니다. Windows의 추가 생략 1개는 Unix 폴더 쓰기 권한 시험입니다. 데스크톱 선택 검사에서는 macOS 두 환경 200 passed, Windows 199 passed / 1 skipped를 확인했습니다. 화면 테스트 100개도 세 곳 모두 통과했습니다.

## 범위와 한계

이 기록은 기능 동작·편집 보존·알려진 합성 평가의 회귀 여부를 확인합니다. 테스트 증가를 판정 정확도 향상으로 해석하지 않습니다. 소스 Qt 화면은 macOS ARM64에서 임시 저장소로 실행한 것이며, 실제 사용자의 Windows·macOS 설치·사용성 검증은 아닙니다. 기존 공개 미리보기 릴리스는 갱신하지 않았습니다. 기존 로컬 문서 삭제 두 건은 이번 커밋에 포함하지 않았습니다.
