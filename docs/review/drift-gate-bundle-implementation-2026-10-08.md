# S2-c: 원본 증거 묶음 영구 저장과 원자적 공개

## 최종 확인 — 2026-10-08 KST

기능 소스는 `79b38614e5c33b44cdd3c53500d4dc03d874012a`다. 후속 공개는 문서·증거만
추가한다. [커밋 원본 대조](../assessment/bundle-implementation-2026-10-08/committed-source-validation.json)는
운영 코드·테스트가 실제 커밋과 같음을 확인한다. 검증 기록 뒤 보고서에 결과를 덧붙여
달라진 MD 1개의 hash도 따로 기록하며, 코드 변경으로 혼동하지 않는다.

| 최종 범위 | 결과 |
|---|---|
| 로컬 전체 Python | 1,805 통과·1 skip (Windows junction 전용) |
| 새 저장 회귀 | 49 통과·1 skip |
| 원격 push·PR CI | 각각 12 job 성공; 각 실행에 3 OS × 3 Python 조합 포함 |
| 원격 회귀 원본 로그 | Linux/Mac 각 1,756 통과·5 skip; Windows 각 1,751 통과·10 skip |
| PR 전체 저장·재실행 | 원격 자체 검사 통과; 실제 artifact 다운로드 뒤 Mac 재검증·재실행도 일치 |
| Desktop CI | Mac arm64·Intel·Windows 3 job 성공 |
| 설치 검사 JSON | 6/6 다운로드 후 기존 native/Git v2 계약으로 재검증 |
| 최초 공개 증거의 fresh clone | 줄바꿈 변환을 켜도 원본 38개 hash 유지; 두 fixture 재실행 일치 |

