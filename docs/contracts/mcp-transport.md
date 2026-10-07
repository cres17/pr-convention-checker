# MCP 입력·출력 계약

## S1-e proof 진단 opt-in

`drift_gate_check_local/pr`에 boolean `contract_proofs`를 추가한다. 기본 false다.
문자열 `'true'`는 서버 입력 오류이며 JSON boolean을 전달해야 한다. full은 공통
`contract_diagnostics`와 전체 증명을 전달하고 compact는 같은 projection만 전달한다.
compact의 `full_proofs_omitted=true`는 raw 증명이 없다는 뜻이다. 응답 축소 시 entries를
생략하면 `display_truncated=true`, `omitted_entry_count`를 표시한다. 수집·보관 생략
개수와 `complete_policy_coverage=false`는 유지하며 표시 생략을 검증 완료로 해석하지 않는다.
기존 토큰 예산은 대략적 축소 기준이며 응답 전체의 엄격한 크기 보장은 아니다.

## 논리 검사 schema 3

full·compact 모두 검사 출력 schema_version=3, verification과 미결정/미검증 규칙 수를 유지한다. compact의 verification_limits는 규칙별 판정·검증 상태·미검증 이유를 토큰 예산 축소에서도 제거하지 않는다. status=undetermined는 확인된 위반과 구분하며 on_unverified=fail이면 위반 수 0이어도 게이트가 fail일 수 있다.

로컬·PR 검사와 근거 조회는 공통 inspection 서비스를 사용한다. 입력 digest는 before/after 원문의 해시도 포함하며 원문은 출력하지 않는다. 정책 목록·설명에는 그룹 content와 교차 조건, on_unverified를 포함한다. api-schema PR 원문은 고정 merge-base/head에서 읽으며 실패 시 파일 조건으로 대체하지 않는다.

stdio의 한 줄이 한 요청 프레임이다. 서버는 UTF-8 바이트 기준 최대 1,000,000바이트(줄 끝 포함)를 읽고, 초과하면 그 줄의 나머지를 제한된 크기로 배출한 뒤 다음 요청을 처리한다.

UTF-8 decode, JSON parse, root/envelope/인자 검증은 요청 단위로 실패한다. 손상 바이트를 치환해 도구를 실행하지 않는다. 잘못된 UTF-8 또는 JSON 한 줄 때문에 뒤의 정상 요청을 잃지 않는다. 정상 요청 전후에 손상 입력을 끼운 별도 프로세스 검사를 유지한다.

JSON-RPC 경로와 기존 `tool/args` 경로를 지원한다. 도구의 signature와 scalar 타입, 알려지지 않은 인자를 실행 전에 검사한다. batch는 지원하지 않는다. 응답은 UTF-8 기준 최대 2,000,000바이트이며 비유한 숫자는 직렬화하지 않는다.

현재 구현은 요청 크기·형식을 제한한다. 도구 전체 실행 시간 제한, 취소 worker, 모든 MCP 표준 기능의 지원을 뜻하지 않는다. 계약 테스트는 `drift_gate/tests/test_mcp_tools.py`에 있다.

## 2026-10-06 응답·경로 보완

유효한 id 없는 JSON-RPC 알림에는 응답하지 않는다. 파싱/인코딩 실패는 JSON-RPC -32700 envelope로 보고한다. 요청의 NaN/Infinity 및 도구 응답 안의 비유한 JSON 숫자를 거부한다. 내부 `content.text` 직렬화에도 `allow_nan=false`를 사용한다.

stdio 서버 시작 시 선택한 repository를 허용 루트로 고정한다. 도구의 policy_path/path/repo_root는 resolve한 경로가 그 안에 있어야 하며 symlink 경유 외부 경로도 거부한다. 읽는 단일 파일은1MB 이하다. 요청 인자로 허용 루트를 넓힐 수 없다. 별도 저장소에는 별도 서버를 시작한다. Python 함수의 직접 호출은 호출자 권한으로 경로를 선택하는 기존 API이며 stdio 서버의 제한 모드와 구분한다.

## 다자 검토 후 검사 결과 계약

MCP의 로컬/PR 검사와 근거 조회·수정 계획은 규칙이 없는 정책을 정상 pass로 반환하지 않는다. 정책 목록 조회는 설정 기능이므로 빈 목록을 허용한다.

검사 응답의 `execution`은 실행 ID, 정책 digest, 입력 digest와 출처를 포함한다. 로컬 Git 검사는 비교 기준·snapshot·dirty·`untracked_skipped` 및 총 개수를 보존한다. compact 응답은 큰 생략 목록을 줄일 수 있지만 실행 ID와 생략 총 개수를 제거하지 않으며 목록을 줄였다는 표시를 남긴다. PR 출처는 저장소·PR 번호로 표시하며 수집하지 않은 head SHA를 보장한다고 주장하지 않는다.
## S2-b immutable Git 도구

`drift_gate_check_git`은 `base`, `head`, `trusted_policy_ref`,
`trusted_policy_sha256`을 필수 문자열로 받는다. 저장소 상대 `policy_path`,
`comparison_mode`, `mode`, `token_budget`, boolean `contract_proofs`를 선택할 수 있다.
서버 고정 저장소 안의 Git 객체에서만 읽으며 working-tree 정책 파일의 존재·크기로
Git 정책 입력을 대체하지 않는다. 조직 승인이나 외부 checker 인증은 하지 않는다.
full 출력은 원본 artifact 해시와 subject OID를 포함하고 compact는 전체 manifest digest,
artifact 개수·생략 표시를 유지한다. 원문 bytes는 응답에 넣지 않는다.
