# 검증 결과의 재검증 자료

- `verify.py`: 고정 `f43cada`와 과거 `01e28e1` 소스를 임시 복사본에서 실행하는 재검증 프로그램.
- `saved-evidence/`: 원격 push·PR CI에서 이번에 다시 내려받은 자체 검사 JSON과 실행 메타데이터.
- `verified-run/`: 위 원격 원본을 사용한 최종 결과. `results.json`에 18조건, 기대 결과, 실제 결과, 종료 코드, 원본 SHA-256이 기록된다.
- `verified-run/latest-gate.html`: 최신 자체 정책 push 검사를 제품으로 재실행해 생성한 HTML. 과거 HTML을 덮어쓰지 않았다.
- `run/`: 이전 로컬 다운로드 자료로 처음 시험한 중간 실행. 최종 판단은 `verified-run/`을 사용한다.
- `policy-regressions.log`: 현재 자체 정책 회귀 테스트 14개 재실행 결과.

한계 실험의 `expected=fail`은 더 강한 검증을 원할 때의 사전 기대다. 빈 diff·Git 미등록 파일·정책 밖 파일이 실제 현재 제품 계약상 반드시 실패해야 한다고 가정한 점수가 아니다. `limitations_found` 다섯 항목을 제품 정확도나 버그율로 환산하지 않는다.

설명과 우선순위: [재검증 리뷰](../../review/drift-gate-meta-verification-2026-10-06.md).
