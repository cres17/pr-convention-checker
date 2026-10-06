# MCP 입력·출력 계약

stdio의 한 줄이 한 요청 프레임이다. 서버는 UTF-8 바이트 기준 최대 1,000,000바이트(줄 끝 포함)를 읽고, 초과하면 그 줄의 나머지를 제한된 크기로 배출한 뒤 다음 요청을 처리한다.

UTF-8 decode, JSON parse, root/envelope/인자 검증은 요청 단위로 실패한다. 손상 바이트를 치환해 도구를 실행하지 않는다. 잘못된 UTF-8 또는 JSON 한 줄 때문에 뒤의 정상 요청을 잃지 않는다. 정상 요청 전후에 손상 입력을 끼운 별도 프로세스 검사를 유지한다.

JSON-RPC 경로와 기존 `tool/args` 경로를 지원한다. 도구의 signature와 scalar 타입, 알려지지 않은 인자를 실행 전에 검사한다. batch는 지원하지 않는다. 응답은 UTF-8 기준 최대 2,000,000바이트이며 비유한 숫자는 직렬화하지 않는다.

현재 구현은 요청 크기·형식을 제한한다. 도구 전체 실행 시간 제한, 취소 worker, 모든 MCP 표준 기능의 지원을 뜻하지 않는다. 계약 테스트는 `drift_gate/tests/test_mcp_tools.py`에 있다.

## 2026-10-06 응답·경로 보완

유효한 id 없는 JSON-RPC 알림에는 응답하지 않는다. 파싱/인코딩 실패는 JSON-RPC -32700 envelope로 보고한다. 요청의 NaN/Infinity 및 도구 응답 안의 비유한 JSON 숫자를 거부한다. 내부 `content.text` 직렬화에도 `allow_nan=false`를 사용한다.

stdio 서버 시작 시 선택한 repository를 허용 루트로 고정한다. 도구의 policy_path/path/repo_root는 resolve한 경로가 그 안에 있어야 하며 symlink 경유 외부 경로도 거부한다. 읽는 단일 파일은1MB 이하다. 요청 인자로 허용 루트를 넓힐 수 없다. 별도 저장소에는 별도 서버를 시작한다. Python 함수의 직접 호출은 호출자 권한으로 경로를 선택하는 기존 API이며 stdio 서버의 제한 모드와 구분한다.
