# 과적합 점검과 개선 전후 비교

검증일: 2026-09-22 · 기준 커밋: `bffc6550fd0b7da0509fe9ae8838efcf5fe9bc8c` · 비교 대상: `ver2`의 1차 개선 제품 코드

## 판단

**개선 효과는 재현됐지만, 개발 목표 사례의 8/8을 일반적인 정확도로 해석하면 성능을 과대평가한다.** 새 지원 범위 사례에서는 10/24에서 17/24로 개선됐다. 그러나 문자열·주석 오탐과 일부 계약 변경 미탐이 남았고, Markdown 표·OpenAPI 문서에서는 기존 정상 사례 2개가 새로 차단됐다.

이 프로젝트는 규칙 기반 도구이므로 여기서 과적합은 학습 모델의 과적합이 아니라 **개발에 사용한 예시와 문법에 구현이 치우쳤는지**를 뜻한다. 새 사례에서도 개선된 7건이 있어 기존 예시만 통과하도록 만든 것이라고 단정할 수는 없다. 다만 지원 문법과 검사 단계가 일관되지 않아 일반화가 충분하지 않다는 반례는 확인했다. 실제 PR에 대한 정확도와 효과 크기는 아직 판단할 수 없다.

## 어떻게 비교했나

- 개발 목표 8개와 별도로 사후 반례 32개를 작성하고, 첫 실행 전에 기대 판정과 지원 범위 구분을 고정했다. 고정 절차는 평가 파일의 `protocol`에 기록돼 있으며 외부 사전등록은 아니다.
- 구현을 본 작성자가 설계한 합성 사례다. 독립 평가자나 블라인드 검증으로 표현하지 않는다.
- 지원 범위 24개는 기존 지원 설명을 확인하는 사례다. 확장·형식 경계 8개는 미지원 문법과 문서 형식에 대한 스트레스 검사다. 실패 사례를 결과 확인 후 지원 범위 밖으로 옮기지 않았다.
- 두 제품 버전에 같은 입력·정책·측정 스크립트·Python·주요 의존성을 적용했다. 원본 코드는 기준 커밋에서 추출했다.
- 엔진에 합성 diff와 문서 키 증거를 전달한다. 기존 버전은 새 `content` 설정과 키 증거를 해석하지 않는다. 따라서 새 기능 도입에 따른 판정 차이이며, 실제 GitHub 수집부터 이어지는 통합 평가가 아니다.
- 이번 점검과 재개 후 재검증에서는 제품 코드와 기대 판정을 바꾸지 않았다. 기존 JSON을 보존하고 별도 임시 경로로 재실행하여 모든 사례별 결과·소스 해시·입력 해시의 일치를 확인했다.

환경: Python 3.11.15, macOS 26.6.2 ARM64, PyYAML 6.0.3, tree-sitter 0.26.0, tree-sitter-language-pack 1.20.0. 원본의 파서 실패도 같은 환경에서 나타나는 제품 상태로 비교에 포함했다. 이 결과로 모든 이전 실행 환경의 성능을 추정할 수는 없다.

## 비교표

| 평가 구분 | 개선 전 | ver2 | 해석 |
|---|---:|---:|---|
| 기존 합성 사례 | 22/22 | 22/22 | 기존 기대 판정 유지 |
| 개발 목표 사례 | 4/8 | 8/8 | 구현에 사용한 인수 기준 충족 |
| 개발 중 별도 환경변수 사례 | 5/8 | 8/8 | 독립 검증셋으로 해석하지 않음 |
| **새 반례: 지원 범위** | **10/24 (41.7%)** | **17/24 (70.8%)** | **+7개, +29.2%p** |
| 정상 변경 오차단 — 지원 범위 | 5/12 | 4/12 | 1건 감소 |
| 차단할 누락을 놓침 — 지원 범위 | 9/12 | 3/12 | 6건 감소 |
| **새 반례: 확장·형식 경계** | **2/8** | **0/8** | 정상 문서 형식 2건에서 악화 |
| 정상 변경 오차단 — 경계 | 0/2 | 2/2 | Markdown 표·중첩 OpenAPI YAML |
| 차단할 누락을 놓침 — 경계 | 6/6 | 6/6 | 미지원 문법의 누락 지속 |
| 전체 pytest | 470/471 | 524/524 | 새 테스트 53개 + 기존 실패 1개 해결 |
| 파서 직접 실행 | 0/3 | 3/3 | Python·TypeScript·Go 호출 확인 |

