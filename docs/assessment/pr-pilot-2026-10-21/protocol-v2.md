# 실제 PR 파일럿 — 규칙 수정 (v2)

작성: 2026-10-21 · [protocol.md](protocol.md)를 고치지 않고 이 문서로 바꾼 점만 적는다. PR 표본 추출 전에 커밋한다.
v1 커밋 이후 확인한 것: 세 저장소를 복제하고 기본 브랜치의 최근 커밋 제목 몇 줄(PR 제목 형식 확인용)을 보았다.
PR의 변경 내용·병합 결과는 보지 않았다.

## 바뀐 점과 이유

| # | v1 | v2 | 이유 |
|---|---|---|---|
| 1 | 저장소 3곳 중 `Netflix/dispatch` | `Netflix/dispatch` 제외, `BerriAI/litellm` 추가 | dispatch의 마지막 커밋이 2025-09-02라 2026-01-01 이후 PR이 0개(`git clone --shallow-since=2026-01-01`이 빈 결과로 실패). v1 규칙상 15개 미만이면 기간을 앞당기되 2026-01-01을 넘길 수 없으므로 표본이 성립하지 않음 |
| 2 | 대체 저장소 규칙 없음 | 두 번째 후보 목록을 같은 방법(env 예시 파일 raw 존재)으로 확인해 목록 순서상 처음 통과한 곳 | 아래 참조 |
| 3 | GitHub API로 PR 목록·작성자·변경 파일 수집 | 공개 저장소의 익명 git 복제만 사용 | 이 세션에서 API는 연결된 저장소에만 열려 있고, 타 저장소에 쓰기 가능한 자격증명을 붙이는 것은 목적에 비해 과함 |
| 4 | "기본 브랜치로 병합된 PR" | 대상 브랜치의 first-parent 커밋 중 제목이 `(#번호)`로 끝나거나 `Merge pull request #번호`인 것을 PR로 본다 | git만으로 PR을 식별하기 위함. 직접 푸시 커밋은 PR이 아니므로 제외 |
| 5 | 봇: `user.type != Bot` | 작성자 이름 또는 이메일에 `[bot]`, `dependabot`, `renovate`, `github-actions`, `pre-commit-ci`가 있으면 봇 | API 없이 판별 |
| 6 | open-webui는 기본 브랜치 | 대상 브랜치 `dev` | `main`에는 `dev` 병합 PR(`Merge pull request #… from open-webui/dev`)만 들어오고, 기여자 PR은 `dev`에 병합됨(확인: `dev`의 first-parent에 `(#번호)` 제목 커밋이 있음). `main`의 병합 PR은 수백 개 변경이 묶여 포함 조건(30개 파일)을 넘김 |
| 7 | 문서·테스트 판별 불명확 | 문서: `docs/` 아래 또는 `.md`·`.rst`·`.mdx`. 테스트: `tests/`·`test/`·`__tests__/` 아래 또는 `test_*.py`·`*_test.py`·`*.test.*`·`*.spec.*` | 포함 조건("문서·테스트가 아닌 파일이 1개 이상")을 기계적으로 적용 |
| 8 | 변경 파일 비교 기준 불명확 | `git diff <PR 커밋>^1 <PR 커밋>`(첫 부모 대비). 스쿼시 병합은 한 커밋, merge 커밋은 첫 부모 대비 | 병합 방식이 달라도 PR이 가져온 전체 변화를 본다 |

## 대체 후보 확인(2번)

두 번째 후보 목록(작성 순서): BerriAI/litellm, Significant-Gravitas/AutoGPT, langgenius/dify, browser-use/browser-use,
letta-ai/letta, unclecode/crawl4ai, All-Hands-AI/OpenHands, chroma-core/chroma, mlflow/mlflow, fastapi-users/fastapi-users.
환경 변수 예시 파일이 있는 곳: litellm(`.env.example`, `docker/.env.example`), AutoGPT(`autogpt_platform/backend/.env.default`),
dify(`docker/.env.example`, `api/.env.example`), browser-use(`.env.example`), crawl4ai(`.env.example`), OpenHands(`.env.sample`).
목록 순서상 처음 통과한 `BerriAI/litellm`(Python API 프록시 서버, 기본 브랜치 `main`, 병합 PR 제목이 `(#번호)` 형식)을 쓴다.
이 선택에도 v1과 같은 한계가 있다(작성자 지식 기반 목록).

## 최종 대상

| 저장소 | 대상 브랜치 | 환경 변수 예시 |
|---|---|---|
| open-webui/open-webui | `dev` | `.env.example` |
| langflow-ai/langflow | `main` | `.env.example` |
| BerriAI/litellm | `main` | `.env.example` |

기간·표본 크기(저장소당 10개)·추출 해시 규칙·정답 기준·지표는 v1과 같다.
