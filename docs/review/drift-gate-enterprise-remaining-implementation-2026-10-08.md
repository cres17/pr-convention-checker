# 심화 설계 남은 항목 5~23 구현 (W05·W07~W17)

2026-10-08 KST · 기준 `b5c52ab`(원격 `ver2`) 위 커밋 `5cd00ed`~`3c7d463`와 이 보고서 커밋 · 원격 CI는 push 후 확인

[심화 설계](../architecture/drift-gate-enterprise-detailed-design-2026-10-07.md)의 남은 항목 목록 중 1~4번은
[실행 수명주기 보고서](drift-gate-run-lifecycle-implementation-2026-10-08.md)에 있다. 이 보고서는 5~23번을 다룬다.
12·13번은 사람 검토 대신 LLM 검토를 쓰기로 했으므로 도구와 절차만 구현했고 평가 수치는 없다.
22·23번은 설계의 선행 조건을 확인하지 않고 구현하기로 결정한 항목이다.

## 항목별 구현

| # | 항목 | 코드 | 보장 | 보장하지 않는 것 |
|---|---|---|---|---|
| 5 | 신뢰 검증기와 후보 분리 (W09) | `core/trust/validation.py`, `adapters/engine_artifact.py`, `adapters/trusted_validation.py`, CLI `engine`·`trusted-check` | manifest SHA-256으로 pin한 commit의 엔진을 별도 `python -I`에서 실행. 후보 결과는 shadow. module·grammar 해시 불일치면 merge 근거 없음 | interpreter 검증, sandbox. 자식은 같은 기계의 파일·네트워크를 쓴다 |
| 6 | 면제 승인 인증 (W09) | `core/trust/approvals.py`, `adapters/github/approvals.py`, `adapters/approval_signing.py`, `bundle_codec.require_replayable` | rule·경로·head·정책 digest·기간에 묶인 envelope만 인정. 저장 묶음은 HMAC 서명 확인 시에만 면제 재인정 | 공개키 서명, 승인자 신원 확인. 공유 키 보유자는 누구나 서명 가능 |
| 7 | 인증된 엔진 재실행 (W07/W09/W15) | `trusted_validation.certified_replay`, `bundle replay --engine-manifest` | 저장 입력을 pin한 엔진으로 재평가하고 attestation 기록 | 원래 실행 환경(OS·interpreter)의 재현 |
| 8 | NoDeltaCertificate (W05/W11) | `core/contracts/certificates.py`, `adapters/scope_analysis.py` | 서비스 전체 module을 양쪽 revision에서 읽고 열린 경계·모호 소속·identity 변화가 없을 때만 발급 | 선택 파일 집합의 빈 변경을 인증서로 승격하지 않음 |
| 9 | must/may 문서 membership (W05/W08) | `core/evaluation/membership.py`, `obligations._document_outcome` | 구간 `lower ⊆ actual ⊆ upper`에서 모든 해석이 같을 때만 T/F | 구간 간 상관을 쓰지 않아 일부 결정 가능 사례가 U |
| 10 | 증거 byte 범위 (W07/W08) | `core/evaluation/evidence_spans.py`, `adapters/evidence_spans.py`, `bundle spans` | 원본 SHA-256과 `[start,end)`를 경계·구문 재parse로 검증 | 분석기 해석이 맞다는 증명 |
| 11 | proof → gate 전환 | `core/evaluation/proof_gate.py`, `migrate proof-gate` | `gate.proof_gate: v1`일 때만 proof DAG가 판정. U를 pass로 바꾸지 않음 | 기존 정책의 자동 전환 |
| 12 | holdout (W10) | `core/evaluation_stats.py`, `adapters/holdout.py`, `holdout split·freeze·run·packet` | family 단위 분할, 동결·pin, 덮어쓰기 금지, blind packet | 사례 수집. 저장소에 holdout 사례 없음 |
| 13 | 제3자 검토·통계 (W10) | `holdout adjudicate·score`, [평가 절차](../ops/holdout-evaluation.md) | human·llm-proxy label 분리, Cohen's kappa, Wilson 95% 구간 | 검토자 종류 확인. 선언을 그대로 기록 |
| 14 | 설치본 새 기능 검증 (W16) | `desktop/cli_entry.py`, `packaging/verify_package_cli.py`, desktop-build workflow | dist·DMG·설치된 Windows 앱에서 증거 저장·검증·저장소 삭제 후 재실행·spans·run journal 확인 | 이 보고서 작성 시점의 원격 실행 결과(push 후 확인) |
| 15 | Intel Qt 종료 실패 진단 (W16) | `DRIFT_GATE_TEARDOWN_TRACE`, `packaging/teardown_diagnosis.py` | 반복 실행의 종료 코드·마지막 event·faulthandler stack 기록 | 원인 확정이나 수정. 관찰 도구다 |
| 16 | 의존 그래프 영향 (W11) | `core/contracts/dependency.py` | 정적 import 그래프, 동적·미해석 import는 열린 경계, Gbefore ∪ Gafter 역방향 도달 | 동적 import 해석, 저장소 밖 package의 계약 |
| 17 | 서비스·진입점 identity와 env key (W11) | `core/contracts/services.py`, 정책 `services` | `(service, entrypoint, METHOD, path)`·`(service, KEY)`, 모호 소속은 병합하지 않음 | 경로 glob 밖의 서비스 경계 추론 |
| 18 | 전체 검사 자원 예산 (W12) | `core/budget.py`, 정책 `budget`, `git/immutable.py` | 파일·bytes·Git 호출·시간·graph edge·보고서 bytes 초과 시 `resource_limit`로 종료 | 서비스 수준 보장. 기본값은 이 저장소 측정치 기반 |
| 19 | 분석 worker 격리 (W12) | `adapters/analyzer_worker.py`, `scope --isolated-workers` | 별도 process·process group kill·OS 제한·audit hook, 설정 못한 제한 보고 | OS sandbox. audit hook은 native 코드를 막지 못함 |
| 20 | typed trigger와 전환 (W13) | `core/classification/triggers.py`, `migrate typed-trigger` | family·predicate·magnitude 구간으로 T/F/U, U는 `on_unknown`으로만 처리 | `selected-modules` 외 scope |
| 21 | schema 호환성·방향 (W14) | `core/evaluation/compatibility.py`, `content: api-compatibility` | 엄격한 JSON Schema 포함, 지원 밖은 U | 실제 소비자의 관대한 처리 |
| 22 | 조직 서비스 (W17) | `core/org/policy.py`, `adapters/org_service.py`, `org` | tenant·역할·저장소 범위 인가, quota, 보존 purge, hash chain 감사, pin 확인 backup/restore | 인증, network 서비스, 다중 writer 동시성 |
| 23 | 지속 분석 캐시 | `adapters/analysis_cache.py`, `scope --cache-dir` | content-addressed, 완료·결정적 거부만 저장, 변조 시 miss | 승인 context·자원 제한 칸은 현재 고정값 |

