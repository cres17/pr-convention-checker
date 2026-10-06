# AI가 작성한 문서에서 가져온 주장 (모두 "확인 완료"로 체크된 상태)

출처: `docs/contracts/gate-and-inputs.md`, `docs/contracts/mcp-transport.md`, `README.md`, `docs/assessment/self-verification-2026-10-06/` 를 만든 작업 기록.
각 항목은 원문을 그대로 옮겼고, 주장한 쪽이 이미 검증을 마쳤다고 표시한 상태(`[x]`)로 둔다.

## 입력과 종료 코드
- [x] C01 `check`, `report`, `review`, `self-audit`의 변경 수집 실패는 종료 코드 **2**다. 없는 base, 비저장소, Git timeout을 빈 변경으로 바꾸지 않는다. (`drift_gate/adapters/cli/runner.py`)
- [x] C02 JSON 모드의 입력 실패는 `{"error":{"code":"input_error","message":"..."}}`다. (`drift_gate/adapters/cli/runner.py`)
- [x] C03 로컬 GitAdapter는 base를 commit으로 확정하고 NUL 구분 경로를 읽는다. 외부 diff/textconv를 끄고 literal pathspec을 사용한다. (`drift_gate/adapters/git/client.py`)
- [x] C04 새 파일은 Git index에 추가해야 수집된다. (`drift_gate/adapters/git/client.py`)
- [x] C05 이미 커밋한 변경을 비교하려면 `--base main`처럼 실제 기준 브랜치를 지정한다. (`README.md`)

## MCP
- [x] C06 서버는 UTF-8 바이트 기준 최대 1,000,000바이트를 읽고, 초과하면 그 줄의 나머지를 배출한 뒤 다음 요청을 처리한다. (`drift_gate/adapters/mcp/server.py`)
- [x] C07 잘못된 UTF-8 또는 JSON 한 줄 때문에 뒤의 정상 요청을 잃지 않는다. (`drift_gate/adapters/mcp/server.py`)
- [x] C08 JSON-RPC 경로와 기존 `tool/args` 경로를 지원한다. batch는 지원하지 않는다. (`drift_gate/adapters/mcp/server.py`)
- [x] C09 응답은 UTF-8 기준 최대 2,000,000바이트이며 비유한 숫자는 직렬화하지 않는다. (`drift_gate/adapters/mcp/server.py`)

## 계약 내용 검사
- [x] C10 Python 환경 키는 파싱 가능한 조각의 실제 `os.getenv`, `os.environ.get`, `os.environ[...]` 호출에서 정적 문자열 키를 읽는다. 설명 문자열·주석은 접근으로 취급하지 않는다. (`drift_gate/core/python_syntax.py`)
- [x] C11 명시적 `env-keys` 내용 검사는 지원 문법에 한해 추가 확인한다. 새 키가 샘플 파일에 있으면 통과한다. (`drift_gate/core/evaluation/contracts.py`)
- [x] C12 코멘트 전용 변경을 제외하는 강도 기준을 사용하며, 모든 의미 없는 포맷 변경을 정확하게 구별하지는 못한다. (`drift_gate/core/classification/intensity.py`)

## 자체 검사 결과
- [x] C13 Drift Gate 자체 정책 검사는 푸시 변경분과 PR 전체 변경분 모두 pass다. (`scripts/check_self.py`)
- [x] C14 로컬 전체 Python 검증은 874개 통과했고 React 122개가 통과했다.
