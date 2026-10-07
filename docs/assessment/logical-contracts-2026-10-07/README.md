# 논리 구조 수정의 실행 근거

대상: d262ec2 기반 미커밋 작업 트리. 기존 평가 원본과 과거 결과를 보존한 새 실행이다.

verification.json은 실행 상태·환경·결과·소스 및 근거 해시를 기록한다. python-full.log, react.log, tsc.log, ruff.log, ui-build.log에서 실행 결과를 확인한다. fixed-evaluation.json과 generalization-audit.json은 기존 고정 입력의 새 실행이다. 합성 점수는 실제 PR 정확도가 아니다.

reproduce.py는 입력 cases.json을 읽어 순수 엔진에서 대표적인 정상·반례·확인 불가를 재실행한다. 스냅샷 문자열은 작은 합성 예제이며 실제 프로젝트 원문·비밀정보가 아니다. results.json은 이번 실행의 원본 결과이고 재실행할 때에는 다른 출력 경로를 지정한다.

self-check.json은 현재 후보를 임시 checkout에 추가한 뒤 자체 정책으로 검사한 결과다. 사용자의 index와 삭제한 두 인수인계 파일은 변경하지 않았다. 로컬 점검과 원격 CI·배포·실기기 검증을 구분한다.
