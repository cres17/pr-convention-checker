# Drift Gate 두 번째 아키텍처·워크플로우 리뷰

2026-10-06. `ver2`의 수정 작업 트리. HEAD는 `729a3cde70c3457b633798bb50273d815d4d2c12`지만 [직전 수정](architecture-fixes-2026-10-06.md)은 아직 커밋하지 않았다. HEAD만으로 이번 코드 상태를 식별하면 안 된다. 검증 자료의 `validation.json`에 소스별 SHA-256을 기록한다.

이 문서는 샘 알트만, Claude Code 개발진, OpenAI, Anthropic의 공식 평가가 아니다. 제품 책임자의 관점에서는 사용자가 작업을 끝낼 수 있는지와 결과의 신뢰성을, 개발 도구 엔지니어의 관점에서는 경계 계약·상태·실패 복구·배포 검증을 평가했다. 완벽하다는 인증이나 임의의 품질 점수는 제시하지 않는다.

## 판정

**직전 수정의 방향은 적절하다. 그러나 안정성 검토를 끝낼 단계는 아니다.** R1–R6의 회귀 검사는 통과하지만, 문서 파일의 생명주기, 저장 기준 재생성, 보조 이력의 장애 격리, 같은 버전 안의 시간 순서에 빈틈이 있다. public core API와 MCP 서버에 앞선 리뷰에서 남겨 둔 문제도 실제로 재현했다.

이번에는 운영 코드·제품 회귀 테스트를 변경하지 않았다. 기존 수정과 무관한 문서 삭제 2건도 그대로 두었다. 새 관찰 자료·리뷰·설계를 별도 작성했으며 커밋·푸시하지 않았다.

## 확인 범위

- 직전 변경 전체의 Git/CLI, baseline·초안·백업·이력, Qt 작업 실행, React 요청·세션·상태·병합 연결을 다시 읽었다.
- 추가로 public core 진입점, 날짜 의존 ignore 판단, MCP 입력·tool schema, native 빌드·릴리스의 출처 검사를 확인했다.
- 언어별 탐지 규칙 전부를 줄 단위로 검증하거나 실제 PR 정확도를 재평가한 감사는 아니다.
- Python **800 passed**, skip 없음. React **117 passed**. TypeScript·Vite 빌드, Ruff `E9,F` 통과.
- Python 관찰 스크립트의 반례 6개, 정상 통제 4개를 실행했다. Qt worker로 손상 이력 오류와 정상 통제를 별도로 실행했다. TS 관찰 2개도 실행했다. 관찰 성공은 결함 존재 확인이며 회귀 검사 수에 합산하지 않는다.
- 실제 설치 파일, Windows·Linux 실행, 실기기 GUI, 원격 CI, 판정 정확도·성능 벤치마크는 이번에 재실행하지 않았다. 직전 소스 Qt 화면 8건의 결과도 이번 실행 수에 합산하지 않는다.
- [재현 자료 및 실행 안내](../assessment/architecture-second-review-2026-10-06/README.md).

## 확인한 문제: 우선순위 순

P1은 지원 API에서 잘못된 승인 또는 정상 편집 경로의 지속적인 막힘, P2는 조건부 유실·프로세스 중단·표시 오류다. 각 발생 조건을 심각도와 함께 본다.

### S1 — P1: 문서 파일 삭제·이름 변경 뒤 저장을 마칠 수 없다

위치: `progress_service.py:581–588`, `merge.ts:36–42, 76–80`.

README.md로 확정 기준을 저장한 다음 PLAN.md로 이름을 바꿨다. 원래 문서를 reference로 바꾸고 기존 기능명을 편집해도 저장은 “기준 문서가 변경됐습니다. 다시 불러와 주세요”로 실패한다. 파일을 원래 위치로 되돌린 통제에서는 v2 저장이 성공했다.

재추출도 해법이 아니다. TS 관찰에서 기존 README.md와 새 PLAN.md를 모두 `documents`에 보존했다. **기능 삭제 버튼은 문서 binding을 지우지 않는다.** 같은 앱에서 사용하는 재추출·제외만으로 이 오류를 해소할 경로가 없다. 새 편집과 원래 기준은 남아 있으며 이 실험에서 데이터 유실은 없었다.

현재 보존 원칙이 “원문 위치를 남김”과 “지금 존재하는 파일을 저장 전제조건으로 사용”을 같은 map으로 표현한 것이 원인이다.