오탐(FP)은 통과해야 할 변경을 차단한 경우, 미탐(FN)은 차단해야 할 변경을 통과시킨 경우다. 지원 범위의 정상/차단 기대 사례는 각각 12개다. 양 버전 모두 사후 평가 실행 오류는 0건이다. 지원 범위에서 개선 7건·악화 0건, 경계에서 개선 0건·악화 2건을 확인했다. 경계의 기존 2/8은 문서 내용을 이해했다는 뜻이 아니라 경로 검사로 정상 수정이 통과했다는 뜻이다.

평가셋은 무작위 실제 PR 표본이 아니며 사례끼리 문법과 원인이 겹친다. 따라서 이 비율을 실제 정확도 추정치로 사용하거나 통계적으로 유의한 개선이라고 주장하지 않는다. 서로 목적이 다른 평가셋을 합쳐 하나의 정확도로 제시하지 않는다. 기존 22개 평가는 규칙 위반까지 비교하지만 사후 32개 평가는 최종 pass/fail 일치만 집계한다.

## 어떤 부분이 개선됐고 무엇이 남았나

| 구분 | 확인한 내용 | 근거 사례 |
|---|---|---|
| 개선 | 무관한 문서, 잘못된 HTTP 메서드, 여러 API 중 일부 누락 차단 | A06, A08, A14 |
| 개선 | 삭제한 API의 문서 누락 차단, 주석 줄만 바뀐 경우 통과 | A15, A12 |
| 개선 | 다른 키·빈 샘플을 정상 설정 예제로 인정하지 않음 | E01, E06 |
| 남은 미탐 | HEAD·OPTIONS가 내용 검사에 도달하기 전 변경 분류에서 빠짐 | A03, A04 |
| 남은 미탐 | 문서에서 이전 경로를 삭제했다 다시 추가해도 삭제로 인정 | A09 |
| 남은 오탐 | 문자열·줄 끝 주석의 코드 예시를 실제 접근으로 인식 | A10, A11, E05 |
| 남은 오탐 | 기존 키 사용 코드를 정리한 변경에도 새 키 검사를 요구 | E04 |
| 악화 | 정상 Markdown 표·중첩 OpenAPI YAML 수정 차단 | B02, B03 |
| 미지원 | 여러 줄 등록, prefix, 동적 키·별칭, 응답 스키마, 연결형 라우터 | B01, B04–B08 |

현재 내용 검사와 변경 강도 분류는 서로 다른 정규식·휴리스틱을 사용한다. 내용 검사에 HEAD·OPTIONS 정규식이 있더라도 앞 단계에서 규칙이 발동하지 않으면 검사하지 않는다. 문서도 현재 파일의 최종 상태가 아니라 diff의 추가·삭제 줄을 비교하므로 A09 같은 순변경 누락이 생긴다. 파서 호출 복구만으로 이런 오류가 해소되지는 않는다.

## 사례별 결과

`pass`는 변경 허용, `fail`은 변경 차단이다. 성공 여부는 기대값과 같은지로 판단한다. 사례의 전체 입력과 선정 이유는 [고정 평가셋](assessment/generalization-audit-v1.json)에 있다.

| 사례 | 범위 | 기대 | 개선 전 | ver2 | 변화 |
|---|---|---|---|---|---|
| A01-get-added | 지원 | fail | fail | fail | 통과 유지 |
| A02-delete-added | 지원 | fail | fail | fail | 통과 유지 |
| A03-head-added | 지원 | fail | pass | pass | 실패 지속 |
| A04-options-added | 지원 | fail | pass | pass | 실패 지속 |
| A05-correct-route-doc | 지원 | pass | pass | pass | 통과 유지 |
| A06-unrelated-route-doc | 지원 | fail | pass | fail | 개선 |
| A07-correct-method-doc | 지원 | pass | pass | pass | 통과 유지 |
| A08-wrong-method-doc | 지원 | fail | pass | fail | 개선 |
| A09-stale-route-retained | 지원 | fail | pass | pass | 실패 지속 |
| A10-route-in-string | 지원 | pass | fail | fail | 실패 지속 |
| A11-route-in-inline-comment | 지원 | pass | fail | fail | 실패 지속 |
| A12-route-in-comment-line | 지원 | pass | fail | pass | 개선 |
| A13-two-routes-documented | 지원 | pass | pass | pass | 통과 유지 |
| A14-one-route-missing | 지원 | fail | pass | fail | 개선 |
| A15-route-file-deleted | 지원 | fail | pass | fail | 개선 |
| A16-local-variable-rename | 지원 | pass | pass | pass | 통과 유지 |
| E01-unrelated-key | 지원 | fail | pass | fail | 개선 |
| E02-bracket-key-present | 지원 | pass | pass | pass | 통과 유지 |
| E03-javascript-key-present | 지원 | pass | pass | pass | 통과 유지 |
| E04-existing-token-key | 지원 | pass | fail | fail | 실패 지속 |
| E05-env-access-in-string | 지원 | pass | fail | fail | 실패 지속 |
| E06-empty-sample | 지원 | fail | pass | fail | 개선 |
| E07-env-comment-only | 지원 | pass | pass | pass | 통과 유지 |
| E08-key-no-sample | 지원 | fail | fail | fail | 통과 유지 |
| B01-multiline-route | 경계 | fail | pass | pass | 실패 지속 |
| B02-markdown-table | 경계 | pass | pass | fail | 악화 |
| B03-openapi-yaml | 경계 | pass | pass | fail | 악화 |
| B04-router-prefix | 경계 | fail | pass | pass | 실패 지속 |
| B05-dynamic-environment-key | 경계 | fail | pass | pass | 실패 지속 |
| B06-aliased-environment-getter | 경계 | fail | pass | pass | 실패 지속 |
| B07-response-schema | 경계 | fail | pass | pass | 실패 지속 |
| B08-chained-router | 경계 | fail | pass | pass | 실패 지속 |

