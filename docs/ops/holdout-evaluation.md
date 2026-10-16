# holdout 평가 절차 (W10)

이 문서는 `drift-gate holdout` 명령으로 엔진을 개발에 쓰지 않은 사례에서 평가하는 순서와
GPT 같은 언어 모델을 사람 검토자 대신 쓸 때의 기록 방법을 정한다.

## 무엇을 재는가

| 지표 | 정의 | 분모 |
|------|------|------|
| `confirmed_violation_precision` | 엔진이 violated로 낸 의무 중 label도 violated인 비율 | 해당 출처가 판정 가능한 label을 준 의무 중 엔진 violated 수 |
| `confirmed_violation_recall` | label이 violated인 의무 중 엔진도 violated인 비율 | label violated 수 |
| `verified_coverage` | label된 의무 중 엔진이 verified로 결정한 비율 | label된 의무 수 |
| `false_verified` | verified 확정 결정이 판정 가능한 label과 불일치한 비율 | 판정 가능한 label이 있는 verified 확정 결정 수 |
| `appropriate_unsupported_hold` | 지원 범위 밖 사례에서 엔진이 undetermined로 멈춘 비율 | label된 의무 중 expected support=unsupported 수 |
| `known_violation_retained` | 기대값에 known_violation으로 표시한 위반을 계속 잡는 비율 | known_violation이면서 label도 violated인 의무 수 |
| `false_block` | label이 pass/warn인 PR을 엔진이 fail로 막은 비율 | label pass/warn PR 수 |
| `missed_block` | label이 fail인 PR을 엔진이 막지 않은 비율 | label fail PR 수 |

모든 지표는 label 출처(human·llm-proxy)별로 따로 계산한다. 비율마다 Wilson 95% 구간을 함께 낸다.
undetermined, skipped, error는 분모에서 빼지 않는다.
`frozen_expectation_agreement`는 동결한 기대값과 엔진의 일치이며 검토 label 지표와 별개다.

현재 출력은 `holdout-metrics-v2`다. 확정 결정은 satisfied·violated·not-applicable이며,
판정 가능한 label도 이 세 값이다. 이 두 값이 다르면 verified 확정 오판으로 집계한다.
`undecidable` label은 맞음/틀림에 넣지 않고 `verified_without_decidable_label`과
전체 `decision_label_matrix`에 남긴다. label이 없는 단위는 `units_unlabelled`,
그중 verified 확정 출력은 `verified_without_label`로 표시한다. PR도 전체 수와 미라벨 사례를 기록한다.
규칙 지표의 `engine_outcomes_total`은 label 유무와 관계없이 모든 단위의 출력을 센다.
중복 단위·같은 출처의 중복 label은 거부하므로 마지막 행이 앞의 판단을 덮어쓰지 않는다.

평가 단위는 기대값 목록이 아니라 **정책의 모든 규칙**으로 생성한다(`unit_basis: all-policy-rules-v1`).
기대값이 없는 규칙도 실행 결과·검토 packet에 포함하고 기대·지원 분류는 null로 남긴다.
`frozen_expectation_agreement`의 분모는 기대값이 선언된 단위뿐이고 빠진 수는
`units_without_frozen_expectation`에 표시한다. 따라서 기대값 누락을 정답이나 성공으로 취급하지 않는다.
이전 결과 파일은 다시 쓰지 않으며, unit_basis가 없는 과거 결과는 `legacy-expectation-selected-rules`로 표시한다.
v1·v2의 지표를 같은 정의로 직접 비교하지 않는다.

Wilson 구간은 비율별 계산 참고값이다. 같은 PR의 규칙들이 독립 표본이라는 뜻은 아니므로,
실제 성능 평가에는 PR·저장소별 분포와 원시 분모를 함께 보고한다.

## 사례 준비

`holdout split`의 입력은 `{"cases": [...]}`이다. 사례 하나는 다음 필드를 가진다.

- `case_id`, `repository`, `source_family`: family는 같은 출처(같은 저장소·같은 작성자 묶음)를 묶는 이름이다.
  분할은 family 단위이며 한 저장소가 두 split에 동시에 들어가면 거부된다.
- `policy`: `.drift-gate.yml`과 같은 구조의 JSON 객체.
- `changed_files`: `path`, `status`, `patch`, `before_source`, `after_source` 등 `ChangedFile` 필드. 알 수 없는 필드는 split·freeze에서 거부된다.
- `expected`: `gate`(pass/warn/fail)와 규칙별 `rules.<rule_id>` = `{decision, support, known_violation?}`.
  decision은 satisfied·violated·undetermined·not-applicable·waived·error·skipped, support는 supported/unsupported다.
  rules는 정책 규칙의 일부만 선언할 수 있지만, 정책에 없는 ID는 거부한다. 생략한 규칙도 평가·검토 대상에서 빠지지 않는다.
- 선택: `drift_ignores`, `evaluated_on`(ISO 날짜, 없으면 2026-01-01).

