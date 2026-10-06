# 첫 원격 실행에서 확인한 두 가지와 수정

소스 커밋 `5550c14`의 첫 push/PR CI와 Desktop build에서 다음 문제가 확인됐다. 로컬 macOS 설치본 검증 결과는 그대로 보존한다.

- Windows Python 3.10/3.11/3.12: `test_backup_at_its_exact_byte_limit_round_trips` 실패. JSON을 텍스트 모드 기본 줄바꿈으로 기록해 Windows에서 CRLF로 확장됐다. 사전 UTF-8 직렬화 바이트 수와 실제 파일 크기가 달랐고, 정확한 크기 상한 검사도 달라졌다. `json_store.write_json`의 줄바꿈을 LF로 고정했다. Windows 기본 CRLF 변환을 모사해 실제 저장 바이트가 사전 직렬화 바이트와 정확히 같은지 검사하는 회귀 테스트를 추가했다.
- Intel macOS: 119개 추가 상한과 121개 복구·내보내기·삭제 시험 두 개가 기본 5초 제한을 초과했다. 119/121개의 실제 DOM 행과 모든 행동·상한 검증을 유지하고, 매번 전체 jsdom 접근성 트리를 계산하는 역할 검색 대신 실제 button의 텍스트를 검색하게 했다. 전역 timeout을 늘리거나 테스트·항목을 생략하지 않았다. 접근성 역할·라벨 시험은 다른 화면 테스트에서 유지한다.

수정 후 로컬: Python **834 passed**, React **122 passed**, Ruff E9,F와 변경 코드 공백 검사 통과. 테스트 검색 비용 개선을 실제 제품 렌더링 성능 개선으로 주장하지 않는다.

실패 실행은 [push CI](https://github.com/cres17/pr-convention-checker/actions/runs/37413128104), [PR CI](https://github.com/cres17/pr-convention-checker/actions/runs/37413132330), [Desktop build](https://github.com/cres17/pr-convention-checker/actions/runs/37413128101)에 남아 있다. 이 수정은 별도 후속 커밋으로 푸시하고 새 커밋의 CI·세 플랫폼 설치본을 다시 확인한다. 최종 성공 여부는 해당 커밋의 Actions 결과와 이 대화의 최종 보고를 기준으로 한다.