core에는 시각·파일·네트워크·subprocess 호출이 없다. 시간·저장·프로세스는 adapter가 공급한다.

## 독립 검토와 반영

문서를 쓴 뒤 작성 과정을 보지 않은 별도 agent가 다섯 계약 문서의 주장을 코드와 대조했다. 17건의 불일치·과장을 보고했고
다음과 같이 처리했다.

- 코드 수정: grammar pin 불일치가 merge 근거로 남던 문제(attestation에 `parsers.matched` 요구), CI가 merge 근거 없는 review를
  경고로 통과시키던 문제, guard가 `direction` 축소를 허용하던 문제, holdout pin이 선택이던 문제, resolution·변경 파일 필드
  미검증, CLI 오류 경로가 holdout·engine `--out` 산출물 위치에 오류 JSON을 쓰던 문제(덮어쓰기 금지 위반).
- 문서 수정: 제거 환경 변수 목록, `suppression.require_codeowners_approval` 위치, 서명 없는 면제가 든 묶음 전체 거부, `scope`의
  예산 초과 보고 형태, 캐시 key의 고정 칸, `create-tenant` 무인가 초기 생성, `store`의 원문 저장 책임, 지표 분모, 추적 시각 단위.
- 추가 수정: 정책 `budget.max_memory_bytes`가 worker에 전달되지 않던 문제. 이제 worker 주소 공간 제한으로 쓰이고, worker가
  설정하지 못한 제한은 `worker_limits_unapplied`로 보고된다.

## 검증

| 검사 | 결과 | 근거 |
|---|---|---|
| 전체 pytest (Linux 컨테이너, Python 3.11.17, `3c7d463`) | 1,868 통과, 12 건너뜀 | [full-suite.log](../assessment/enterprise-remaining-implementation-2026-10-08/full-suite.log) |
| ruff `E9,F` (`drift_gate/ packaging/ scripts/`) | 통과 | [ruff.log](../assessment/enterprise-remaining-implementation-2026-10-08/ruff.log) |
| 자체 정책 검사 (`b5c52ab`..`3c7d463`) | pass, 위반 0 | [self-check.json](../assessment/enterprise-remaining-implementation-2026-10-08/self-check.json) |
| immutable 검사 + 저장 묶음 재실행 | 재실행 결과 일치 | [bundle-replay-summary.json](../assessment/enterprise-remaining-implementation-2026-10-08/bundle-replay-summary.json) |
| 신뢰 엔진 대조 (`ed9f904`, manifest `88f275f5…e37e8`) | 신뢰 pass, 후보 pass, review(검사기 변경) | [trusted-check.json](../assessment/enterprise-remaining-implementation-2026-10-08/trusted-check.json) |
| 패키지 CLI 검증기 | `--cli` 진입 wrapper로 4단계 통과(테스트) | `test_packaged_cli.py` |
| 호환성 판정 독립 oracle | 테스트 통과. 별도 12 seed 18,000쌍 실행에서 불일치 0(로그 미보존) | `test_decision_models.py`. oracle 문법에 union이 없어 U 판정은 0건이며 union 경로는 이 대조로 검증되지 않음 |

건너뛴 12개는 컨테이너에 PySide6(4), Express 4.21.2 대조 설치(4), zstandard(3)가 없고 Windows junction 시험(1)이 Linux에서
제외되어 생긴 것이다. 설치본 검증(14)과 종료 진단(15)은 Desktop
workflow에서만 실행되며, 이 표에는 아직 결과가 없다. macOS·Windows 단위 테스트도 push 후 CI 결과로 확인한다. 로컬 Linux 통과를
다른 OS 검증으로 승계하지 않는다.

## 남은 한계

- 신뢰 엔진 대조는 후보 코드가 설치된 runner에서 실행된다. 신뢰 경계가 되려면 후보 코드가 없는 별도 job·runner가 필요하다.
- 면제 서명은 공유 키 HMAC이다. 키 관리와 승인자 신원 확인은 조직 설정에 달려 있다.
- worker 격리는 Linux에서 가장 강하다. macOS는 memory 제한이 없고 Windows는 OS 제한과 process group kill이 없다.
- holdout 사례와 사람 label이 없다. LLM label 지표는 독립 정답이 아니다.
- 조직 서비스는 로컬 파일 저장소이며 인증·network·동시 writer를 다루지 않는다.
