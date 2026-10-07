# S2-b: 원본 Git 객체 수집과 명시 정책 pin 검증

## 구현 범위

base, head, 정책 ref를 먼저 commit OID로 고정하고, 원본 blob과 방문한 tree bytes를
읽는 선택형 수집 경로를 추가했다. Git replace refs, working tree, 미추적 파일,
미저장 버퍼는 이 모드의 입력에 포함되지 않는다. 기본 로컬 검사 경로는 유지한다.

원본 bytes의 Git object ID와 SHA-256, 경로·revision·파일 mode·수집 상태를 묶는다.
CRLF는 보존하고 rename의 이전 경로와 삭제된 파일의 명시 부재를 기록한다.
symlink와 submodule은 따라가지 않는다. 원본은 메모리에서 보관하며 공개 결과에는
OID와 해시를 담는다. 기존 문자열 capsule과 별도의 Git evidence digest를 결합해
평가 문자열과 고정 정책이 실제로 수집한 bytes에서 왔는지 검사한다.

신뢰 정책은 호출자가 지정한 ref와 **기대 SHA-256**으로 선택한다. 후보 정책의 약화는
거부하고 실제 평가에는 고정 정책을 적용한다. 후보가 더 강해졌어도 자동으로 평가
정책을 교체하지 않는다. 이는 명시 pin의 무결성 검증이며 **조직 승인 검증은 아니다**.
`organization_approval_verified=false`, `checker_authority=current-engine-not-attested`를
유지한다. 브랜치 보호·서명·외부 신뢰 검사 엔진은 별도 단계다.

## 운영 경계

| 경계 | 구현 |
| --- | --- |
| 순수 core 모델 | GitArtifact·GitSubject·GitInputEvidence, 원본 bytes와 OID 검증 |
| Git adapter | ref 고정, 원본 객체 읽기, 정책 pin·약화 검사, immutable snapshot 생성 |
| CLI | `check/report --head`, `--trusted-policy-ref`, `--trusted-policy-sha256` |
| MCP | 별도 `drift_gate_check_git`, compact에서 목록 생략·digest 보존 |
| CI | 기존 자체 검사에 더해 고정 역사 정책의 ref·해시로 실제 커밋 객체 검사 |
| 설치본 | 네트워크 차단 상태에서 앱 내부의 실제 Git 객체 대조 6건 실행 |

파일당 1 MB, tree 20,000개 entry, patch 256 KB 제한을 둔다. 분석하지 못한 입력을
verified 성공으로 바꾸지 않는다. 다중 merge-base는 입력 오류로 거부한다.
수집 범위는 변경 경로와 설정한 문서 관찰이며 모든 서비스 의존성의 완전한 폐쇄가
아니다. 공개 목록만으로 원본을 복구하는 디스크 증거 bundle도 아직 제공하지 않는다.

## 로컬 검증

[근거 폴더](../assessment/git-trust-implementation-2026-10-07/)에 실패 로그와
수정 후 결과를 함께 남겼다. 작업 시작 때 S2-a 소스 280개와 고정 입력 5개가 이전
영수증과 같음을 확인했다. 기존 평가 입력과 이전 근거는 덮어쓰지 않았다.

| 검사 | 결과 |
| --- | --- |
| Python 전체 | 최초 1,736, 설치 검증 수정 후 1,739 통과, skip 0 |
| React | 126 통과, 11개 파일 |
| TypeScript·UI 빌드·Ruff E9,F | 통과, 기존 큰 chunk 경고 유지 |
| Python/Git 고정 대조 | 14/14, 사실·판정·검증·gate 네 축 유지 |
| Express/Git 고정 대조 | 8/8, 네 축 유지 |
| 기존 고정 합성 평가 | 21/21, baseline 조건 통과 |
| 설치본용 대조의 소스 실행 | 6/6 |

회귀는 실제 임시 Git 저장소를 사용한다. ref가 수집 중 이동하는 경우, commit/blob
replace ref, 잘못된 해시, 정책 완화, rename·삭제·symlink, binary·크기 제한,
SHA-256 Git 저장소, 원본·manifest 치환, CLI/MCP 결과 연결을 포함한다.
설치 검증기는 통과 boolean만 보지 않고 고정 fixture의 정책 해시, base/head,
CRLF 원본 SHA-256과 blob OID를 확인한다. 거짓 통과·잘못된 원본 해시도 거부한다.

초기 설치 검증 회귀 한 건은 예전 가짜 성공 응답에 새 Git 검사 필드가 없어서
실패했다. fixture를 실제 대조 결과로 갱신했다. 이를 운영 실패로 숨기거나 기대
판정을 바꿔 통과시킨 것은 아니다. 첫 실패 로그를 보존한다.

운영 코드·테스트·워크플로·계약 문서의 commit diff 공백 검사는 통과했다. 함께 올린
과거 실행 로그에는 pytest가 출력한 끝 공백이 있고, 과거 Markdown 일부에는 줄바꿈용
끝 공백이 있다. 기존 근거 해시를 보존하기 위해 그 bytes는 정리하지 않았다.

## 원격·설치 파일 확인

이 문서의 최초 작성 시점에는 원격 CI와 이번 설치 파일을 검증하기 전이다.
완료 결과는 이 폴더의 별도 원격 영수증과 이 절에 기록한다. 로컬 소스 실행을
설치본 성공으로 취급하지 않는다. 작성자 대조·회귀가 PR 정확도나 독립 홀드아웃을
대신하지 않는다. 과거 auto 경계 1/8의 개선을 주장하지 않는다.

첫 원격 설치본 실행(`92f9ae7`, run `37636470221`)은 signature 단계에서 실패했다.
새 입력 수집은 source 1개에 설정 문서의 부재 관찰을 더하므로 `scanned_files=2`인데,
기존 진단 계약이 변경 파일 수와 같은 1을 요구했다. 동일 source 경로·정확한 diff와
문서의 부재를 검사하도록 진단 계약을 수정했다. 다른 관찰의 유입은 계속 거부한다.
실제 단계 준비 함수와 desktop scan을 연결한 회귀도 추가했다. 재현 입력에 대해
옛 validator는 실패하고 수정한 validator는 통과했으며, 전체 1,739개가 통과했다.
[원격 첫 오류](../assessment/git-trust-implementation-2026-10-07/first-arm64-package-error.json)와
[소스 재현](../assessment/git-trust-implementation-2026-10-07/package-scope-reproduction.json)을
보존했다. 원격 재실행의 최종 결과는 아래에 기록한다.
