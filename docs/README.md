# 문서 안내

처음 사용한다면 [설치와 사용법](desktop-app.md)부터 읽으면 됩니다. 과거 실험 문서는 당시 입력과 결과를 보존한 기록이며, 현재 기능의 안내는 최신 사용 문서에서 확인하세요.

| 목적 | 문서 |
|---|---|
| Windows·Mac 설치와 화면 사용 | [데스크톱 앱 안내](desktop-app.md) |
| 구독 계정으로 선택형 LLM 검토 | [구독 LLM 연결](subscription-llm-review.md) |
| 문서 기준의 구현 현황을 확장하려는 계획 | [프로젝트 현황 계획](../계획.md) |
| 최신 구조 보완·기능 회귀·릴리스 검증 | [2026-10-01 검증 보고서](review/release-readiness-2026-10-01.md) |
| 문서 종류와 V5·V6·V7 구현 | [기능별 변경과 검증](review/document-kinds-v5-v7-2026-10-01.md) |
| 다음 대화에서 이어갈 상태 | [작업 인계](handoff-2026-10-01.md) |
| 빌드·설치 프로그램·릴리스 운영 | [데스크톱 CI](ops/desktop-ci.md) |
| 원본 버전과 개선본의 차이 | [12개 통제 사례](v1-ver2-controlled-comparison-2026-09-23.md) |
| P06·P10·Markdown 표 오류의 실제 수정 | [수정 후 재검증](v1-ver2-contract-fix-results-2026-09-23.md) |
| 기존 평가 밖에서 드러난 한계 | [과적합 점검](generalization-audit-2026-09-22.md) · [공개본 재검증](published-recheck-2026-09-29.md) |
| UI에 적용한 스킬과 요소 | [디자인 작업](design/desktop-redesign-skill-workflow.md) · [tool-ui 구성](design/tool-ui-integration-2026-09-29.md) |

`assessment/`는 고정 입력과 평가 원본, `review/`는 분석·재검증, `design/`은 설계 근거, `ops/`는 배포 절차, `assets/`는 문서용 캡처입니다. 실행 로그·빌드 산출물·설치 파일은 GitHub Actions와 Releases에서 관리합니다.
