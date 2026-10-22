# Python 설정·API 문서 누락 검사

`focused-python`은 새 환경 변수 키와 API 경로 변경을 지정한 문서의 내용과 대조하는 선택형 정책이다.
기존 정책과 기본 프리셋은 그대로 유지된다. LLM 없이 검사하며 대상 프로젝트의 코드를 실행하지 않는다.

## 연결할 범위

| 코드 | 문서 | 확인하는 내용 |
|---|---|---|
| `src/config/**`의 지원되는 정적 Python 환경 변수 접근 | `.env.example` | 새 키 이름의 존재 |
| `src/api/**`의 지원되는 정적 FastAPI 등록 | `docs/openapi.json` | 추가 경로의 존재, 제거 경로의 부재 |

이 경로들은 시작 예시다. 정책을 생성한 뒤 실제 프로젝트의 코드·문서 위치로 바꾼다.
API 문서와 선택한 모듈의 소유 범위가 맞는지 확인해야 한다. 다른 모듈·서비스도 같은 경로를 사용하면
선택한 변경 파일만으로 서비스 전체 경로 제거를 확정할 수 없다. 그런 프로젝트의 전체 소유 범위 검증은 이 프리셋이 제공하지 않는다.

## 시작

저장소 루트에서 다음을 실행한다. 이미 설치된 실행 환경을 사용한다.

```sh
python -m drift_gate init --preset focused-python --policy .drift-gate.focused.yml
python -m drift_gate check --policy .drift-gate.focused.yml --base HEAD --json --out-json focused-result.json
```

새 코드 파일은 Git index에 추가해야 변경 수집에 들어간다. 추가하지 않은 파일은 판정에서 빠지며, Markdown 보고서 상단의 "Untracked files not evaluated" 목록과 JSON의 `execution.untracked_skipped`, `--json` 실행 시 stderr 경고로 알려 준다.
이미 커밋한 기능 브랜치 변경을 보려면 실제 기준 브랜치를 사용한다.

```sh
python -m drift_gate check --policy .drift-gate.focused.yml --base main --comparison-mode merge-base --json
```

기존 정책으로 같은 검사를 내용 모드로 전환할 때는 결과 차이를 검토한다. 이 프리셋은 명시적인 `env-keys`와 `api-routes`,
typed trigger를 사용하며 기존 `auto`·동반 변경 정책의 의미를 바꾸지 않는다.

## 결과 읽기

| `rule_decisions[].decision` | 뜻 | 이 프리셋의 조치 |
|---|---|---|
| `satisfied` | 적용되는 내용 의무를 충족 | 다른 미해결 항목이 없으면 `allow` |
| `violated` | 확인한 새 키·경로가 누락되거나 제거 경로가 남음 | `block` |
| `undetermined` | 변경·문서 내용을 확정할 수 없음 | 확인한 위반이 없으면 `review` |
| `not-applicable` | 선택 범위에서 해당 변경 의무가 없음을 판정 | 그 규칙의 검사 의무 없음 |

결과는 `result`(기존 gate), `enforcement.action`(allow/review/block), 의무별 판정·검증 수준을 함께 제공한다.
이 프리셋의 미검증 처리는 `warn`이므로 `review`도 CLI 종료 코드 0일 수 있다. **종료 코드 0만으로 내용 검증 완료나 자동 병합을 승인하지 않는다.**
자동화에서는 `enforcement.action`과 미해결 항목을 읽고 팀의 승인 절차를 적용한다.
입력 오류·예산 초과는 정상 gate 대신 종료 코드 2의 오류로 남는다.

누락 근거에는 필요한 키 이름, 추가 경로, 문서에 남은 제거 경로가 표시된다.
문서 내용이 이미 맞다면 그 파일을 형식적으로 수정하지 않아도 충족한다.
여러 문서 후보의 조각을 합쳐 한 완전한 문서처럼 취급하지 않는다.

## 보장하는 범위

- 환경 변수: `python-env-literals@1`의 정적 `os.getenv`, `os.environ` 접근과 지원되는 직접 별칭.
  동적 키, 재바인딩, 지원하지 않는 접근은 보류한다. 키 값·배포 성공·보안 적합성은 검사하지 않는다.
- 경로: `python-fastapi-routes@1`의 정적 등록·같은 모듈의 지원되는 router 구성.
  동적 등록·파일 간 불완전한 구성은 보류한다. 요청·응답 스키마 호환성과 실제 HTTP 서버 동작은 별도 검사다.
- 문서: 이 프리셋은 OpenAPI JSON을 선택한다. JSON/YAML 경로 내용 검사는 기존 문서 분석 범위 안에서 가능하지만,
  `$ref` 경로·잘못된 문서 등 해석하지 못한 입력을 빈 문서로 바꾸지 않는다.
- 범위: 선택한 모듈의 관찰 결과다. 서비스 전체의 의존성 닫힘이나 변경 없음 인증으로 확대하지 않는다.

## 제품 경로로 재현

```sh
python scripts/check_focused.py --out /tmp/driftgate-focused-flow.json
```

11개 통제 사례가 실제 임시 Git 저장소에서 원본 commit·정책 pin을 고정해 CLI 검사를 실행한다.
키·경로 누락, 올바른 반영, 이미 문서화된 내용, 동적 입력, 잘못된 문서, 새 키 없음,
확인한 위반과 보류의 공존을 확인하고 모든 결과의 증거 묶음을 재실행한다.
임시 저장소·묶음은 정리되고 JSON에 관찰·기대·입력 digest·receipt digest와 일치 여부가 남는다.
동일 사례의 증거 파일을 직접 보관하려면 제품의 `check --evidence-store <경로>`를 사용한다.

이 사례는 개발자가 작성한 통제 시험이다. 독립 PR 정확도나 사용자 시간 절감 수치로 해석하지 않는다.
[개선 계획](architecture/drift-gate-focused-logic-plan-2026-10-13.md)과
[holdout 절차](ops/holdout-evaluation.md)는 외부 파일럿의 기준을 설명한다.
