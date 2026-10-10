# 두 번째 리뷰의 관찰 자료

2026-10-06. `ver2` 수정 작업 트리. HEAD `729a3cd`에 아직 커밋하지 않은 운영 변경이 있으므로 `validation.json`의 source fingerprint를 함께 사용한다.

[두 번째 리뷰](../../review/architecture-second-audit-2026-10-06.md)와 [설계 v2](../../architecture/target-architecture-v2-2026-10-06.md).

## 검증 결과

- Python 전체 800 passed, skip 없음: `python-tests.log`.
- React 전체 117 passed: `react-tests.log`.
- TypeScript/Vite 성공: `ui-build.log`. 큰 chunk 경고가 남는다.
- Ruff E9,F 통과: `ruff.log`.
- 운영 코드와 제품 회귀 테스트는 이번 리뷰에서 변경하지 않았다. 직전 validation의 소스 hash와 일치한다.

개발·desktop 의존성을 설치한 Python을 사용해 저장소 루트에서 실행한다.

```sh
python -m pytest drift_gate/tests -q
python docs/assessment/architecture-second-review-2026-10-06/reproduce.py
python docs/assessment/architecture-second-review-2026-10-06/bridge_probe.py
```

`reproduce.py`는 임시 Git 저장소·임시 앱 저장 파일로 반례 6개와 정상 통제 4개를 관찰한다. 저장 파일 재생성은 앱 외부의 삭제/복원 조건을 모사하며 일반 동시 저장과 구분한다. `results.json`은 정상 동작 검증이 아니라 **남은 결함이 존재하는 결과**다. 개선 뒤 이 assert는 실패할 수 있다.

`bridge_probe.py`는 실제 QCoreApplication·DesktopBridge·Qt worker로 손상 이력에 따른 terminal error와 정상 이력의 report/history 전달을 확인한다. GUI 창을 열거나 실제 설치 파일을 실행하지 않는다. `bridge-results.json`과 `bridge-run.log`를 보존한다. 사용자의 설정을 변경하지 않는다.

## TS 관찰

`ui-probe.ts.fixture`를 임시 테스트로 복사한다. 이미 같은 이름의 파일이 있으면 덮어쓰지 않는다.

```sh
cp -n docs/assessment/architecture-second-review-2026-10-06/ui-probe.ts.fixture desktop-ui/src/features/project-progress/secondArchitectureAudit.test.ts
cd desktop-ui
npm test -- --run src/features/project-progress/secondArchitectureAudit.test.ts
```

확인 뒤 새로 만든 임시 파일만 제거한다. 이번에도 제거했다. `ui-probe.log`의 2 passed는 문서 rename 뒤 old binding 유지와 같은 context의 잘못된 history 수락을 관찰한 결과다. React 전체 117개에 합산하지 않는다. 실제 화면 조작·키보드 접근성 시험은 아니다.

과거 재현 자료, 고정 정확도 fixture, 사용자 저장 데이터는 덮어쓰지 않는다. 이번 실행은 원격 CI·Windows/Linux·설치본·실제 PR 정확도·제품 성능 검증을 포함하지 않는다.
