# 설치본 삭제 키 버튼 확인 (2026-10-20)

## 대상
- 설치본: Desktop app build run 39191991641(`3101d57`)의 `DriftGate-macOS-arm64.dmg`
  - SHA-256 `de3c1ba4756c387a6605fef7ae942820c8b67dbc3e1ee005b85c13d4f221b1aa`(CI 산출물과 Mac 수신본 일치)
  - `6356126`과의 차이는 문서 2개 삭제뿐이다.
- 실행: 마운트한 DMG 안의 앱을 직접 실행했다. /Applications의 앱은 바꾸지 않았다.
- 환경: macOS arm64, 2026-10-20 15:01~15:04 KST
- 조작: 원격 화면 조작 도구로 클릭과 키 입력을 보냈다. 사람이 직접 누른 시험은 아니다.
- 시험 저장소: `_dg-transfer/sample`(커밋하지 않음)
  - `src/app.py`에서 `LEGACY_TOKEN`, `OLD_REGION` 읽기를 지웠다. `.env.example`에는 두 키가 남아 있다.
  - `OLD_REGION`은 `docker-compose.yml`의 `environment:`에 남겼다.
  - 정책: `env-keys`, severity blocker.
- 소스 엔진 기대값: `fail`/`block`. `LEGACY_TOKEN`은 위반, `OLD_REGION`은 `config` 경고.

## 결과

| 단계 | 조작 | 관찰 | 기대와 일치 |
|---|---|---|---|
| 1 | 검사 | "수정 필요"(fail). 패널에 두 키, 키마다 버튼 2개 | 예 |
| 2 | 검사 끄기 → 확인창 | 기본 선택 No. 5초 이상 응답 없이 대기, 파일 변경 없음 | 예 |
| 3 | 2에서 Yes | `check_removed_keys: false` 저장, 재검사 "통과" | 예 |
| 4 | 정책 복원 후 LEGACY_TOKEN 예외 → 확인창 | 5초 대기, 파일 변경 없음 | 예 |
| 5 | 4에서 **No** | 3초 안에 "삭제 키 설정을 저장했습니다", `exclude_removed_keys: [LEGACY_TOKEN]` 저장, 재검사 "주의" | **아니오** |
| 6 | 정책 복원 후 같은 버튼 → **Esc** | 16초 안에 같은 내용 저장 | **아니오** |

- 첫 시도(단계 4 이전)도 No를 누른 뒤 저장됐다. 다만 저장 시점과 다른 클릭의 순서가 분명하지 않아 위 표에서 뺐다.
- 예외 저장 후 판정은 "주의"(warn)였다. `OLD_REGION` 경고만 남았다. 이 부분은 문서와 일치한다.

## 판단
- **사실:** 이 설치본에서 확인창의 취소(No, Esc)가 저장을 막지 못했다. 조건을 맞춘 2회 시험 모두 그랬다.
- **사실:** `web_app.py`의 `setRemovedKeyPolicy`는 `QMessageBox.question`의 반환값이 Yes가 아니면 바로 반환하도록 작성돼 있다.
- **사실:** `test_desktop_web.py`는 `QMessageBox.question`을 가짜 함수로 바꿔 검사한다. 실제 확인창의 반환값 경로는 자동 테스트하지 않는다. 2026-10-16 `validation.md`의 "기본 취소·취소 시 무변경" 항목도 이 방식의 확인이다.
- **원인 미확인:** 다음 중 무엇인지 아직 확인하지 않았다.
  - macOS 기본 확인창과 PySide6 사이의 반환값 문제
  - 같은 요청이 두 번 들어와 확인창이 겹치는 문제
  - 원격 입력 도구의 전달 방식
- 사람이 직접 누르는 재현이 필요하다.
