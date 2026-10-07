# S1-e: 증명 projection과 외부 진입점 통합

## 결과와 적용 범위

검증된 계약 증명의 공통 projection을 운영 코드에 추가하고 CLI, local/PR MCP,
Desktop 서비스, GitHub Action, JSON·Markdown·HTML 출력에 연결했다.
명시적으로 켜는 shadow 진단이며 기존 정책 판정과 schema 3의 의미는 유지한다.
기본값은 false다. 새 출력 변환은 pass/warn/fail을 계산하지 않는다.

작업 기준은 `ver2`의 HEAD `d262ec2faff3b98c917e3e99f7b6260cf0514ff3`에 누적된 미커밋
작업 트리다. 이번에도 커밋·푸시는 하지 않았다. 이전 기록과 고정 입력을 보존하고
이번 실행을 [별도 폴더](../assessment/projection-implementation-2026-10-07/)에 기록했다.

## 변경한 구조

`core/compat/legacy_result.py`가 두 역할을 맡는다. 기존 `EvaluationResult`의 필드는
이전 값으로 내보내고, 요청된 경우에만 `contract_diagnostics`를 덧붙인다. 별도의
`project_contract_proof`는 `ContractProof.validate()`를 통과한 진리값과 coverage를
decision/verification으로 변환한다. reporter가 명제를 만들거나 범위를 닫지 않는다.

| 입력 | 공통 projection |
| --- | --- |
| 적용 조건 A=F인 의무 | not-applicable / not-applicable |
| 알려진 T/F, 범위 닫힘 | satisfied 또는 violated / verified |
| 알려진 T/F, 범위 열림 | satisfied 또는 violated / partial |
| U | undetermined / unverified |

알려진 F는 미확인 형제 때문에 사라지지 않는다. OR의 T 근거가 있더라도 다른 대안의
범위가 열려 있으면 새 projection은 partial이다. 이는 이전 verification 의미를 바꾸는
작업이 아니다. 기존 정책 verification과 shadow의 projection을 각각 보존한다.

`AnalysisSession`은 유효한 기록 수와 최근 보관 증명을 유지한다. 엔진은 요청된 경우
이를 불변 `ContractDiagnostics`에 담는다. 중복 요청의 이전 기록이 대체되거나 보관
한도를 넘으면 `records_seen`, `retained_count`, `omitted_record_count`, `trace_truncated`로
알린다. `complete_policy_coverage=false`, `gate_action_applied=false`는 항상 유지한다.
empty·no-policy·docs-only 입력에서 기록이 없다고 proof 완료로 표시하지 않는다.

## 사용하는 방법

| 진입점 | 명시 요청 |
| --- | --- |
| CLI check/report | `--contract-proofs` |
| local/PR MCP | JSON boolean `contract_proofs: true` |
| Desktop 서비스 | `scan_repository(path, contract_proofs=True)` |
| 공개 Action | `contract_proofs: 'true'` |
| 순수 projection API | `project_contract_proof(validated_contract_proof)` |

CLI 예시는 다음과 같다. 비교 기준은 검사하려는 변경 범위에 맞게 지정한다.

```sh
python -m drift_gate check --base HEAD --contract-proofs --json
```

full에는 projection과 전체 proof 결과를 포함한다. compact는 같은 projection만 남기며
`full_proofs_omitted=true`를 표시한다. 토큰 예산 때문에 entries까지 생략하면
`display_truncated=true`, `omitted_entry_count`를 표시하고 보관 개수와 범위 제한은 유지한다.
기존 compact 예산은 대략적 축소 기준이며 엄격한 전체 응답 크기 보장은 아니다.

MCP 서버는 옵션을 boolean으로 광고하고 문자열 `'true'`를 거부한다. Action은 true/false
외 값을 거부한다. CLI에서 IR 검증 실패는 종료 코드 2와 `result_validation_error`로
끝나며 정상 result 필드를 내보내지 않는다. 다른 진입점도 invalid proof를 성공 결과로
변환하지 않는다. HTML·Markdown의 사용자 지정 이름은 표시 형식에 맞춰 escape한다.

## 의도한 호환 경계

