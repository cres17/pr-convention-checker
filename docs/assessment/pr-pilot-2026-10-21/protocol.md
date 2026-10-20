# 실제 PR 파일럿 — 실행 전 고정 규칙

작성: 2026-10-21 · 이 문서는 PR 목록·내용을 보기 전에 커밋한다. 커밋 시각이 "사전 고정"의 근거다.
이후 규칙을 바꾸면 이 문서를 고치지 않고 `protocol-v2.md`를 새로 만들며, 바꾼 이유와 시점을 적는다.

## 1. 무엇을 측정하나

개발에 쓰지 않은 공개 저장소의 병합된 PR에서 Drift Gate가
"문서·설정 예시를 함께 고쳐야 했는가"를 맞게 판정하는지 처음으로 측정한다.
합성 사례 통과 수치는 이 측정의 근거가 아니며 섞어 보고하지 않는다.

## 2. 저장소 선정

선정 기준(모두 충족):

1. 주 언어가 Python이고 웹 API 서버를 포함한다.
2. 저장소 루트 또는 `docker/`에 환경 변수 예시 파일(`.env.example` 계열)이 있다.
3. 이 저장소의 개발·회귀 사례로 쓴 적이 없다(`docs/`·테스트에 해당 저장소 이름이 없음을 확인).

후보 확인 방법: 아래 14개 후보의 기본 브랜치에서 환경 변수 예시 파일(`.env.example`, `env.example`, `.env.sample`,
`docker/.env.example`)이 raw 파일로 존재하는지 확인했다. 후보는 작성자가 알고 있는 Python API 저장소 목록이며
GitHub 검색 API를 쓸 수 없어 전수 목록이 아니다. 이것이 선정 편향의 한계다.

후보: open-webui/open-webui, langflow-ai/langflow, fastapi/full-stack-fastapi-template, Netflix/dispatch,
danswer-ai/danswer, onyx-dot-app/onyx, zylon-ai/private-gpt, infiniflow/ragflow, Kludex/fastapi-microservices,
mem0ai/mem0, khoj-ai/khoj, getmaxun/maxun, apache/superset, frappe/frappe.

확인 결과(2026-10-21): 예시 파일이 있는 곳은 3곳이다.

| 저장소 | 예시 파일 |
|---|---|
| open-webui/open-webui | `.env.example` |
| langflow-ai/langflow | `.env.example` |
| Netflix/dispatch | `docker/.env.example` |

세 곳을 모두 쓴다. 나머지 11곳은 예시 파일을 찾지 못해 제외했다(다른 이름·위치의 파일은 확인하지 않았다).

## 3. PR 선정

- 기간: 2026-07-01 ~ 2026-10-15(UTC)에 기본 브랜치로 병합된 PR. 한 저장소에서 아래 조건을 만족하는 PR이 15개 미만이면
  기간 시작을 30일씩 앞당기되 2026-01-01을 넘기지 않는다. 앞당긴 사실은 기록한다.
- 포함 조건: 봇이 작성하지 않았고(`user.type != Bot`), revert가 아니며, 변경 파일이 30개 이하·변경 줄 수가 1,500줄 이하이고,
  문서·테스트가 아닌 파일이 1개 이상이다.
- 추출: 조건을 만족하는 PR을 `sha256("pr-pilot-2026-10-21:" + <owner/repo> + ":" + <PR 번호>)` 오름차순으로 정렬해
  저장소마다 앞 10개를 쓴다(30개). 난수 라이브러리나 사람의 선택을 쓰지 않는다.
- PR 본문·제목·병합 결과를 보고 표본을 바꾸지 않는다. 수집 불가(삭제된 브랜치 등)인 PR은 사유를 적고 다음 순번으로 대체한다.

## 4. 정책

- 저장소마다 `.drift-gate.yml`을 기본 브랜치 파일 구조(PR 내용이 아님)만 보고 작성하고 SHA-256을 기록한다.
- 정책 작성에 쓰는 정보: 환경 변수 예시 파일, 설정 코드 위치, 문서·CHANGELOG 위치, API 라우터 위치.
- 정책은 PR 수집 전에 커밋한다. 결과를 본 뒤 정책을 고치면 별도 실험(`policy-v2`)으로 분리하고 이 파일럿의 지표에 섞지 않는다.

## 5. 정답(label)

- 질문: "이 PR이 건드린 변경에 대해, 저장소가 스스로 따르는 관례(예시 파일·문서·CHANGELOG 갱신)상 같은 PR에서 함께 갱신해야 했는가?"
  규칙 단위로 satisfied · violated · not-applicable · undecidable, PR 단위로 pass · warn · fail.
- label은 도구 결과(`results`)를 보기 전에 작성한다. 검토자에게 도구 출력을 주지 않는다.
- 사람 검토자가 한 label만 `human`으로 집계한다. 언어 모델 검토는 `llm-proxy`이며 독립 사람 검토를 대신하지 않는다.
  사람 label이 없으면 결과에 "사람 label 없음"을 명시한다. 이 문서 작성 시점에 사람 검토 여부는 정해지지 않았다.

## 6. 지표와 보고

`docs/ops/holdout-evaluation.md`의 `holdout-metrics-v2` 정의와 절차(`split → freeze → packet → run → adjudicate → score`)를 따른다.
모든 비율에 원시 건수와 Wilson 95% 구간을 함께 낸다. 표본이 30개 PR이므로 구간이 넓다. 점추정만 인용하지 않는다.
결과를 보고 고친 사례는 회귀 테스트로 옮기고 같은 사례로 정확도를 다시 주장하지 않는다.

## 7. 알려진 한계

- 후보 저장소는 작성자 지식에서 고른 목록이다(검색 불가). 통계적 대표 표본이 아니다.
- 저장소 3곳·PR 30개는 Python API 서버 일부의 분포이며 다른 언어·프레임워크로 일반화할 수 없다.
- 정답은 저장소 관례에 대한 판단이며 저장소 관리자의 의도와 다를 수 있다.
