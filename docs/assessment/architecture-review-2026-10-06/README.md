# 2026-10-06 아키텍처 리뷰 재현 자료

소스 `729a3cde70c3457b633798bb50273d815d4d2c12`, macOS 로컬 환경.
운영 코드를 수정하지 않고 임시 저장소·Qt worker·jsdom으로 반례를 확인했다.

이 폴더의 관찰용 assert는 **현재 결함이 존재함을 확인**한다. 개선된 코드에서 실패할 수 있으며 제품 회귀 테스트로 그대로 복사하면 안 된다. 수정할 때 원하는 동작을 단언하는 테스트로 전환한다. 실제 사용자 데이터·live LLM·원격 저장소를 사용하지 않는다.

## Python

프로젝트를 설치한 Python 환경에서 저장소 루트 기준:

```sh
python docs/assessment/architecture-review-2026-10-06/reproduce.py
python docs/assessment/architecture-review-2026-10-06/bridge_audit.py
```

두 번째 스크립트에는 PySide6가 필요하다. Qt worker를 실제로 실행하지만 앱 창을 열지 않는다. malformed 입력의 예상 밖 예외가 stderr에 출력되는 것이 이번 관찰이다. 임시 프로젝트용 QSettings 항목은 종료 시 삭제한다. 서로 다른 저장의 순서는 inspect 함수 직전에 다른 save를 삽입해 고정했다. 자연 발생 동시성 빈도를 측정한 것이 아니다.

- `results.json`: Git 한글 경로 false pass, 없는 ref의 exit 0과 유효 ref의 exit 1 통제, 121개 저장·보관·export 거부, clone 백업 거부, malformed tests, 2MB 비대칭, wire 검증 차이.
- `bridge-results.json`: worker 완료 후 응답 0개, save v1/report v2/history v2.
- `bridge-stderr.log`: malformed 테스트 결과의 실제 TypeError 경로.

## React

`desktop-ui` 의존성을 설치한 뒤 저장소 루트에서 다음 파일을 임시로 복사한다. 기존 파일이 있으면 덮어쓰지 않는다.

```sh
cp -n docs/assessment/architecture-review-2026-10-06/ui-audit.tsx.fixture desktop-ui/src/features/project-progress/architectureAudit.test.tsx
cd desktop-ui
npx vitest run src/features/project-progress/architectureAudit.test.tsx
```

검사 후 방금 복사한 임시 `architectureAudit.test.tsx`만 제거한다. 이번 실행에서도 제거했으며 운영 테스트 수 111개에는 이 관찰용 3개를 더하지 않았다. fixture import는 복사 후 위치를 기준으로 작성돼 있다.

- 실제 React 화면: 120개 → 직접 추가 → 121개 저장 payload, export 탈출 버튼 부재.
- decoder: edit_base.repository 누락은 recovery=null.
- reducer: 기준 v1에서 v2 report는 거부하지만 v2 history는 수락.

## 기존 검사 재실행

- `python-tests.log`: Python 774 passed, 16.74초, skip 없음.
- `react-tests.log`: React 111 passed.
- `ui-audit.log`: 관찰용 React 3 passed. 결함 해소가 아닌 결함 존재 확인.
- TypeScript `tsc --noEmit`: exit 0.
- Ruff `E9,F`: 통과.

시간은 이 로컬 실행의 테스트 시간이며 제품 응답 시간·플랫폼 성능 비교가 아니다. native UI·설치본·원격 CI는 이번에 다시 실행하지 않았다. 보고된 예전 CI 수치를 현재 로컬 검증에 섞지 않는다.
