# 2026-10-01 데스크톱 릴리스 후보 검증 원본

기준은 `b13d73f`이다. 과거 평가를 덮어쓰지 않고 별도 경로에 보존했다.

| 파일 | 내용 |
|---|---|
| `baseline-audit.json` | 변경 전 고정 32개 반례, 입력·도구·제품 해시 |
| `release-audit.json` | 구조 보완 후 같은 32개 반례. 미커밋 시점의 제품 해시로 소스 식별 |
| `published-source-audit.json` | 패키지 평가 수정까지 포함한 최종 제품 커밋 `6445879`의 32개 반례와 모든 제품 Python 파일 해시 |
| `controlled-12.json` | 고정 Git 변경 12개를 v1의 통제 응답과 현재 ver2에 적용한 결과. ver2 반복 판정 12/12 일치 |
| `release-downloads.json` | 공개 설치 파일 네 개를 전체 다운로드한 크기·SHA-256과 게시 시각 |
| `workflow-verification.json` | 제품 커밋의 CI와 세 플랫폼 릴리스 빌드 결과 |
| `summary.json` | 전체 테스트, 같은 UI 입력의 변경 전후 결과, 벤치마크와 한계 |

12개 사례의 `B01`은 Markdown 표이고, 32개 반례의 `B01-multiline-route`는 여러 줄 라우트다. 같은 식별자 접두사라도 다른 평가 입력이므로 혼동하거나 합산하지 않는다.

UI의 새 회귀 입력은 `desktop-ui/src/features/project-progress/ProjectProgress.test.tsx`이다. 기존 `b13d73f` 소스를 임시 폴더에 추출하고 동일 테스트 파일을 복사해 실행했다. 입력 파일의 SHA-256은 요약에 기록했다. 패키지 평가의 새 입력은 `drift_gate/tests/test_eval_runner.py`의 외부 폴더 실행·빈 입력 거부 여섯 검사다. 두 소스에서 같은 파일을 실행했고 SHA-256을 요약에 기록했다. 원시 테스트 로그와 설치 패키지는 Git 이력에 추가하지 않는다.

합성 평가이며 일반적인 PR의 정확도나 실제 사용자 PC에서의 성능을 입증하지 않는다. 상세 해석은 [릴리스 검증 보고서](../../review/release-readiness-2026-10-01.md)를 참고한다.
