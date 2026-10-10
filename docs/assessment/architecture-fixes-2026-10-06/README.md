# 리뷰 반례 수정 후 검증

2026-10-06 macOS 로컬 소스 검증. 수정 전 기준 `729a3cde70c3457b633798bb50273d815d4d2c12`, `ver2` 작업 트리.
[수정 보고서](../../review/architecture-fixes-2026-10-06.md). 원래 반례와 관찰 결과는 [이전 폴더](../architecture-review-2026-10-06/README.md)에 그대로 보존했다.

## 회귀 검사

저장소 루트에서 개발·desktop·zstandard 의존성이 설치된 Python을 사용한다.

```sh
python -m pytest drift_gate/tests -q
ruff check drift_gate/ --select E9,F
```

UI는 `desktop-ui`에서 실행한다.

```sh
npm test
npm run build
```

- `python-tests.log`: 800 passed, skip 없음.
- `react-tests.log`: 117 passed.
- `ui-build.log`: TypeScript + Vite 성공. 큰 chunk와 의존성의 주석 경고가 남는다.
- `ruff.log`: E9,F 통과.
- Git 실제 경로와 오류: `test_git_collection.py`.
- 백업 identity·크기·복구: `test_progress_drafts.py`.
- 실제 Qt terminal 응답 및 저장 interleaving: `test_desktop_web.py`.
- 늦게 끝난 검사와 이력 순서: `test_progress_history.py`.
- UI 추가·복구·정리: `ProjectProgress.test.tsx`.
- 파생 결과 수락과 공통 전송 자료: `progressContracts.test.ts`. Python과 TS는 `tests/contracts/progress.json`을 함께 읽는다.

## 소스 앱의 실제 화면 흐름

```sh
python docs/assessment/architecture-fixes-2026-10-06/native_harness.py
```

빌드한 React를 소스 Qt 창과 실제 QWebChannel에 연결한다. 임시 Git 저장소·격리된 설정·합성 초안·테스트용 파일 선택 응답을 사용한다. live LLM·실제 사용자 프로젝트·배포 설치 파일을 사용하지 않는다.

`native/result.json`의 8개 checks를 모두 확인한다. 파일 선택 취소, 다른 프로젝트 거부, import 후 확정 기준 유지, 별도 복구 사본, 1.5 줄 번호 복구, 명시적 저장, 원본 백업 보존과 선택 사본 삭제, 저장 후 초안 부활 방지를 검증한다. `native/*.png`는 실제 소스 창의 캡처다.

샌드박스 안에서는 macOS GUI 서비스 연결이 차단돼 처음 두 실행이 exit 134로 끝났다. GUI 접근을 허용한 실행에서 검사가 통과했다. 이 환경 오류를 제품 테스트 실패나 성공에 포함하지 않는다. Windows·Linux·설치본 오프라인·원격 CI는 이번에 다시 검증하지 않았다.
