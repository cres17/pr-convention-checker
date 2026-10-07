# S2-a: 불변 분석 입력·manifest·메모리 재실행

## 결과와 범위

공통 inspection이 분석 직전에 전달된 입력을 불변 capsule로 봉인하도록 수정했다.
분석기는 capsule에서 만든 private copy를 사용한다. 호출자가 기존 객체를 바꾸거나
검사 이후 원래 저장소가 바뀌어도 캡처된 입력은 바뀌지 않는다. `inspect_snapshot`으로
캡처된 입력을 현재 엔진에서 다시 분석할 수 있다.

S2 전체 완료는 아니다. 이번 S2-a는 **전달받은 관찰의 동일성**을 고정한다. Git OID에서
원본 bytes를 수집하는 별도 모드, trusted policy authority, 엔진·파서 아티팩트 고정,
디스크 bundle·receipt의 원자적 공개와 최신성 검증은 다음 단계다. capsule은 메모리에만
남으므로 앱 재시작 후 replay 저장소로 쓰지 않는다.

작업 기준은 `ver2` HEAD `d262ec2faff3b98c917e3e99f7b6260cf0514ff3`에 누적된 미커밋
작업 트리다. 이전 S1-e 소스 277개의 해시와 고정 입력 5개가 같은 것을 확인하고
[새 근거 폴더](../assessment/snapshot-implementation-2026-10-07/)에 실행을 기록했다.
기존 작업과 삭제 파일을 보존했으며 커밋·푸시는 하지 않았다.

## 운영 코드 변경

| 경계 | 변경과 보장 |
| --- | --- |
| `core/models/input_manifest.py` | 순수 불변 artifact·manifest, 버전 있는 Python JSON encoding |
| `adapters/snapshot.py` | 파일·정책·ignore 승인 근거·UTC 날짜·옵션·출처를 bytes capsule로 봉인, 재실행마다 복사 |
| 공통 `inspection.py` | 분석 전 봉인, manifest/payload 정합성 확인, capsule 기반 enrichment·core 실행 |
| 정책·문서 읽기 | 한 번의 1 MB 제한 읽기, 줄바꿈 보존, 관찰 가능한 교체·크기·수정 변경 거부 |
| 정책 source binding | 원문에서 해석한 정책과 제출된 평가 정책이 다르면 input error |
| 환경 문서 | 키 이름과 함께 실제로 관찰한 원문을 private 입력에 보관, 공개 JSON에는 값 미포함 |
| CLI·MCP·Desktop 서비스·Action | 기존 공통 inspection을 통해 `execution.input_capture` 추가 |
| compact MCP | manifest 항목 목록 생략, 전체 개수·digest·생략 표시 보존 |

새 모델은 mutable `ChangedFile`을 즉시 제거하지 않는다. 기존 core·reporter 인터페이스로
복사본을 전달해 정책 판정 호환성을 유지한다. 순수 core 직접 호출은 파일 수집 경계가
아니므로 이 capsule을 자동 생성하지 않는다. 기존 `input_digest_version=3`도 유지하고,
새 캡처에는 별도 schema와 digest protocol을 부여했다.

## 상태와 해시의 의미

present의 빈 bytes, adapter가 선언한 absent, unavailable, not-collected, limited,
unsupported를 구분한다. rename의 before는 이전 경로에 연결하고 삭제 파일의 before를
남긴다. 신규·삭제 파일의 없는 쪽을 `''`로 전달하던 기존 관례는 해당 쪽의 absent로
해석한다. 기존에 존재하는 빈 파일의 `''`는 present이며 서로 다른 manifest다.

문서 원문이 읽혔지만 YAML 해석에 실패할 수 있다. 이때 관찰한 원문은 present,
의미 입력은 unavailable로 남긴다. 원문을 버리거나 검증 성공으로 바꾸지 않는다.
내용과 명시 부재의 모순, 중복·비정상 경로, manifest/payload 변조, 비유한 숫자는 거부한다.

`observed_text_sha256`는 adapter가 제공한 문자열을 UTF-8로 표현한 해시다. 현재 Git
adapter에는 대체 문자 디코딩·줄바꿈 변환이 있으므로 모든 원본 disk/blob bytes를
보존했다고 주장하지 않는다. 정책과 새 문서 reader의 CRLF는 보존한다.

JSON object key는 정렬하고 array·파일 관찰·정책 group 순서는 보존한다. Unicode는
정규화하지 않는다. NaN/Infinity는 금지한다. Python producer encoding v1이며 RFC 8785나
다른 언어 producer와의 적합성 인증은 아니다. UUID·실행 시간은 capsule에서 제외하고
시도별 execution에 둔다. 현재 캡처 위치·출처도 input identity에 결합된다.