기존 YAML은 새 모델의 명시적 profile/document binding을 선언하지 않는다. 따라서
shadow는 기존 그룹 선택 패턴만으로 문서 연결을 추측하지 않고 unmapped로 남긴다.
이 경계 때문에 현재 문서가 맞아 legacy가 verified여도 shadow는 U일 수 있다.
이를 새로운 검증 성공으로 꾸미거나 기존 게이트를 바꾸지 않는다.

실제 Git 프로브에서 확인한 결과는 다음과 같다. 기본 모드와 옵션을 켠 모드의 정책
결과는 같았고, 모든 진입점의 추가 진단도 같았다.

| 사례 | 기존 gate / verification | 옵션을 켠 shadow truth |
| --- | --- | --- |
| 옛 API 문서 | fail / verified | U — binding 없음 |
| 갱신된 API 문서 | pass / verified | U — binding 없음 |
| 동적 route | fail / unverified | U |
| 계약 변화 없음 | pass / not-applicable | T / N/A |

직접 명시 binding을 받은 proof의 T·F·U·partial·N/A 변환은 별도 회귀 테스트로 확인했다.
새 기본 profile 전환, 모든 정책 의무의 proof ledger, waiver·threshold·ignore의 새 IR
전환은 이번 단계에 추가하지 않았다. 최근 128개 기록은 전체 정책 처리 완료 인증이 아니다.

Desktop은 서비스 API와 scanned 이벤트의 확장 필드 보존을 검증했다. 현재 Qt 화면에
새 설정 스위치를 추가하지 않았으며 실제 화면 조작으로 옵션을 켠 결과를 확인한 것은 아니다.

## 실행한 검증

| 검사 | 결과 |
| --- | --- |
| Python 전체 | 1,660 통과, skip 0 |
| 신규 projection 회귀 | 38개, 전체 검사에 포함 |
| proof·projection·진입점 관련 검사 | 171 통과 |
| React | 126 통과, 11개 파일 |
| TypeScript·UI 빌드·Ruff E9,F | 통과 |
| 실제 Git + 진입점 비교 | 4종 × 옵션 2모드 = 8/8 |
| Python/Git 고정 평가 | 14/14, 네 평가 축 일치 |
| Express/Git 고정 평가 | 8/8, 네 평가 축 일치 |
| 고정 평가 | 21/21 |
| 자체 정책 | pass / unverified |

GitHub Action과 PR MCP의 transport는 프로브에서 로컬 입력으로 대체했다. 이것은
실제 원격 CI 결과가 아니다. CLI·local MCP·Desktop 서비스는 임시 저장소의 실제 Git과
현재 문서 읽기를 사용했다. 동일 사례의 JSON projection 및 HTML·Markdown 표시 값을
비교했고, compact 생략·proof 조작·빈 기록·잘못된 옵션도 검사했다.

이전 S1-d와 고정 Git 22건의 suite·입력 해시, 기대값과 실제값이 같았다. 고정 21건의
판정과 보고서도 실행 식별자·시간 정보를 제외하면 같다. 작성자가 만든 비맹검 통제이며
실사용 PR 정확도나 전면 형식 검증을 뜻하지 않는다.

## 근거와 후속 범위

- [소스·고정 입력·결과 해시와 실행 영수증](../assessment/projection-implementation-2026-10-07/verification.json)
- [이전 결과 비교](../assessment/projection-implementation-2026-10-07/comparison.json)
- [진입점별 실제 출력과 사례](../assessment/projection-implementation-2026-10-07/entrypoints.json)
- [재현 프로그램](../assessment/projection-implementation-2026-10-07/probe_projection.py)
- [Python 전체 로그](../assessment/projection-implementation-2026-10-07/python-full.log)
- [관련 회귀 로그](../assessment/projection-implementation-2026-10-07/targeted-final.log)
- [자체 정책 결과](../assessment/projection-implementation-2026-10-07/self-check.json)

원격 CI·설치본·Windows/Linux·실제 화면·독립 홀드아웃은 이번에 확인하지 않았다.
원본의 진위·manifest·현재 HEAD·서비스 전체 closure는 증명하지 않는다. 기존 auto 경계
1/8을 이번에 재실행하거나 개선했다고 주장하지 않는다. 다음은 S2의 불변 snapshot,
manifest·입력 신뢰·실행 영수증 구조다.