수정 방향: 활성 문서 binding과 보관 출처를 분리하고, 명시적 이름 변경 연결·문서 철회·출처 보관 동작을 제공한다. 없어진 문서를 자동으로 다른 문서에 연결하거나 자동 삭제하지 않는다. 보관 출처는 화면에 남기고 현재 근거로 집계하지 않는다. 다른 항목의 저장은 계속 가능해야 한다.

완료 조건: 삭제·rename·파일 복귀·중복 출처·다른 checkout에서의 부재에 대해 근거 보존, 명시적 선택, 확정 저장 완료를 함께 확인한다.

### S2 — P2: 기준 재생성 뒤 숫자 버전이 재사용되면 오래된 편집이 새 내용을 덮어쓴다

위치: `progress_service.py:624–629`.

기준 A(v1)를 읽은 편집기를 남겨 두고, 앱의 기준 파일을 삭제한 뒤 새 기준 B(v1)를 만들었다. B의 내용과 `baseline_id`는 A와 다르다. A의 오래된 편집을 저장하자 v2로 성공했고 B에만 있던 편집이 사라졌다.

**외부 저장 파일 삭제·복원/재생성 조건이다. 일반적인 두 편집기의 동시 저장이 실패한다는 뜻은 아니다.** 일반 동시 저장과 서로 다른 숫자 버전의 충돌 검사는 이번에도 통과했다.

추가된 `baseline_id`는 화면 응답 수락에는 쓰지만 저장 CAS의 기대 조건에는 쓰지 않는다. 이미 제공한 identity를 쓰기 계약에 연결하지 않은 상태다.

최소 수정: 내용이 달라지는 저장은 기대 `baseline_id`도 검사한다. 원래 존재하던 기준이 없으면 기존 편집을 암묵적으로 새 v1로 생성하지 않는다. 장기적으로 `{generation, version, content_hash}`를 쓰고 명시적 복원은 generation을 바꾼다. 동일 내용 재시도의 기존 멱등 동작은 유지한다.

완료 조건: 일반 충돌, 재생성 v1, 백업 복원, 기준 파일 부재, 응답 분실 후 동일 내용 재시도에서 덮어쓰기가 없고 정직한 결과를 반환한다.

### S3 — P1, public API 한정: policy_path를 전달해도 정책을 읽지 않고 pass한다

위치: `core/engine.py:18–47`.

blocker 정책 파일과 문서 없는 코드 변경을 만들었다. `run(files, policy_path=...)`는 `pass, no_policy=True`, 같은 파일을 adapter로 읽어 `run(files, policy=loaded)`한 통제는 `fail`이다. 인자의 설명은 정책을 읽는다고 약속한다.

공식 CLI/desktop/MCP adapter는 읽은 policy를 전달하므로 이 반례가 그 경로의 잘못된 통과를 재현한 것은 아니다. 앞선 리뷰의 미사용 API 인자 문제가 남아 있으며, 이번에는 판정 차이까지 직접 확인했다.

수정 방향: core에 파일 I/O를 넣지 않는다. 이 인자만 지정한 호출은 명시적으로 거부하고, adapter API에서 정책 로드를 담당한다. 이후 문서·호출자 이관 뒤 미사용 인자를 제거한다.

완료 조건: public API의 미지원 호출은 실행 오류이며 pass가 아니고, 공식 adapter의 기존 판단은 유지된다.

### S4 — P2: 손상된 편의 이력이 정상 현황 검사까지 막는다

위치: `progress_service.py:651–661`, `web_app.py:291–294`.

유효한 JSON인 `{"schema":1,"snapshots":[{}]}`를 이력 파일에 넣었다. 현황 검사는 성공하지만 이력 조회가 KeyError를 내서 실제 Qt worker는 `progressError` 하나만 전달한다. 정상 `progressReport`는 오지 않는다. 손상 이력을 제거한 통제에서는 report/history가 정상 전달됐다.

작업의 terminal 오류는 전달되므로 이전 R5의 무한 busy 문제와 다르다. JSON 문법 오류만 처리하고 내부 row 구조를 검증하지 않으며, 보조 이력을 핵심 검사와 같은 실패 단위에 묶은 문제다.