## 원본 자료와 재현

- [원본 결과](assessment/generalization-original.json) / [ver2 결과](assessment/generalization-ver2.json): 전체 보고서, 실행 환경, 제품 파일별 SHA-256
- [고정 입력](assessment/generalization-audit-v1.json) / [측정 스크립트](../scripts/audit_generalization.py)
- [1차 개발 결과](development-results-2026-09-22.md) / [개발 당시 자동 비교표](assessment/after-v1/comparison.md)

두 사후 결과의 `suite_sha256`·`harness_sha256`는 같다. 원본 제품 해시는 기준 커밋과, ver2 제품 해시는 현재 브랜치의 제품 코드와 대조했다. 문서와 CI 설정은 제품 해시 대상이 아니며 후속 정리에 따라 달라질 수 있다. 최초 측정 당시 미커밋 상태를 나타내는 기록은 수정하지 않는다.

저장소 루트에서 Python 3.11 가상환경을 사용한다. 아래는 macOS·Linux 재현 예시다. 이미 가상환경과 같은 버전의 의존성이 준비됐다면 설치 단계는 생략한다.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r docs/assessment/baseline-requirements.txt
```

```bash
AUDIT_DIR=$(mktemp -d)
mkdir "$AUDIT_DIR/original"
git archive bffc6550fd0b7da0509fe9ae8838efcf5fe9bc8c | tar -x -C "$AUDIT_DIR/original"
python scripts/audit_generalization.py --source-root "$AUDIT_DIR/original" --revision bffc6550fd0b7da0509fe9ae8838efcf5fe9bc8c --out "$AUDIT_DIR/original.json"
python scripts/audit_generalization.py --source-root . --revision ver2 --out "$AUDIT_DIR/ver2.json"
```

같은 셸에서 순서대로 실행한다. 결과는 출력에 표시되는 임시 경로에 남는다. 스크립트는 기존 결과 파일 덮어쓰기를 거부하며, 실패 사례도 관측 결과로 저장한다. **종료 코드 0은 모든 사례의 성공을 뜻하지 않는다.** JSON의 `counts`와 `cases[].matched`를 확인해야 한다. 파서 문법의 최초 다운로드에는 네트워크가 필요할 수 있다.

## 다음 개선 순서

아래는 이번 브랜치에서 완료한 기능이 아니라 후속 작업이다. 현재 32개를 수정 목표로 쓰기 시작하면 이후에는 회귀 평가셋이며 독립적인 새 평가가 아니다.

| 순서 | 개선 대상 | 완료 판단 기준 |
|---|---|---|
| 1 | 문자열·주석을 실제 선언과 구분하고 변경 분류·내용 검사 인식 범위 통일 | A03·A04·A10·A11·E04·E05 재현 회귀 검사와 정상 대조 사례 통과 |
| 2 | 코드와 문서의 변경 전후 상태·순변경 비교 | A09 차단, 단순 이동·정렬 변경은 허용 |
| 3 | Markdown 표·OpenAPI 구조 지원과 미지원 상태 명시 | B02·B03 정상 통과, 무관한 문서 변경은 계속 차단 |
| 4 | 원본 PR·SHA를 추적할 수 있는 별도 실제 PR 평가 | 30~50개부터 시작해 정상/누락 기준 사전 정의, 가능하면 별도 평가자 판정, 개발에 쓰지 않은 표본의 오탐·미탐 공개 |
| 5 | 실제 GitHub 권한 환경에서 승인 예외·Action 확인 | 모의 API 검증과 실제 연동 결과를 구분해 기록 |

실제 PR 표본 수 30~50개는 다음 수집 목표이며 정확도를 보장하는 기준이 아니다. 공개한 결과는 로컬 재현 검증까지이며, 리뷰 시간 절감과 조직 운영 효과는 측정하지 않았다.
