# auto 개선안 구현 검증 자료

[구현·해석 보고서](../../review/drift-gate-auto-update-2026-10-07.md)를 참고한다.

- `python-complete.log`: 전체1,228 통과. 앞선1,225/1,227 검사 로그와 중간 실패 로그도 보존했다. type-only Express import의 잘못된 확신도 추가 통제로 거부한다.
- `evaluation-v2-verified.json`: Python/Git14개, 사실·의무·검증·게이트 각14/14.
- `express-v1-verified.json`: Express/Git8개, 네 축 각8/8.
- `*-first.json`: 새 suite 첫 실행을 별도로 보존했다.
- `generalization-v1-verified.json`: 원본 지원24/24, 경계 gate5/8, verified gate 일치2/8.
- `relation-after.json`: 이전 교차 조건 재현의 수정 후 입력·결과.
- `react.log`, `tsc.log`, `ruff-final.log`: 화면 호환·정적 검사 결과.
- `self-check.json`, `self-check-inputs.json`: 사용자 index를 변경하지 않는 별도 checkout 자체 검사 및 그 입력 해시.
- `verification.json`: 운영 소스와 이 폴더 근거의 파일 해시. 과거 영수증은 변경하지 않는다.
- `verification-final.json`, `self-check-final*.json`: 마지막 scope 보완 후 최종 파일 해시와 별도 자체 검사 snapshot.

서로 다른 suite의 분모를 합치지 않는다. 새 suite는 작성자 비맹검 통제이며 실제 PR 정확도가 아니다. `self-check-inputs.json`은 검사 당시 snapshot이다. 그 후 생성되는 자체 결과·해시 영수증은 자기 입력에 포함되지 않는다. 원격 CI나 새 설치본 결과는 이 폴더의 로컬 실행으로 대체하지 않는다.