수정 방향: 이력 codec에서 row를 검증하고 원본을 보존한다. 정상 검사 결과 + `history.status=unavailable`과 복구 안내를 보낸다. 깨진 파일을 빈 목록으로 읽은 뒤 새 이력으로 조용히 덮어쓰지 않는다.

완료 조건: 문법 오류·root 배열·필드 누락·숫자/enum 오류·읽기 실패·이력 기록 실패에서도 핵심 검사와 확정 저장이 정직하게 남는다.

### S5 — P2: 같은 기준 버전의 미래 이력과 비교해 거짓 회귀를 표시할 수 있다

위치: `progress_history.py:80–93`.

v1의 01:00 검사 결과(unknown)를 02:00에 기록한 같은 v1 이력(implemented)과 비교하자 regressed=1이 나온다. 버전이 같은 행은 미래 시각이어도 통과한다. 화면은 baseline/inspection ID가 맞으면 이 값을 수락하는 것도 TS 관찰로 확인했다.

이는 이력 비교 함수와 수락 계약의 반례다. 자연 발생 동시성 빈도나 실제 GUI에서의 발생 횟수는 측정하지 않았다. 검사 완료 뒤 이력 조회 전에 다른 앱이 같은 기준의 검사 이력을 기록하는 순서에서 발생할 수 있다.

수정 방향: baseline revision과 inspection/source snapshot을 구분한다. 현재 검사의 관측 순서 이전에 기록된 기준점을 선택하며 미래 이력이면 비교를 보류한다. 단순 wall clock만으로 다중 프로세스의 모든 순서를 보장하지 않는다. 안정된 history sequence와 comparison anchor를 snapshot 시작 시 캡처한다.

완료 조건: 다른 버전 역순과 같은 버전 역순, 동일 시각, clock 역행, 다른 checkout의 이력을 구분하고 틀린 회귀를 생성하지 않는다.

### S6 — P2: MCP에 JSON 배열 한 줄이 들어오면 서버가 종료된다

위치: `adapters/mcp/server.py:37–47, 112–121`.

stdio에 `[]` 다음 정상 tools/list 요청을 보냈다. 서버가 AttributeError로 exit 1하고 응답은 0개였다. 정상 요청만 보낸 통제에서는 exit 0과 응답 1개였다.

구조적으로 잘못된 입력 때문에 이후 정상 요청을 처리하지 못한다. 원격 코드 실행이나 정보 유출을 재현한 것은 아니다. 정상 MCP 클라이언트가 항상 object를 보내는 경로에서는 드러나지 않을 수 있다.

수정 방향: JSON root와 envelope·params·arguments를 검증하고 요청 하나만 실패시킨다. 프레임 바이트·중첩·출력·실행 시간 제한을 둔다. JSON-RPC batch는 구현하지 않으면 명시적으로 거부한다. tools/list의 빈 properties도 실제 도구별 인자 schema로 보완한다.

완료 조건: malformed JSON, 배열/null/string, params 타입 오류, unknown tool, 잘못된 args 뒤에도 정상 요청을 처리한다.

## 코드 품질 평가

### 유지할 부분

- 정확한 Git 바이트 경로, literal pathspec, invalid ref fail closed. 경로 통제는 옵션 설정을 바꿔 우회하는 방식보다 검증하기 쉽다.
- `progress_context.py`, `progress_limits.py`, TS `limits.ts`로 반복 의미를 모은 점.
- 재추출·rebase·scope·상태 선택을 순수 함수로 분리한 점. 확인하지 않은 근거를 자동 완료로 올리지 않는 점.
- 저장 락 안의 비교·쓰기, 실행 수명 lease와 짧은 transaction gate의 분리.
- 확정 성공과 초안 cleanup 실패의 분리, 전체 이벤트 직렬화 후 전송, terminal 오류의 checked metadata.
- 실제 Git·Qt worker·명시적 interleaving·byte 경계·공통 wire fixture를 검사한 점.

### 더 정리할 부분

