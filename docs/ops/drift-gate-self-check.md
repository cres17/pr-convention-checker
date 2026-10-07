# Drift Gate 자체 검사와 패키지 검증

## S1-e 진입점 일치 검사

`test_contract_projection.py`를 Desktop CI 명시 목록에 포함한다. 임시 Git의 동일한
소스·문서를 CLI, local/PR MCP, Desktop 서비스, Action에 전달하고 JSON·HTML·Markdown
projection을 비교한다. GitHub는 이 검사에서 transport만 대체하며 원격 실행 결과가 아니다.
기본 출력 회귀, opt-in diagnostics, compact 생략 표시, no-shadow 입력, invalid proof 실패를
검사한다. Action 입력은 `contract_proofs`이며 기본 false이고 true/false 외 값은 거부한다.

## S1-d 증명 검증

`test_proof_evaluation.py`를 일반 CI와 Desktop의 명시 목록에 포함한다. 세 값 논리의
전수표와 중첩 식, 미사용 leaf의 모든 이진 보완에 대한 근거 충분성, 공유 원자,
범위 유지, 잘못된 참조·진리값·증거 범위·profile·순환·노드/간선/깊이 상한을 검사한다.
같은 경로의 새 내용에 이전 계획을 적용하는 반례, 삭제 env 문서의 잔존 키,
비활성 검사 종류의 직렬화 구별도 회귀로 고정한다. 자체 정책의 pass/unverified를
증명 검증 통과나 parser 건전성으로 해석하지 않는다.

## 논리 검사 회귀 기준

test_logical_contracts.py는 정책 순서·미지원 입력·응답 구조·문서 연결·미결정 집계를 확인한다. test_logical_entrypoints.py는 실제 임시 Git 저장소에서 CLI/MCP/Desktop을 실행하고 GitHub 수집만 대체한 Action과 판정을 비교한다. 두 파일은 데스크톱 빌드의 명시적 검사 목록에도 포함한다. 로컬 통과를 원격 CI나 실기기 설치 검증으로 대신 기록하지 않는다.

## 자체 정책

`.drift-gate.yml`은 웹 프로젝트용 예시로 유지하고 Drift Gate 자체 변경은 `.drift-gate.self.yml`로 검사한다.

```bash
python scripts/check_self.py --base BASE_COMMIT --out build/self-check.json
```

base는 실제 비교할 commit이다. 새 파일을 포함하려면 먼저 Git index에 추가한다. CI는 PR base SHA 또는 push 이전 SHA를 명시적으로 사용한다. 기준이 없거나 유효하지 않으면 오류로 종료하고 다른 기준으로 대체하지 않는다. 소스가 바뀌는 검사와 docs-only 정책 변경은 통제 테스트를 통해 구분한다.

정책은 코드 경로별 계약 문서 갱신을 요구한다. 테스트 파일은 이 요구에서 제외한다. 코멘트 전용 변경을 제외하는 강도 기준을 사용하지만 모든 의미 없는 포맷 변경을 정확하게 구별하지는 못한다. 초기 정책은 보수적인 경로 검사이며 실제 작업에서 불필요한 문서 갱신 요구를 관찰해 조정해야 한다. 관련 없는 리뷰 문서·평가 로그를 계약 문서 대신 인정하지 않는다.

결과에는 gate와 함께 정책 트리거가 일치한 경로와 일치하지 않은 경로를 기록한다. 경로 일치는 의미 검증 완료율이나 버그 탐지율이 아니다. `pass`만 보고 이 목록을 생략하지 않는다. 알려진 자체 운영 경로는 정책 통제 테스트로 지킨다.

## 설치본

desktop-build는 고정 해시와 비교한 파서를 번들링하고, 패키징 후 바이트를 봉인한다. ARM Mac·Intel Mac·Windows에서 패키지 자체를 실행하고 DMG 또는 설치 후 위치에서 다시 실행한다. Windows는 임시 방화벽 규칙을 finally 및 종료 정리에서 제거한다.

오프라인 검사는 빈 파서 캐시와 OS 네트워크 차단에서 화면 렌더링, QWebChannel, 정책 위반, 8개 언어 문법 분석을 확인한다. 프로세스 생존이나 CI 초록색만으로 통과를 대신하지 않는다. `test_git_collection.py`도 패키지 준비 단계의 테스트 목록에 포함돼 있다.

