# S2-c: 원본 증거 묶음 영구 저장과 원자적 공개

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