저장소의 고정 합성 사례(`adapters/eval`)와 개발 중 본 사례는 holdout이 아니다. 그런 출처는
`--regression-families`로 지정해 holdout에서 제외한다. 이 저장소에는 holdout 후보 사례 파일이 들어 있지 않으며,
다른 저장소의 실제 PR에서 직접 수집해야 한다.

## 명령 순서

모든 출력은 한 번만 쓰이고 같은 경로에 다시 쓰면 오류다. 각 단계가 출력하는 SHA-256을 다음 단계에 넘긴다.
run·packet·adjudicate·score는 pin 인자가 없으면 실행하지 않는다.
각 산출물은 원본 산출물의 digest를 기록한다(packet → frozen, labels → packet·frozen). `score`는 labels가 results와
같은 frozen 입력·protocol에서 나왔는지 확인하고, 다른 frozen 입력을 검토한 labels는 항목 ID가 같아도 거부한다.
`run`은 제품 검사와 같은 inspection 경로로 실행하므로 Express 등 제품의 전처리가 평가에도 적용된다.

```bash
drift-gate holdout split --input candidates.json --seed <공개한 seed> --holdout-fraction 0.3 \
  --regression-families fixture-eval --out holdout.json --out-development development.json
drift-gate holdout freeze --input holdout.json --out frozen.json            # frozen_sha256 기록
drift-gate holdout packet --frozen frozen.json --frozen-sha256 <frozen_sha256> --out packet.json
# 검토(아래) → reviews-a.jsonl, reviews-b.jsonl
drift-gate holdout run --frozen frozen.json --frozen-sha256 <frozen_sha256> --out results.json
drift-gate holdout adjudicate --packet packet.json --packet-sha256 <packet_sha256> \
  --reviews reviews-a.jsonl reviews-b.jsonl [--resolutions resolutions.jsonl] --out labels.json   # labels_sha256 기록
drift-gate holdout score --results results.json --results-sha256 <results_sha256> \
  --labels labels.json --labels-sha256 <labels_sha256> --out metrics.json
```

`freeze` 뒤에는 사례·기대값을 고치지 않는다. 고쳐야 하면 새 protocol 이름과 새 파일로 처음부터 다시 만들고
이전 결과를 지우지 않는다. 검토는 `run` 결과를 보기 전에 끝내는 것이 원칙이다.

## GPT를 검토자로 쓰는 방법

packet의 `instructions`와 `items`를 그대로 모델에 준다. packet에는 규칙과 변경 파일만 있고 엔진 출력과
동결 기대값은 없다. 모델에 Drift Gate 결과, `frozen.json`, `results.json`을 보여 주지 않는다.

1. 서로 독립된 검토 두 개를 만든다. 대화 기록을 공유하지 않는 새 세션 두 개를 쓰고, 가능하면 다른 모델이나
   다른 버전을 쓴다. `reviewer_id`를 `gpt-a`, `gpt-b`처럼 구분하고 실제 모델 이름·버전·날짜를 별도 메모에 남긴다.
2. 각 항목의 응답을 한 줄 JSON으로 받는다.
   `{"item_id": "...", "reviewer_id": "gpt-a", "reviewer_kind": "llm-proxy", "label": "...", "rationale": "..."}`
   `reviewer_kind`는 반드시 `llm-proxy`다. 모델 출력에 `human`을 쓰면 지표가 사람 검토로 잘못 집계된다.
3. label은 항목의 `allowed_labels` 안에서만 고른다. rule 항목은 satisfied·violated·not-applicable·undecidable,
   pr-action 항목은 pass·warn·fail이다. 밖의 값은 `adjudicate`가 거부한다.
4. 두 검토가 다른 항목은 `unresolved`로 남는다. 사람이 판단해 `resolutions.jsonl`에
   `{"item_id": "...", "source": "llm-proxy", "label": "..."}`로 기록하거나 미해결로 둔다. resolution의 label도
   `allowed_labels` 안이어야 하며, 같은 출처의 표가 있는 항목에만 적용된다. 미해결 수는 지표에 표시된다.
5. `adjudicate` 출력의 `agreement.llm-proxy.cohen_kappa`로 두 검토의 일치도를 확인한다. 낮으면 label 자체가
   불안정하다는 뜻이며 지표를 결론으로 쓰지 않는다.

## 해석의 한계

- 도구는 `reviewer_kind`를 확인할 수 없다. 선언을 그대로 기록하고 출처별로 지표를 분리할 뿐이다.
- `human` label이 없으면 결과에 `no human labels: llm-proxy metrics are review material, not blind ground truth`가 기록된다.
  llm-proxy 지표는 독립 사람 검토를 대신하는 근거가 아니다. 모델은 같은 입력에 같은 방향으로 틀릴 수 있고,
  두 모델 세션의 일치가 정답을 뜻하지 않는다.
- 사례 수가 작으면 Wilson 구간이 넓다. 구간을 함께 보고하고 점추정만 인용하지 않는다.
- 여기서 얻은 수치는 수집한 사례 분포에 대한 것이며 다른 저장소·언어·프레임워크로 일반화되지 않는다.
