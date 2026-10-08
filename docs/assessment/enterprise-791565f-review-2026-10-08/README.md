# 791565f 검토 근거

- 대상: `791565fd88e109645379b2a2efcd6601840e4191`
- 리뷰: `../../review/drift-gate-enterprise-791565f-review-2026-10-08.md`
- Python: macOS arm64 / 3.11.15. 독립 schema 대조: jsonschema 4.26.0.
- reproduce.py / results.json: 의미·권한·캐시·평가 반례와 정적 import 대조군.
- reproduce_refs.py / refs-results.json: 실제 고정 엔진 ed9f904 실행 후 결정적으로 ref를 이동한 반례. 엔진 결과나 attestation은 조작하지 않음.
- pytest.log: 고정 source를 설치한 별도 환경의 전체 회귀.
- ci-37744699455/: GitHub Desktop 실행의 Offline-check-* 산출물에서 복사한 원본 JSON 8개. CLI 6개, 종료 요약 2개.
- native-summary.json: 위 CLI JSON 6개에서 생성한 요약.
- 이 스크립트는 진단 자료이며 제품 코드/회귀 suite를 수정하지 않는다. 합성 반례를 실사용 정확도로 일반화하지 않는다.
- 재실행 시 고정 source를 설치한 전용 환경을 사용하고 결과를 새로운 파일에 기록한다.
- refs 스크립트는 DRIFT_GATE_REVIEW_ROOT=/absolute/path/to/source 환경 변수가 필요하다. source Git에는 ed9f904 객체가 필요하다.
