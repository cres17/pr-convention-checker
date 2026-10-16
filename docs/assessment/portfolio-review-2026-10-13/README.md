# 포트폴리오 코드 검토 근거 · 2026-10-13

대상: a76306f5636b64daa617e3f90158a79785e07ad1.

[평가 문서](../../review/drift-gate-portfolio-senior-review-2026-10-13.md)

- probes.py: 지원 schema의 숫자 동등성·유한 object, holdout 분모와 지표 반례. 임시 결과를 stdout으로 출력한다.
- probes.json: 실제 실행 결과. label source=human은 지표 API를 시험하는 합성 필드이며 사람 평가를 했다는 뜻이 아니다.
- pytest.log / react.log: 이번 전체 회귀 원본. 전체 통과는 반례가 없다는 증명이 아니다.
- environment.json: 검증 환경. 현재 commit을 별도 환경에 editable 설치했다.
- validation.json: 정적 검사·원격 상태·채점표. 점수는 검토자의 정성적 판단이다.
- sha256.json: 이 폴더 파일 손상 확인용 digest이며 외부 인증이나 서명이 아니다.

재현: 고정 source와 jsonschema==4.26.0을 설치한 전용 환경에서 `python probes.py > new-results.json`.
기존 결과 파일을 덮어쓰지 않는다. 제품 수정·커밋·푸시는 수행하지 않았다.
