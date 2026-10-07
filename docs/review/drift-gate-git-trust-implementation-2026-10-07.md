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

원격 Mac 대기 중 같은 소스로 임시 native 앱도 만들었다. 앱 내부의 세 scan 단계와
Git 대조 6건은 통과했지만 외부 validator도 grammar source 8개에 문서 부재 관찰을
섞어 9개를 문법 분석으로 잘못 비교했다. 공통 `validate_observation_scope`로 내부·외부
검사를 통일했다. 8개 문법 분석과 문서의 명시 부재를 별개로 검사하며 다른 관찰은
거부한다. 최종 임시 앱은 외부 통신 차단·빈 파서 캐시에서 화면·브리지·8개 언어와
Git 대조 6/6을 통과했다. 이는 원격 installer 다운로드 검증과 구별한다.
[임시 native 결과](../assessment/git-trust-implementation-2026-10-07/local-native-result.json)를
보존했다. 최종 외부 validator와 같은 수정 상태에서 전체 Python 1,739개가 통과했다.

`7bf680d`의 원격 Mac 두 플랫폼은 앱·DMG 검사 모두 통과했고, 다운로드한 JSON 4건도
재검증했다. 원격 arm64 DMG를 이 컴퓨터의 임시 설치 위치에 복사하고 DMG를 해제한 뒤,
새 challenge·빈 캐시·OS 외부 통신 차단으로 실행해 통과했다. Git 대조 6/6과 실제 문법
분석 8개를 확인했다. [다운로드 설치 앱 실행 영수증](../assessment/git-trust-implementation-2026-10-07/downloaded-arm64-execution.json)에
원격 artifact ID, source commit, DMG와 executable 해시를 연결했다.

같은 커밋의 일반 CI와 Windows 회귀는 30분 가까이 종료되지 않았다. API에서 실행 중
로그와 종료된 이전 로그를 받지 못했다. 원인을 인프라로 단정하지 않는다. Mac의
얕은 원격 체크아웃·최소 dev/oracle 환경에서는 1,690개 통과·4개 skip으로 36초에 끝나
같은 정체를 재현하지 못했다. 원격 판정을 통과로 바꾸지 않고 pytest 단계 시간 제한,
120초 per-test 스택 덤프, pipefail과 항상 보관하는 진단 로그를 워크플로에 추가했다.
[조건 대조와 파이프 종료 코드 확인](../assessment/git-trust-implementation-2026-10-07/ci-diagnostic-controls.json)을
보존했다. 새 원격 실행의 결과는 완료 후 별도 영수증에 기록한다.

진단 설정을 포함한 `f712dfd`의 Mac arm64는 회귀 1,111개와 앱·DMG 오프라인
검사를 통과했다. 새 DMG를 직접 다운로드해 임시 설치 위치에 복사하고 DMG를
해제한 뒤, 새 challenge·빈 캐시·OS 통신 차단으로 실행해 통과했다. 문법 분석
8개, Git 원본·정책 대조 6/6을 확인했다. [최신 다운로드 실행 영수증](../assessment/git-trust-implementation-2026-10-07/final-downloaded-arm64-execution.json)에
소스 commit과 artifact·DMG·executable 해시를 연결한다.

이 진단 commit의 자체 객체 검사는 새로 보관한 pytest 로그 1,207,220 bytes를
1,000,000 bytes 수집 상한 위반으로 거부했다. 로그를 gzip으로 바꾸고 원본 bytes와
SHA-256의 일치를 확인했다. 제품의 상한을 완화하지 않았다. 이전 큰 blob을 포함한
비교도 여전히 거부되며 이 실패는 [거부 영수증](../assessment/git-trust-implementation-2026-10-07/self-check-input-limit-rejection.json)에
보존한다. 압축본의 원본 해시·복원 검증은 `ci-diagnostic-controls.json`에 남겼다.

일부 상태 조회가 종료 API와 어긋나 별도 조회 URL로 상태를 교차 확인했다.
또 [GitHub 공식 상태](https://www.githubstatus.com/)에는 같은 날 15:06–15:16 UTC
여러 서비스 영향과 15:32 UTC Actions 정상화가 공지됐다. 이 저장소의 정체 원인과
직접 연결되는 로그는 확보하지 못했으므로 인과관계는 주장하지 않는다.
[중간 원격 영수증](../assessment/git-trust-implementation-2026-10-07/remote-verification-checkpoint.json)은
Windows·전체 CI를 명시적으로 pending으로 기록한다. 최종 성공으로 대체하지 않는다.

## 추가 반례와 격리 수정 (2026-10-08 KST)

같은 base/head를 검사하면서 working tree의 `.gitattributes`만 바꾸자 판정은 fail로
유지됐지만 verification은 verified에서 unverified로 바뀌고 snapshot도 달라졌다.
원본 Git evidence는 같았다. Git은 commit 사이의 diff에서도 작업 폴더, index fallback,
`info/attributes`, 전역 속성을 참조한다([공식 문서](https://git-scm.com/docs/gitattributes)).
초기 구현의 `working_tree_ignored` 주장에는 이 예외가 있었다.

수정은 source object directory만 읽는 별도 임시 bare Git 저장소에서 diff를 만드는
것이다. 임시 저장소는 빈 template과 고정 locale로 만들고 caller Git 환경, global·system
config를 배제한다. 원래 저장소의 index·config·objects는 쓰지 않는다. 이 모드에서는
커밋된 `.gitattributes`도 raw object 비교에 적용하지 않는다. 일반 로컬 검사 경로에는
이 변경을 적용하지 않는다. working/index/info/global 속성과 local diff config 5개,
caller Git 환경 3개의 회귀를 추가했다. snapshot·Git evidence·verification이 모두
같고 source index·config bytes가 바뀌지 않는지 검사한다.

설치본의 Git 진단 계약도 `packaged-git-controls-v2`로 강화했다. 기존 6개 대조 중
working-tree 대조에 index/info 속성과 diff config 변형을 넣고, 입력 capture와
verification의 일치를 함께 검사한다. 과거 v1 JSON은 새 계약의 증거로 인정하지
않으며, 거부하는 회귀를 추가했다. 과거 다운로드 설치본 결과는 당시 계약의 근거로
보존한다. 새 소스 설치본의 결과를 대신하지 않는다.

별도 Linux amd64 컨테이너에서 초기 테스트는 1,689 통과·4 skip·1 error였다.
1 MB 입력을 pytest 사례 이름으로 자동 노출해 `PYTEST_CURRENT_TEST` 환경변수가
커졌고, Git 생성이 `Argument list too long`으로 실패했다. 입력은 1,000,001 bytes로
유지하고 사례 이름만 `binary`·`oversized`로 고쳤다. 같은 Linux 환경의 격리 prototype은
1,698 통과·4 skip으로 끝났다. 이 Linux 실행은 GitHub runner가 아니며, 진단 schema v2,
빈 template·locale 고정 전 소스임을 별도 source hash로 기록한다. 최종 현재 소스는
Mac 전체 1,748개 통과·skip 0, Ruff·공백 검사 통과다. [반례·수정·소스 영수증](../assessment/git-trust-implementation-2026-10-07/attribute-isolation/verification.json)을
보존했다. Linux 첫 오류의 raw log는 원본 SHA-256을 유지한 gzip으로 보관한다.

이 오류는 실제 재현한 회귀 테스트 결함이다. 원격 정체 전부의 원인이라고 단정하지
않는다. 최종 소스의 새 원격 회귀와 v2 설치본 검증 결과는 아래에 별도로 기록한다.
