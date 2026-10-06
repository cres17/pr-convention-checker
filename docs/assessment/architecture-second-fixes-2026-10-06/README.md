# 두 번째 리뷰 수정 검증 자료

이 폴더는 수정 전 관찰 기록인 `architecture-second-review-2026-10-06`을 대체하지 않는다. 구현 내용은 [수정 보고서](../../review/architecture-second-fixes-2026-10-06.md)에 있다.

- `python-tests.log`: 전체 Python 833 passed, skip 없음.
- `react-tests.log`: 전체 React 122 passed.
- `ui-build.log`: 타입 검사와 Vite 빌드. 기존 chunk 경고 포함.
- `ruff.log`: E9,F 통과.
- `validation.json`: HEAD, 커밋되지 않은 상태, 검증한 소스 해시와 결과.
- `native_harness.py`, `native/result.json`, `native/finished.png`, `native-run.log`: 실제 macOS 소스 Qt/React/QWebChannel 흐름. 임시 Git 저장소, 격리된 설정, 확인창 긍정 답변 fixture. 설치본 검증이 아니다. 로그의 손상 이력 예외는 의도적으로 만든 입력의 기록 거부이며, 정상 저장과 report/history 경고 전달을 함께 확인한다.

재실행:

```sh
python -m pytest drift_gate/tests/ -q
ruff check drift_gate --select E9,F
(cd desktop-ui && npm test -- --run && npm run build)
python docs/assessment/architecture-second-fixes-2026-10-06/native_harness.py
```

Python desktop/dev 의존성이 필요하다. native harness는 Qt/macOS 화면 접근이 필요한 실행이며 결과 파일을 이 폴더에 쓴다. 초기 harness에서는 JS 객체의 Qt 반환 변환이 불완전해 화면 확인값을 받지 못했다. JSON 문자열로 전달하고 검증하는 방식으로 고쳐 다시 실행했고 최종 결과 10개 모두 true다. 앱의 보존 저장은 첫 실행에서도 성공했다.