Mac 임시 서명은 Developer ID 서명·공증과 다르다. 로컬 소스 검사·로컬 설치본·원격 CI·공개 릴리스의 완료 상태를 별도로 보고한다. 이번 소스 변경 후 새 설치본·원격 CI를 실행하지 않았다면 그 사실을 명시한다.

## 2026-10-06 자체 검사 보완

`scripts/check_self.py`는 빈 정책·미분류 운영 경로·없는/빈 필수 계약 문서를 입력 오류로 거부한다. 운영 범위는 `source_scope.product_path`에 명시하며 임의 위치의 모든 운영 파일을 자동 식별한다는 보장은 없다. coverage와 evaluator가 rename 경로 역할을 공유한다. 오류 산출물도 실행 ID와 원자적 교체를 사용한다. 내부 예외는 진단 traceback 및 execution_error/종료3으로 남긴다.

CI의 `--trusted-policy-ref ae0028d5edd95d5dd4819939a5801cb028639a6b`는 초기 의무를 고정한다. 기존 규칙 삭제·심각도 감소·실패 개수 증가·ignore 추가·필수 그룹 완화·trigger 축소·강도 기준 상향을 거부하며 trigger 확장과 신규 규칙 추가는 허용한다. 마이그레이션은 이 참조를 검토해 갱신해야 한다. **이는 후보 브랜치의 실행기/workflow까지 신뢰하는 현재 CI의 한계를 없애는 외부 보안 경계는 아니다.** 분리된 신뢰 실행기와 GitHub 필수 검사 발행 통제는 후속 운영 설정이며 이번 커밋으로 완료됐다고 표시하지 않는다.

최종 desktop build는 package/DMG 또는 installer 각각에서8언어 오프라인 파서 분석에 더해 실제 브리지의 signature/rename 반례 검사를 수행한다. 공개 릴리스 게시 없이 같은 커밋의 CI 산출물을 사용한다. 설치본은 ad-hoc 서명이며 공증을 대체하지 않는다.

## 다자 검토 후 재실행 안전성

`verify_package.py --output`은 이미 존재하는 폴더를 거부한다. 과거 JSON·PNG를 덮어쓰지 말고 새 출력 경로를 사용한다. 실행기의 challenge 및 fixture 경로와 일치하는 새 앱 응답만 채택하고, 단계별 실행 ID·순서·시그니처 diff·rename 경로를 확인한다. 무동작 실행 파일과 오래된 성공 보고서, 다른 검사 단계의 결과를 넣는 대조군을 회귀 테스트로 유지한다.

Desktop CI는 다자 검토에서 추가한 core·adapter·CLI 회귀 테스트도 세 플랫폼에서 실행한다. 로컬에서 만든 새 설치본의 검사 결과와 이전에 다운로드한 설치본의 결과, 원격 CI의 실행 상태는 별도 증거로 기록한다.

2026-10-07 auto 개선 회귀와 Express 등록 검사도 Desktop 목록에 포함한다. 일반 CI는 실제 Git 기반의 auto-contracts-v2/express-contracts-v1을 실행하며 네 축(사실·판정·검증 상태·게이트)을 독립 비교한다. Express4.21.2는 테스트 전용 임시 설치이며 설치본 런타임 의존성으로 추가하지 않는다. 네 HTTP oracle은 고정된 테스트 앱만 실행한다. 로컬 실행 성공을 원격 CI 성공으로 표현하지 않는다.

심화 설계의 `test_enterprise_correctness.py`도 Desktop 목록에 포함한다. 혼합 계약의 검사 누락, TypeScript type-only의 주석·공백 변형, JSON 지수 오버플로, 명시적 만료 날짜와 입력 digest, 평가 실행기 입력 오류를 확인한다. `audit_auto_contracts.py`는 비어 있는 suite, 중복 ID, 빠진 기대 축, 잘못된 protocol·결과 값, `.git` 또는 저장소 밖 경로를 실행 전에 종료2로 거부하며 성공 보고서를 쓰지 않는다. 기존 v1/v2 고정 입력과 과거 결과는 바꾸지 않는다.

## 내부 typed facts 검증

S1-a의 `test_typed_facts.py`를 일반 CI 및 Desktop 검사에 포함한다.
unknown과 빈 Exact의 구분, 불변 생성자, 범위/프로필 불일치, 세 사실 universe의 모든
구체 전후 변화, patch 분석의 확정 승격 금지, route API 오류 호환과 env 키 이동을 검사한다.
고정 Git 평가 입력은 유지하며 기존 네 축 결과와 대조한다.
새 타입 도입을 서비스 전체 완전성 증명이나 실제 PR 정확도 개선으로 보고하지 않는다.

