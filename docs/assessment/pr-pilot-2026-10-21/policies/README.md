# 파일럿 정책

[protocol-v2](../protocol-v2.md) 4절에 따라 PR 수집 전에 작성·커밋한 정책이다. 해시는 [policies.sha256](../policies.sha256).

| 저장소 | 규칙 | 선택 근거(기본 브랜치 파일 구조) |
|---|---|---|
| open-webui (dev) | `env-sample-content` | 환경 변수를 `backend/open_webui/env.py`·`config.py`에서 읽음. 예시 파일은 `.env.example`. 저장소 안에 API 문서 파일이 없어 경로 규칙은 두지 않음 |
| langflow (main) | `env-sample-content`, `api-route-content` | 설정은 `services/settings/` 아래(`os.getenv` 직접 접근이 아닌 설정 클래스일 수 있어 엔진이 보류할 가능성이 있음). API 문서는 `docs/openapi/openapi.json` |
| litellm (main) | `env-sample-content` | `litellm/constants.py`와 `litellm/proxy/**`에서 `os.getenv` 사용. API 문서가 저장소 안에 없어 경로 규칙은 두지 않음 |

한계: 정책이 가리키는 경로는 작성자가 구조를 훑어 고른 것이며 저장소 관리자의 문서 소유 범위와 다를 수 있다.
환경 변수 규칙은 `selected-modules` 범위의 관찰이라 선택하지 않은 모듈의 키 추가는 보지 못한다.
