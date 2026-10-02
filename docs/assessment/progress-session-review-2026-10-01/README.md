# 편집 세션 후속 검증 입력과 원본

기준 `244bf3274c8ec0bb462ae6ff6255a427ab32b6cf`, 2026-10-01 macOS.

- `SessionRegression.test.tsx.txt`: 변경 전 소스의 `desktop-ui/src/`에 복사해 사용한 입력. 수정본 App.test.tsx 끝의 동일 세션 입력에서 페이지 이동과 이전 저장 응답 두 검사를 선택했다. 변경 전 2개 실패, 변경 후 2개 통과. 새 종료 검사 하나는 비교에서 제외했다.
- `regression-before.log`, `regression-after.log`: 동일 입력의 전후 결과.
- `python-all.log`, `ui-final-contract.log`: 전체 검사 결과. 전체 테스트 수는 정확도 지표가 아니다.
- `results.json`: 환경, 번들 크기, 결과 수치와 응답 입력 해시.
- `native-smoke.py`: 현재 UI 빌드에서 실행하는 독립 합성 저장소 검사. 실제 사용자 설정을 사용하지 않고 임시 경로에 상태·캡처를 저장한다. 저장 성공은 동적으로 다음 버전을 확인한다.
- `native-result.json`, `native-final5.log`: 실제 Qt 편집/종료/저장/diff 확인 결과.
- `qt-events.json`: 위 흐름의 실제 Python/Qt 응답. 임시 절대 경로만 `/fixture`로 치환했다. React의 eventSchema.test.ts가 이 입력 전체를 읽어 계약을 검증한다.

```bash
cd desktop-ui
npm test
npm run build
cd ..
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu python docs/assessment/progress-session-review-2026-10-01/native-smoke.py
```

실행 환경에 PySide6와 프로젝트 의존성이 필요하다. offscreen 검사는 Qt 연결과 렌더링 검사이며 Windows/macOS 사용자의 실기기 사용성 평가를 대체하지 않는다. 문제 발견 후 만든 통제 입력이고 새 엔진 정확도 평가가 아니다.