`atomicity=per-artifact-observation`, `original_bytes_certified=false`,
`revision_certified=false`, `selection_complete=false`,
`policy_authority=unverified-caller-input`을 명시한다. 승인 근거를 보관하더라도 과거 승인과
고정 UTC 날짜의 재실행이지 현재 승인을 재조회한 결과가 아니다. fstat 전후 비교는
관찰 가능한 경합 방지이며 ABA·동시 여러 파일 수집의 증명이 아니다.

## 실제 Git 대조와 회귀 검증

[실제 로컬 대조](../assessment/snapshot-implementation-2026-10-07/snapshot-controls-final.json)에서
CLI·MCP·Desktop manifest가 같았다. 옛 문서에서는 fail, 코드·문서를 함께 갱신하면 pass였다.
원래 저장소를 삭제한 뒤 캡처를 재실행해 최초 fail과 같은 판정·검증 상태·규칙·집계를
얻었다. input identity는 같고 attempt ID는 달랐다. 관찰 source hash도 통제 원문과 같았다.
검사 8/8이 통과했다. 실제 Qt 화면 조작이나 설치본 시험은 아니다.

| 검사 | 결과 |
| --- | --- |
| Python 전체 | 1,706 통과, skip 0 |
| 신규 입력 캡처 회귀 | 46개, 전체 검사에 포함 |
| 입력·projection·진입점·Git 관련 회귀 | 209 통과 |
| React | 126 통과, 11개 파일 |
| TypeScript·UI 빌드·Ruff E9,F·diff 검사 | 통과 |
| 기존 진입점 프로브 | 8/8, GitHub transport 모의 응답 |
| Python/Git 고정 평가 | 14/14, 네 평가 축 유지 |
| Express/Git 고정 평가 | 8/8, 네 평가 축 유지 |
| 고정 합성 평가 | 21/21, 판정·보고서 유지 |
| 자체 정책 | pass / unverified, 98개 입력 중 미추적 source 49개 명시 포함 |

UI 빌드는 별도 임시 폴더에 만들었으며 기존 큰 chunk 경고가 있었다. 번들 화면을
교체하지 않았다. 위 회귀와 대조는 작성자가 만든 비맹검 사례이며 PR 정확도 측정이 아니다.

고정 suite bytes는 바꾸지 않았다. 네 평가 축과 고정 보고서는 실행 메타데이터·시간을
제외하면 이전과 같다. 다만 `alias-preexisting-document`, `missing-getter-import`의 기존
execution 입력 해시는 바뀌었다. 이전에는 환경 문서의 키 이름만 결합했으나 이제 관찰
원문 해시도 결합하기 때문이다. 이를 입력 해시가 모두 유지됐다고 보고하지 않는다.

첫 회귀에는 기존 신규 파일의 빈 before 관례 때문에 10건이 실패했다. 의미 있는 before와
부재 관례를 구분해 수정했다. 첫 실제 진입점 대조는 7/8이었다. CLI에 local-git 출처가
빠져 MCP·Desktop과 캡처 모드가 달랐다. 출처와 정책 경로 표현을 일치시킨 뒤 8/8이 됐다.
실패 로그와 첫 결과도 근거 폴더에 보존했다.

## 근거와 다음 단계

- [실행·소스·고정 입력 해시 영수증](../assessment/snapshot-implementation-2026-10-07/verification.json)
- [이전 결과와 해시 차이 비교](../assessment/snapshot-implementation-2026-10-07/comparison.json)
- [로컬 재현 프로그램](../assessment/snapshot-implementation-2026-10-07/probe_snapshot.py)
- [전체 Python 로그](../assessment/snapshot-implementation-2026-10-07/python-full-final.log)
- [관련 회귀 로그](../assessment/snapshot-implementation-2026-10-07/targeted-final.log)
- [자체 정책 결과](../assessment/snapshot-implementation-2026-10-07/self-check-final.json)

다음 S2-b는 불변 Git OID의 원본 artifact 수집, Subject와 manifest 연결, 별도 신뢰 정책
ref/digest와 권한 검증이다. 그 뒤 디스크 증거 bundle·receipt·최신성·재시도 계약을 다룬다.
원격 CI·native 설치본·Windows/Linux 실행·실제 화면·독립 홀드아웃은 이번에 확인하지 않았다.
기존 auto 경계 1/8을 재실행하거나 개선했다고 주장하지 않는다.
