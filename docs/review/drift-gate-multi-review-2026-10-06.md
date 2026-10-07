# Drift Gate 최종 결과 다자 검토와 논리 검증

검토일: 2026-10-06. 대상: `d262ec2faff3b98c917e3e99f7b6260cf0514ff3` (`ver2`).

## 판정

**최종 설치본의 실제 오프라인 동작은 다시 확인했다. 다만 정책 판정과 검증 도구에는 재현되는 보완 사항 8개가 남아 있다.** 기존 테스트·CI 성공과 새로운 반례는 동시에 참이다. 테스트 성공을 판정의 완전성으로 확대하면 안 된다.

정책·입력 계약, 변경 분석, 설치본 증거를 세 검토 작업으로 분리했다. 일부 작업은 사용 한도로 최종 보고 전에 중단됐다. 주 검토자가 남겨진 재현 코드를 읽고 모두 다시 실행했으며, 어댑터 간 계약과 실제 다운로드 설치본을 추가 확인했다. 따라서 세 검토자가 모든 항목에 합의했다고 주장하지 않는다. 아래 판정은 주 검토자가 직접 재확인한 결과다.

운영 코드, 기존 평가 입력, 과거 결과는 변경하지 않았다. 새 검토 문서와 재현 자료만 작성했다. 커밋·푸시는 하지 않았다. 사용자가 삭제해 둔 문서 두 개도 복원하거나 포함하지 않았다.

## 다시 확인한 결과

| 검증 대상 | 이번 확인 결과 | 의미와 범위 |
|---|---|---|
| 보존한 최종 근거 파일 | 영수증에 기록된 SHA-256 **82개 모두 일치** | 보존 이후 바뀌지 않았다는 확인이며 내용의 진실성 자체를 증명하지는 않음 |
| 최종 arm64 DMG | SHA-256 `6f6d4a53f39f5bcada37b9b5d5f6147c67ed76eb21aa2ae6e7ab7a5ae917b47d` 일치 | 이전 다운로드와 같은 바이너리 |
| push·PR·Desktop CI | GitHub에서 세 실행 모두 `completed/success`, workflow head `d262ec2` 재확인 | PR은 기존 근거대로 후보를 부모로 포함하는 합성 merge를 검사 |
| 기존 설치본 보고서 | 원격 6개 + 로컬 1개에서 단계별 실행 ID와 실제 시그니처 diff·rename 경로를 추가 검사, **7/7 일치** | 단순히 `warn`과 규칙 이름이 있다는 검사보다 강한 사후 대조 |
| 다운로드된 Mac 설치본 재실행 | **새 결과 폴더**·임시 설치·OS outbound 차단·빈 파서 캐시에서 성공 | Qt offscreen UI/QWebChannel, 8개 언어, 시그니처·rename 검사. 모든 화면의 수동 사용성 검증은 아님 |
| 이번 설치본 실행의 신규성 | 세 단계의 실행 ID가 서로 다르고 이전 보고서 ID와도 다름 | 이전 JSON 재사용 가능성을 이번 실행에서는 배제 |
| 관련 기존 회귀 테스트 | `test_hardening_contracts.py`, `test_packaging.py`: **70 passed** | 아래 반례를 기존 테스트가 포착하지 못한다는 사실도 확인 |

이전 Python 912개·React 122개 전체 테스트는 이번에 다시 실행하지 않았다. 그 숫자는 이전 실행 기록이며 이번 실행 수치와 섞지 않는다. Windows·Intel Mac 설치본은 이번에 다시 실행하지 않고 보존된 CI 근거를 검증했다. Mac 서명은 ad hoc이고 공증되지 않았다.