## 내부 profile discovery 검증

S1-b의 `test_profile_discovery.py`를 일반 CI와 Desktop 명시 목록에 포함한다.
혼합 계약·미사용 import·설명 문자열·동적 getter·외부 등록·응답의 국소 미지원,
언어/profile 미지원·요청 domain 누락·중복 source·cache의 파일 범위 분리를 검사한다.
신규 metadata 선언만으로 분석기 지원을 가장할 수 없게 통제한다.
고정 Git 평가의 facts/decision/verification/gate를 기존 결과와 비교한다.
discovery의 completeness는 요청한 모듈/profile 부분집합이며 실제 PR 정확도나 서비스
전체 discovery 완전성이 아니다. 기존 auto-strict 호환 결과와 새 domain coverage를 분리한다.

## 내부 obligation planner 검증

S1-c의 `test_obligation_planner.py`를 일반 CI와 Desktop 명시 목록에 포함한다.
설계의 혼합 env/API 6행, unmapped 의무, 문서 수집 누락과 명시 missing의 구분,
다른 모듈의 unknown old getter, 파일 간 키 이동, route/response 동시 의무,
open guard 제거 거부, relation source scope, 실제 legacy shadow 연결을 검사한다.
새 truth와 completeness를 기존 gate와 따로 기록한다. 고정 Git 평가의 기대값과 입력은
유지하며 전 단계 actual과 비교한다. shadow trace의 상한은 진단 보관 상한이며 전체
정책 의무의 처리/인증 상한으로 해석하지 않는다.
## S2-b 원격·설치본 검사

CI는 기존 변경 검사와 함께 immutable `--head "$GITHUB_SHA"` 검사를 실행한다.
기존에 선택한 `ae0028d5edd95d5dd4819939a5801cb028639a6b`의 `.drift-gate.self.yml`을
raw SHA-256 `3b703eaf71d1fbb7ab3a3eea1a704e99912c70344daa1c7a6da7c4ad1f5bf2eb`로 확인한다.
정책 pin은 caller 기준이며 조직 승인이나 checker binary 인증은 아니다.
출력 `object-self-check.json`에는 고정 subject와 원본 해시 근거가 남는다.
native build의 package 및 DMG/Windows 설치 후 검사는 모두 새 Git 객체 대조도 수행한다.
원격 결과와 다운로드한 artifact의 해시·오프라인 JSON은 별도 실행 문서에 기록한다.

native 검증기의 grammar 관찰은 source 8개와 configured 문서 부재 1개다. 문법 적용
확인은 source 8개에 한정하고, 문서 부재는 input capture로 따로 검증한다. signature와
rename도 source 1개·문서 부재 1개를 공통 범위 검사로 확인한다. 통과 boolean이나 총
관찰 수를 언어 분석 수로 오인하지 않으며, 예상 밖 patch 관찰은 실패 처리한다.

원격 회귀 정체를 성공으로 처리하지 않는다. 일반 pytest 단계는 10분, desktop 회귀는
15분으로 제한하고, 각 테스트가 120초 이상 걸리면 Python 스택을 기록한다. Bash의
pipefail로 pytest 종료 코드를 유지하며, tee가 기록한 로그를 성공·실패 모두 별도
artifact로 보관한다. timeout은 실패이며 부분 통과를 전체 통과로 보고하지 않는다.

고정 Git 평가 harness의 입력·결과 JSON은 명시 UTF-8을 사용한다. 결과의 한글 진단도
Windows 기본 cp1252에 맡기지 않고 UTF-8/LF로 보관한다. Windows Python 버전별로
pytest와 그 뒤 네 축 평가의 종료 상태를 따로 확인한다. pytest 통과만으로 workflow가
통과했다고 보고하지 않는다. 고정 suite의 기대값은 인코딩 수정으로 바꾸지 않는다.

같은 pytest 단계에서 임시 고정 CRLF 파일의 path stat·첫 handle·재개방 handle metadata를
기록해 `read-metadata.json`으로 보관한다. 새 bounded read는 같은 API의 identity·size·
mtime·ctime을 비교하고 안정적인 파일을 받아들여야 한다. 기존 path/handle 혼합 비교가
달라지는 필드는 원격 native 관찰로 확인한다. 이 probe는 입력 파일 내용을 한 번 읽는
제품 계약을 바꾸지 않으며 사용자 저장소 대신 임시 fixture만 사용한다.
