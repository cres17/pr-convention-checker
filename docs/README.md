# 문서 안내

처음 사용한다면 [설치와 사용법](desktop-app.md)부터 읽으면 됩니다. 날짜가 붙은 검증 문서는 당시 입력과 결과를 보존한 기록이며, 현재 기능의 안내는 최신 사용 문서에서 확인하세요.

| 목적 | 문서 |
|---|---|
| Python 환경 변수·API 경로 내용 검사 | [focused-python 사용법](focused-python.md) |
| 삭제된 환경 변수 키 검사와 예외 설정 | [삭제 키 확인](removed-environment-keys.md) |
| 내용 검사와 승인 예외 설정 | [내용 검증 안내](content-verification.md) |
| 좁은 판정 범위·구현 순서 | [2026-10-13 논리 개선 계획](architecture/drift-gate-focused-logic-plan-2026-10-13.md) |
| Windows·Mac 설치와 화면 사용 | [데스크톱 앱 안내](desktop-app.md) |
| 구독 계정으로 선택형 LLM 검토 | [구독 LLM 연결](subscription-llm-review.md) |
| 남은 작업과 완료 기준 | [계획](../계획.md) |
| 프로젝트 현황 기능의 설계와 단계 | [현황 기능 설계](design/project-progress-plan-2026-09-29.md) |
| 빌드·설치 프로그램·릴리스 운영 | [데스크톱 CI](ops/desktop-ci.md) |
| 저장소 자체 정책 검사와 고정 엔진 | [자체 검사 운영](ops/drift-gate-self-check.md) |
| 판정·입력·MCP·데스크톱 계약 | [Gate와 입력](contracts/gate-and-inputs.md) · [MCP 전송](contracts/mcp-transport.md) · [데스크톱 브리지](contracts/desktop-bridge.md) · [진행 현황 저장](contracts/progress-storage.md) |
| 문서의 동작 설명 12개 재현 검증 | [검증 보고서](review/drift-gate-claim-verification-2026-10-06.md) · [수정 계획](review/drift-gate-hardening-plan-2026-10-06.md) |
| 원본 버전과 개선본의 차이 | [12개 통제 사례](v1-ver2-controlled-comparison-2026-09-23.md) |
| P06·P10·Markdown 표 오류의 실제 수정 | [수정 후 재검증](v1-ver2-contract-fix-results-2026-09-23.md) |
| 기존 평가 밖에서 드러난 한계 | [과적합 점검](generalization-audit-2026-09-22.md) · [공개본 재검증](published-recheck-2026-09-29.md) |
| UI에 적용한 스킬과 요소 | [디자인 작업](design/desktop-redesign-skill-workflow.md) · [tool-ui 구성](design/tool-ui-integration-2026-09-29.md) |

`assessment/`는 고정 입력과 평가 원본, `review/`는 분석·재검증, `design/`은 설계 근거, `ops/`는 배포 절차, `assets/`는 문서용 캡처입니다. 2026-10-20에 근거로 쓰지 않는 중간 검증 기록을 정리했습니다. 삭제한 기록은 Git 이력에 남아 있습니다. 실행 로그·빌드 산출물·설치 파일은 GitHub Actions와 Releases에서 관리합니다.