실행 링크: [push CI](https://github.com/cres17/pr-convention-checker/actions/runs/37708409032),
[PR CI](https://github.com/cres17/pr-convention-checker/actions/runs/37708414124),
[Desktop CI](https://github.com/cres17/pr-convention-checker/actions/runs/37708409007).

[원격 PR 묶음 대조](../assessment/bundle-implementation-2026-10-08/remote-pr-bundle-recheck.json),
[9개 원본 로그와 요약](../assessment/bundle-implementation-2026-10-08/remote-final/regression-summary.json),
[native JSON 대조](../assessment/bundle-implementation-2026-10-08/remote-final/native-recheck.json)를 보존한다.
일반 CI에는 Qt 의존성 부재에 따른 skip, Windows에 지원되지 않는 파일명·OS 전용 조건이
있다. local 전체 숫자를 모든 원격 플랫폼의 실행 수로 옮겨 적지 않는다.

원격 Linux와 현재 Mac의 관찰 producer identity는 다르지만 결과는 같았다. 이것은 현재
엔진 대조이며 인증된 과거 엔진 replay가 아니다. 자체 정책 pass도 내용 verification은
unverified로 유지한다. native JSON 재검증은 CI에서 실행된 기존 UI·8개 grammar·Git
6개 통제를 확인한다. 새 bundle 기능은 CLI/API 경로이며 GUI에는 자동 저장을 추가하지
않았다. 이번에 다운로드한 설치본을 로컬에서 직접 실행하거나 새 공개 릴리스를 게시하지
않았다. 이전 Intel Qt 종료 실패의 원인도 해결됐다고 주장하지 않는다.

## 구현 범위

[심화 설계](../architecture/drift-gate-enterprise-detailed-design-2026-10-07.md)의
8.4 receipt·저장 commit 중 **로컬 불변 묶음 저장**을 구현한다. S2 전체 완료가 아니다.
원본의 장기 보관과 현재 엔진 재실행을 연결하며, latest pointer·외부 게시·retry state
machine·조직 승인·인증된 검증기와 parser 고정 실행은 이 단계에서 구현하지 않는다.

| 코드 | 역할 |
|---|---|
| `adapters/bundle_codec.py` | canonical encoding, snapshot/Git 복원, 승인 정보 거부, 의미 결과 비교 |
| `adapters/evidence_bundle.py` | 파일·총량 한도, private staging, fsync, 공개 rename, receipt 검증 |
| `adapters/snapshot.py` | immutable payload 복원 생성자 |
| `adapters/cli/runner.py` | 명시 저장 옵션, verify/replay 명령, 구조화 오류와 종료 코드 |
| `packaging/check_evidence_bundle.py` | 실제 자체 검사 결과의 receipt pin·디스크 대조·현재 엔진 재실행 |

## 저장 순서와 실패 의미

1. 결과의 입력 snapshot binding과 retained shadow proof를 확인한다.
2. 입력·정책·Git 원본·결과·receipt의 bytes와 개수 한도를 확인한다.
3. 같은 store filesystem의 `.pending-*` directory에 파일을 exclusive 생성한다.
4. 원본·receipt·commit marker를 fsync하고 디스크에 쓴 모든 파일을 재검증한다.
5. receipt hash 이름의 directory로 한 번 rename한다. 기존 묶음은 덮어쓰지 않는다.
6. 가능한 OS에서 parent directory도 fsync한 뒤 reference를 반환한다.

marker만으로 공개를 추정하지 않는다. directory 이름과 receipt SHA-256, 전체 inventory를
함께 확인한다. 공개 이전 강제 종료의 staging은 재실행 입력으로 인정하지 않는다.
공개 직후 process 종료는 전체 묶음을 다시 읽을 수 있어야 한다. 이 시험은 전원 장애나
모든 filesystem의 durability를 증명하지 않는다. Windows에는 directory fsync 보장이 없다.

## 저장과 판정의 경계

verify는 저장 bytes와 입력 binding의 무결성 검사다. 의미적 진위·조직 승인 인증은 아니다.
자기 일관적인 가짜 결과를 만들고 receipt까지 다시 계산하는 대조군은 integrity를
통과할 수 있다. 현재 엔진 재실행은 그 가짜 결과와 다름을 표시하며, 독립 보관한 원래
receipt hash를 pin하면 무결성 단계에서도 거부한다. 둘을 같은 증명으로 취급하지 않는다.

원문에는 민감한 값이 포함될 수 있어 기본 저장은 끄고 명시 경로만 사용한다. 보관 기간은
사용자가 해당 store를 삭제할 때까지다. 자동 삭제·업로드는 없다. 승인 검증 flag가 있는
waiver는 unsigned disk replay에서 다시 신뢰하지 않으므로 v1 저장·복원을 거부한다.

## 사용

```sh
drift-gate check --base BASE --head HEAD \
  --trusted-policy-ref POLICY_COMMIT --trusted-policy-sha256 POLICY_SHA256 \
  --evidence-store .drift-gate-evidence --json
drift-gate bundle verify .drift-gate-evidence/bundles/RECEIPT_SHA256 --json
drift-gate bundle replay .drift-gate-evidence/bundles/RECEIPT_SHA256 --json
```

placeholder 값은 실제 고정 commit/hash로 치환한다. 현재 엔진 재실행이 같으면 gate
종료 코드 0/1을 유지하고 다르면 2다. verify 성공은 원래 gate pass를 뜻하지 않는다.
history/LLM 보강 전 기본 결과만 저장하며 외부 출력에서 그 범위를 표시한다.

## 검증 기록

| 실제 실행 | 결과 |
|---|---|
| 로컬 Mac 전체 Python | 1,804 통과·1 skip; skip은 Windows junction 전용 통제 |
| 새 bundle 회귀 | 48 통과·1 skip |
| Ruff E9,F·문서 정합성·diff 공백 | 통과 |
| 고정 Git Python 계약 14건 | facts·decision·verification·gate 각 14/14 |
| 고정 Git Express 계약 8건 | 네 축 각 8/8 |
| 실제 디스크 stale/current fixture | fail/pass 유지; 저장소 삭제 뒤 동일 재실행, CRLF 보존 |
| 고정 입력 5개 | 기존 SHA-256과 일치 |

[근거 폴더](../assessment/bundle-implementation-2026-10-08/)에 실제 portable 묶음 2개와
전체/개별 테스트 로그, 입력 hash, 프로브를 보존한다. 위 Git fixture는 작성자 구성 사례이며
실제 PR 정확도나 기존 auto 경계 1/8의 개선을 의미하지 않는다. 첫 전체 실행의 Express
4건은 sandbox의 `listen EPERM 127.0.0.1`로 실패했고, 로컬 서버 실행을 허용한 동일
전체 검사로 통과했다. 실패 로그를 지우지 않았다.

운영 UI는 바꾸지 않아 React를 이번에 다시 실행하지 않았다. 원격 OS/Python 결과와
새 설치본 실행은 이 로컬 결과로 완료 처리하지 않는다. 원격 확인은 후속 기록에 구분한다.

## 다음 단계

- 실행·취소·재시도와 외부 게시의 최신성 계약.
- 조직 승인 envelope와 신뢰 검증기·parser artifact 인증.
- Git 수집 전체의 bytes·호출 수·wall time 예산.
- 이전 Intel Qt 종료 실패 원인 진단, 새 저장 기능을 포함한 native 검증.
- 독립 평가와 dependency closure·schema 분석 확장.

## 최초 원격 검증에서 발견한 보완 (2026-10-08)

`74a6e47`의 push 자체 검사·Linux/Mac 회귀는 통과했지만 PR 자체 검사와 Windows
회귀가 실패했다. 완료로 처리하지 않고 실패 로그를 별도로 보존한다.

- PR 전체 입력은 총 125,172,523 bytes, 가장 큰 capsule은 61,752,569 bytes, 파일은
  3,688개였다. 초기 총 64MB·개별 8MB 한도는 실제 저장소 규모를 반영하지 못했다.
  총 256MB·개별 64MB로 보완하며 파일 개수 4,096개와 reader 강제 한도는 유지한다.
  실제 전체 PR을 저장·재검증·재실행해 확인한다. 이 숫자는 동시 process 메모리 한도가 아니다.
- Windows의 bundle 운영 회귀는 통과했으나 `.git` 삭제 fixture가 read-only loose object를
  지우지 못해 실패했다. 임시 Git fixture의 PermissionError만 권한을 고쳐 재시도하고,
  `.git`가 실제로 사라진 것을 확인한 뒤 replay한다. 실패를 skip하거나 저장소 삭제를
  생략하지 않는다. Windows junction 통제도 원격에서 통과했다.

보완 후 로컬 전체 Python 1,805 통과·1 skip, bundle 49 통과·1 skip이다. 기존 원본
로그와 source hash를 덮어쓰지 않고 `*-capacity-fix.*`와
[보완 검증](../assessment/bundle-implementation-2026-10-08/capacity-fix-validation.json)에
기록한다. 전체 PR의 실제 묶음 저장·원본 검증·결과 재실행도 통과했다. 약 125MB의
원문을 다시 Git에 넣지는 않고 고정 Git subject와 결과·receipt digest를 기록했다.
작은 authored fixture의 원문 묶음 2개는 그대로 Git에 보존한다.