1. `DesktopBridge`는 623줄이며 dialog, 파일 저장 위치, 실행별 사전, 명령 조정, 결과 구성까지 맡는다. **동작 경계가 확인된 save/inspect/recovery 사용 사례부터 ApplicationService로 옮긴다.** 줄 수만 줄이는 파일 분할은 하지 않는다.
2. `progress_service.py`는 965줄이며 저장 의미 검증과 디스크/Git 조회가 섞여 있다. codec/store/domain validation/inspection capture를 분리하되 외부 함수 signature와 schema 1 reader를 유지한다.
3. baseline hash·숫자 버전·inspection UUID가 있어도 같은 입력을 읽었다는 증거는 아니다. identity의 이름·뜻·검사 시점을 일치시켜야 한다.
4. Python과 Zod의 공통 fixture는 유용하지만 현재 한 정상 draft와 소수의 실패만 다룬다. 중복 ID·미지원 schema·unknown field·base provenance·불완전 evidence·enum·크기 경계를 추가해야 한다. 타입 통과가 의미 검증을 대신하지 않는다.
5. 반복된 baseline load/context 생성은 InspectionService 경계로 모은다. 새 클래스는 이 조정 책임을 표현하기 위해 만들고, 모든 순수 함수에 interface를 붙이지 않는다.
6. React 화면 구성은 229줄로 정리돼 있으며 production App/현황 영역에서 `any`를 찾지 못했다. 이것이 상태 조합·프로토콜 정합성까지 증명하지는 않는다. 에러·취소·복구 선택·busy 복귀가 더 중요한 리뷰 대상이다.
7. `write_json`은 atomic replace이며 fsync는 없다. 프로세스 중단의 부분 JSON 방지와 전원 장애 뒤 완료 보존을 구분해야 한다. 현재 filesystem/OS 조건 밖까지 저장 내구성을 약속하지 않는다.
8. 여러 Git 보조 호출은 여전히 timeout이 없다. TaskRunner가 예외를 처리한다는 것과 끝나지 않는 작업의 종료를 보장한다는 것은 다르다. timeout 뒤 worker가 살아 쓰기를 계속할 수 있으므로 무조건 실패로 표시하지 말고 uncertain 상태·fencing을 설계한다.

## 기능·논리 보완

- 문서 관리: 파일의 실제 존재, 현재 목표 포함, 출처 보관, 명시 삭제를 별도 개념으로 표현한다. 단순 제외 체크박스를 출처 삭제로 해석하지 않는다.
- 결과 신뢰: 입력 coverage, parser method/reason, 정책 hash, 기준 revision, 관측 snapshot을 보고서와 화면에 연결한다. untracked 미포함이나 일부 입력 상한을 전체 검사 완료로 표현하지 않는다.
- 보조 결과: 정상 report와 테스트/링크/이력의 실패를 분리해서 사용자가 핵심 검사를 마칠 수 있게 한다.
- 복구: 16MB 백업은 받아도 2MB 자동 보관은 실패할 수 있다. 현재 안내를 유지하고 크기 한계를 미리 보여 주는 개선을 고려한다. 자동 삭제나 조용한 일부 저장은 도입하지 않는다.
- 접근성: 삭제 확인과 성공·오류 안내는 이미 있다. 오류 요약에서 필드 포커스로 이동하는 흐름을 유지한다. 키보드만으로 복구 선택·삭제 확인·저장까지 완료하는 native 검증은 이번에 하지 않았으므로 통과했다고 말하지 않는다.
- 정확도: 기존 합성 수치의 재인용보다 독립 holdout·지원 범위·inconclusive 측정이 우선이다. 테스트 800개는 정확도 800개 사례가 아니다.

## 실행 순서

1. S3 미지원 API의 false pass 제거와 S6 입력 오류 격리: 작고 명확한 경계 수정.
2. S2 baseline_id CAS와 missing baseline 거부: 조건부 유실 방지. 정상 재시도·기존 두 프로세스 시험 유지.
3. S4 이력 codec/보조 결과 격리와 S5 comparison anchor: 같은 inspection 흐름에서 함께 정리.
4. S1 문서 binding/provenance·rename/detach UX: 가장 넓은 저장 의미 변경이므로 계약과 이관을 먼저 확정.
5. ApplicationService·snapshot capture·schema v2·내구성·배포 provenance: 앞의 반례를 닫은 뒤 작은 단계로 진행.

우선순위표는 위험도이고 실행 순서는 작은 경계 패치를 먼저 만들기 위한 순서다. S1을 후속 배포의 장기 미해결 항목으로 넘기라는 뜻은 아니다.

[설계 v2](../architecture/target-architecture-v2-2026-10-06.md)는 현재 구현·제안·증거를 구분하고 이번 반례의 수락 조건, 실패 단위, 데이터 이관, 검증 의무를 구체화한다.