CI: [push](https://github.com/cres17/pr-convention-checker/actions/runs/37429783255), [PR](https://github.com/cres17/pr-convention-checker/actions/runs/37429787652), [Desktop](https://github.com/cres17/pr-convention-checker/actions/runs/37429783328).

## 재현된 보완 사항

우선순위는 영향과 사용 경로를 고려한 의견이다. P1은 우선 수정할 판정·검증 결함, P2는 특정 조건이나 보조 경로의 결함이다.

| ID | 우선순위 | 재현 결과 | 관련 위치 |
|---|---|---|---|
| R1 | P1 | 실제 실행 코드 `++record()`를 diff 헤더로 버려 `pass` | `core/patch_lines.py:35` |
| R2 | P1 | `rules: []`가 CLI에서는 오류, MCP·GitHub Action에서는 `pass` | `adapters/mcp/tools.py:27`, `adapters/github_action/runner.py:51` |
| R3 | P1 | 아무 작업도 하지 않는 앱 + 이전 성공 JSON으로 설치본 검증 `PASS` | `packaging/verify_package.py:125-140` |
| R4 | P2 | 파일 목록 수집 직후 편집하면 변경이 있는데도 0개 검사·`pass` | `adapters/git/client.py:94-100` |
| R5 | P2 | 정책 guard가 두 구성에서 `fail → pass` 완화를 허용 | `core/policy/guard.py:18-32` |
| R6 | P2 | 잘못된 기간 입력에 종료 2만 반환하고 이전 성공 JSON·HTML 유지 | `adapters/cli/runner.py:1500-1508` |
| R7 | P2 | 시그니처·rename 결과를 다른 검사 결과로 바꿔도 검증기 통과 | `packaging/verify_package.py:97-102` |
| R8 | P2 | MCP에서 새 미추적 파일을 생략하면서 생략 사실·입력 출처를 전달하지 않음 | `adapters/mcp/tools.py:27`, `_compact_result` |

### R1. 코드 줄과 diff 헤더를 접두사만으로 구별한다

실제 임시 Git 저장소의 Python 파일에서 주석을 바꾸고 `++record()`를 추가했다. `record()`는 출력 후 정수를 반환하므로 이 코드는 유효하고 실제로 호출된다. 추가된 diff 줄은 `+++record()`가 된다.

`changed_lines`는 hunk 안에서도 `+++` 또는 `---`로 시작하는 줄을 버린다. 따라서 실행 코드가 사라지고 주석 변경만 남아 `comment-only`로 분류된다. `min_change_intensity: impl-only` 규칙은 평가되지 않고 **pass**가 나왔다. 대조군 `+record()`는 **fail**이었다. 이 사례는 원문이 없는 원격 diff의 알려진 한계와 다르다. **로컬 Git과 전체 Python 원문이 있어도 재현된다.**

수정 계약: hunk 밖의 파일 헤더와 hunk 안의 변경 줄을 상태로 구별한다. hunk 안에서는 첫 기호 한 개만 diff 표시로 소비한다. `+++`·`---`로 시작하는 유효 코드, 추가·삭제, 주변 주석, 복수 hunk를 교차한 테스트가 필요하다.

근거: [분석 재현](../assessment/multi-review-2026-10-06/analysis/reproduce.py), [결과](../assessment/multi-review-2026-10-06/analysis/results.json).

### R2. 실행 가능한 정책의 조건이 진입점마다 다르다

같은 코드 변경과 `rules: []`를 넣었을 때:

- CLI: 종료 2, `input_error`.
- 실제 stdio MCP의 compact/full 모드: 정상 도구 응답, `result: pass`.
- GitHub Action runner: `result=pass`를 출력하고 보고서를 작성.

MCP는 실제 별도 프로세스로 실행했다. Action은 외부 GitHub API 수집 부분만 대체하고 실제 runner·정책 로더·엔진을 실행했다. 실제 GitHub에 잘못된 정책을 푸시하거나 댓글을 보내지는 않았다. 유효한 규칙을 넣은 MCP 대조군은 `fail`이므로 서버 연결 실패에 따른 결과도 아니다.

공통 로더는 설정 편집 등의 용도로 빈 규칙을 허용하고, CLI·Desktop·자체 검사기는 실행 시 별도로 거부한다. MCP·Action에는 그 검사가 빠졌다. 따라서 “정책 없음 문제를 모든 제품 진입점에서 해결했다”는 명제는 성립하지 않는다.

수정 계약: 설정 로딩과 **검사 실행에 사용할 정책 검증**을 분리하고 후자를 모든 검사 어댑터에서 호출한다. 빈 규칙은 정상 판정이 아니라 입력 오류여야 한다. 설정 생성·목록 도구까지 무조건 같은 오류로 만들 필요는 없다.

근거: [어댑터 재현](../assessment/multi-review-2026-10-06/adapters_probe.py), [결과](../assessment/multi-review-2026-10-06/adapters-results.json).

### R3. 설치본 검증기가 결과의 신규성을 확인하지 않는다

실제 네이티브 라이브러리 대신 비어 있지 않은 가짜 파일과 manifest 구조를 둔 임시 앱을 만들었다. 실행 파일은 `exit 0`만 한다. 출력 폴더에는 이전의 정상 `result.json`을 복사했다. macOS OS 네트워크 차단 아래에서 검증기는 **“rendered packaged UI + native bridge + 8 offline grammar analyses” PASS**를 출력했다. 결과의 실행 ID도 과거 값 그대로였다.

같은 무동작 앱을 새 출력 폴더에서 실행한 대조군은 결과 파일이 없어서 실패했다. 즉 원인은 정상 종료 여부가 아니라 **오래된 성공 파일 재사용**이다. 최초 시도는 실행 환경의 sandbox 제한으로 종료 71이었고, OS sandbox 실행이 허용된 재시도에서 위 결과를 확인했다.

이 결함만으로 기존 CI가 거짓 성공했다고 단정할 수는 없다. 기존 7개 결과를 추가 대조했고, 실제 최종 DMG도 새 폴더에서 다시 성공했다. **현재 바이너리의 성공 근거는 유지되지만, 검증기의 재실행 안전성은 수정해야 한다.**

수정 계약: 매 실행 고유 출력 경로를 사용하고, 실행기가 만든 challenge/run ID·예상 fixture 식별자를 앱 응답과 대조한다. 결과가 없거나 이전 실행이면 실패시킨다. 파일 시각만으로 판정하지 않는다. manifest 파일의 존재 확인을 무결성 검증이라고 표현해서도 안 된다.

근거: [재현](../assessment/multi-review-2026-10-06/evidence/reproduce.py), [대조군 포함 결과](../assessment/multi-review-2026-10-06/evidence/results.json).

### R4. 안정성 확인 구간 밖에서 파일 목록을 읽는다

`--name-status` 파일 목록을 읽은 직후, 첫 전체 diff를 읽기 전에 파일이 수정되는 순서를 주입했다. 실제 Git 명령·실제 파일 편집을 사용하되 정확한 시점만 테스트용 wrapper로 제어했다. 자연 발생 빈도를 측정한 것은 아니다.

두 번 읽은 전체 diff는 모두 편집 후 내용이어서 비교를 통과한다. 그러나 파일 목록은 편집 전의 빈 목록이다. 결과는 `scanned_files=0`, `skip_reason=no-changes`, **pass**이고, 기록된 snapshot hash는 실제 변경이 있는 diff의 hash다. 직후 정상 재실행은 **fail**이다.

수정 계약: 파일 목록·상태·patch·원문·출처가 하나의 수집 경계 안에 있어야 한다. 최소한 첫 snapshot을 목록 수집보다 앞에 읽고 모든 수집 이후에 다시 비교한다. 가능하면 고정 tree/blob을 중심으로 입력을 구성한다. 시작/종료 snapshot 비교도 중간 변경 후 원복까지 완벽히 검출하는 증명은 아니라는 한계는 남는다.

근거: 분석 결과의 `snapshot_race`, `snapshot_race_control`.

### R5. 정책 완화 방지 비교가 실제 실행 의미를 모두 반영하지 않는다

독립적인 두 반례를 재실행했다. 둘 다 `weakening_reasons=[]`이지만 동일 입력에서 **fail → pass**다.

1. `required:false`인 그룹이 `cross_file.require_groups`로 조건부 강제되는 정책. guard는 `required:false` 그룹을 비교에서 제외한다. 그룹의 경로를 `docs/api.md`에서 `src/**`로 바꾸면 교차 파일 조건은 그대로여도 문서 없이 충족된다.
2. `fail_on_blocker:false`, `fail_on_major_count:1` 정책에서 severity를 `major`에서 `blocker`로 올린다. guard는 이름상 심각도가 높아졌다고 허용하지만 gate는 blocker를 실패·경고에 포함하지 않으므로 pass가 된다.

현재 저장소의 자체 정책은 필수 그룹과 blocker 실패를 사용하므로 이 두 사례가 최종 자체 CI 결과를 뒤집는 것은 아니다. 범용 정책 guard의 계약 결함이다. 두 번째 사례에서 gate의 `pass` 자체를 바꿀지와 guard가 이 변경을 허용할지는 별개의 설계 결정이다.

수정 계약: 항상 필수인 그룹뿐 아니라 교차 조건이 참조하는 그룹의 의무도 보존한다. severity의 순위만 비교하지 말고 gate 설정 아래의 실패 효과를 비교한다. 단순하고 보수적인 대안은 실패 효과를 증명하지 못하는 severity 변경을 명시적 정책 마이그레이션으로 처리하는 것이다.

근거: [정책 재현](../assessment/multi-review-2026-10-06/policy/probe.py), [전체 입력·결과](../assessment/multi-review-2026-10-06/policy/results.json).

### R6. 기간 입력 오류가 공통 오류 출력 처리를 우회한다

`check --temporal-gate --temporal-window nonsense --json --out-json ... --out-html ...`를 실행했다. 종료 코드는 2지만 stdout은 비어 있고, 미리 만든 `OLD` 실행 ID의 pass JSON과 `OLD PASS` HTML이 남았다. `_parse_days`가 직접 `sys.exit(2)`를 호출해서 공통 입력 오류 처리에 도달하지 않기 때문이다. 메시지도 `--temporal-window` 대신 `--last`를 가리킨다.

명령이 성공했다고 보고한 것은 아니므로 종료 코드를 정확히 처리하는 소비자는 실패를 알 수 있다. 다만 “입력 오류 시 새 오류 JSON·HTML로 교체한다”는 계약은 이 경로에서 지켜지지 않는다.

수정 계약: 어댑터 내부 입력 검증은 정해진 예외를 반환하고, 종료 코드와 오류 산출물 작성은 최상단 한 곳에서 담당한다. 존재하지 않는 옵션 등 argparse 단계의 오류에 대해서도 어떤 산출물을 약속할지 별도로 명시한다.

근거: [실제 CLI 재현](../assessment/multi-review-2026-10-06/policy/probe_cli.py), [결과](../assessment/multi-review-2026-10-06/policy/cli-result.json).

### R7. 설치본의 반례 검사가 해당 반례의 입력인지 확인하지 않는다

보존된 정상 보고서에서 `signature`와 `rename` 결과를 모두 최초 8개 파일 검사 결과로 바꿨다. `validate()`는 여전히 성공했다. 두 위치가 `pass`가 아니고 같은 규칙 위반만 있으면 통과하기 때문이다. 제품 내부 `package_check.finish()`도 같은 수준으로 확인한다.

따라서 브리지가 이전 검사 이벤트를 잘못 재사용하는 회귀를 놓칠 수 있다. 이는 JSON을 악의적으로 위조하는 공격을 전부 막으라는 요구가 아니다. **검증하려는 fixture가 실제 입력이었다는 검사 조건이 부족하다**는 뜻이다.

이번에는 기존 7개 보고서와 새 Mac 실행에서 서로 다른 실행 ID, 정확한 `*extra`·`**options` diff, `src/api.py → docs/api.py`와 `renamed` 상태를 별도 확인했다. 따라서 현재 자료에 이 오작동이 있었다는 증거는 없다.

수정 계약: fixture별 예상 변경 파일·경로·상태·핵심 diff와 실행 ID를 검사하고, phase 이름 중복도 거부한다. 초기 검사 결과 재사용, 단계 순서 교환, 잘못된 rename 경로를 변형한 음성 대조군을 추가한다.

근거: evidence 결과의 `unrelated_hardening_result`, [기존 단계 추가 검증](../assessment/multi-review-2026-10-06/evidence/validate_saved_phases.py), [7개 결과](../assessment/multi-review-2026-10-06/evidence/saved-phase-results.json).

### R8. MCP가 검사에서 빠진 새 파일을 알리지 않는다

규칙과 기존 코드를 커밋한 뒤 `src/new.py`만 미추적 상태로 만들었다. CLI에는 `execution.untracked_skipped`가 기록되지만 MCP compact/full 응답은 모두 **pass**, 파일 목록 0개이며 생략 정보·snapshot 출처가 없다. GitAdapter가 만든 provenance를 MCP helper가 보존하지 않기 때문이다.

미추적 파일을 평가 범위에서 제외하는 정책 자체는 이미 공개된 설계다. 문제는 AI 도구 호출자가 새 파일을 작성한 뒤 검사를 실행할 때 **그 파일을 검사하지 않았다는 사실을 받을 수 없다는 것**이다.

수정 계약: 어댑터 공통 실행 결과에 입력 출처·생략 파일·정책 digest를 포함하고, compact 응답에서도 결과 해석에 필요한 이 정보는 제거하지 않는다. 토큰 예산이 부족하면 목록을 줄이되 생략 개수와 상태는 보존한다.

근거: 어댑터 결과의 `untracked_cli`, `untracked_mcp`.

## 논리 검증과 설계 보완 순서

이번 검토에서 채택할 명제와 거부할 명제를 구분한다. 아래 문장은 검토용 명제이며 특정 사람이 실제로 했다고 인용하는 발언이 아니다.

| 명제 | 판정 | 이유 |
|---|---|---|
| 최종 Mac 바이너리에서 준비된 오프라인 검사가 작동한다 | 채택 | 새 경로·새 실행 ID로 재실행 성공 |
| 최종 원격 CI와 내려받은 기록이 보고 내용과 일치한다 | 확인한 범위에서 채택 | 현재 CI 조회, 82 hash, 7개 단계별 입력 대조 |
| 기존 테스트가 모두 통과하므로 false pass가 없다 | 거부 | R1·R2·R4·R5가 반례 |
| 결과 JSON이 validator를 통과하면 이번 앱 실행의 증거다 | 거부 | R3의 무동작 앱이 반례 |
| 규칙 이름과 warn만 확인하면 원하는 반례를 실행했다고 볼 수 있다 | 거부 | R7의 단계 결과 교체가 반례 |
| 강도·심각도 필드의 순서 비교만으로 정책 의무 보존이 증명된다 | 거부 | R5의 교차 조건과 gate 설정 조합이 반례 |

권고 구현 순서는 다음과 같다.

1. **R1·R2:** 실제 판정의 조용한 pass부터 제거한다. hunk 파서와 공통 검사 정책 검증을 수정한다.
2. **R3·R7:** 새 수정이 검증기를 잘못 통과하지 않도록 실행 신규성과 fixture 식별을 강화한다.
3. **R4·R5:** 입력 수집 경계와 정책 의무 보존을 고친다. 경합 테스트는 일정한 시점 제어로, guard는 설정 조합 테스트로 검증한다.
4. **R6·R8:** 모든 진입점의 오류·출처 계약을 맞춘다.

권장 구성은 `입력 수집 → 실행 가능 정책 검증 → 불변 검사 입력 → 순수 엔진 → 공통 실행 결과 → CLI/MCP/Desktop/Action 표현`이다. core에 파일 I/O를 넣지 않고, adapters의 공통 서비스가 준비된 입력과 출처를 함께 전달하도록 한다. 현재 CLI·MCP·Action에 흩어진 “같아야 하는 실행 전제”가 달라진 것이 R2·R8의 직접 원인이다.

| 경계 | 보장해야 할 불변 조건 | 필수 반례 테스트 |
|---|---|---|
| 정책 실행 | 빈 정책은 평가 성공이 될 수 없음 | 동일 정책을 모든 검사 진입점에 전달 |
| diff 해석 | hunk의 코드가 헤더 접두사와 겹쳐도 유실되지 않음 | `+++`·`---`, 추가·삭제, 주석 동반 |
| 입력 수집 | 판정한 파일·원문과 기록한 snapshot이 같은 수집 상태에 속함 | 목록 수집 전후 편집, 재시도·오류 확인 |
| 정책 변경 | 신뢰 정책의 실패 의무를 후보 정책이 조용히 없애지 않음 | 필수/조건부 그룹 × severity × gate 조합 |
| 결과 출력 | 입력 오류와 규칙 위반이 구별되고 이전 성공 파일과 혼동되지 않음 | 잘못된 기간·정책·기준 ref와 기존 결과 파일 |
| 설치본 검증 | 이번 실행·이번 fixture의 결과만 수용 | 무동작 앱, 오래된 결과, 다른 단계 결과 재사용 |
| MCP 요약 | 생략된 입력과 실행 출처가 압축 과정에서 사라지지 않음 | 미추적 파일, 소량 토큰 예산, compact/full 비교 |

고정 평가 21개나 지원 사례 24개를 바꾸어 새 반례를 흡수하지 않는다. 기존 입력을 유지하고 별도 회귀 묶음에 추가한다. 통과 수가 늘어도 실제 PR 정확도를 의미하지 않는다. 외부 신뢰 실행기, 자연어 문서의 진실성, 전체 파일 AST, 미지원 언어 환경변수 의미 분석은 여전히 별도 범위다.

## 재현 자료와 제한

- [근거 목록과 SHA-256](../assessment/multi-review-2026-10-06/manifest.json)
- [이번 실제 Mac 설치본 결과](../assessment/multi-review-2026-10-06/evidence/fresh-installed-result.json)
- [설치본 신규성·반례 입력 확인](../assessment/multi-review-2026-10-06/evidence/fresh-download-results.json)
- [관련 테스트 70개 실행 로그](../assessment/multi-review-2026-10-06/targeted-tests.log)

재현 스크립트는 Python 개발 환경에 현재 소스가 설치된 상태에서 실행한다. CLI probe의 Python 경로는 이번 환경의 `/private/tmp/driftgate-final-review-venv/bin/python`이다. 다른 환경에서는 수정해야 한다. 설치본 재현은 macOS와 기존 최종 다운로드 근거 폴더가 필요하다. `recheck_download.py`는 과거 결과 재사용을 막기 위해 출력 폴더가 이미 있으면 중단한다. 반복할 때 기존 증거를 지우지 말고 새 출력 경로를 지정한다.

설치본·가짜 앱·임시 캐시 등 실행 산출물은 Git에서 제외된 `build/multi-review-confirmation/`에 있다. 저장소에 남길 자료는 작은 재현 코드와 JSON·로그로 제한했다. 이번 검사로 모든 동시성 순서·정책 조합·실사용 환경을 완전 검증했다고 주장하지 않는다.
