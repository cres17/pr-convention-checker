# Drift Gate 검증과 AI 주장 거부 사례 (2026-10-06)

검증 대상: `ver2` `f43cada2ea177b63cb0ac4a79be37071113a5191`. 비교 기준: 직전 푸시 `7244969`, `main` `bffc655`.
실행 환경: Linux x86_64, Python 3.11. Windows·macOS 실행은 이번에 하지 않았다.
원본 입력·결과는 [`docs/assessment/ai-claim-rejection-2026-10-06/`](../assessment/ai-claim-rejection-2026-10-06/)에 새 경로로 보존했고 기존 평가 결과는 수정하지 않았다.

## 1. 결론

| 질문 | 결과 |
|---|---|
| 현재 결과물이 Drift Gate 정책을 통과하는가 | 통과. 자체 정책·기본 정책 모두 푸시 변경분과 PR 전체 변경분에서 `pass`다. |
| `pass`는 AI가 쓴 문서가 맞다는 뜻인가 | 아니다. AI가 쓴 계약 문서의 주장 12개를 실제로 실행해 확인한 결과 **거부 3개, 부분 수용 3개**, 수용 6개였다. 이 문서들이 바뀌었다는 이유로 정책은 통과했다. |
| 도구의 `self-audit`가 틀린 주장을 걸러내는가 | 걸러내지 못했다. 거부된 주장 3개를 포함해 문서 주장 12개가 모두 `supported`였고, 사실로 확인한 주장(C14)만 `unsupported`였다. |
| 마무리해도 되는가 | 아직 아니다. 게이트 판정의 정확성에 직접 닿는 결함 3건(§4의 D1~D3)을 재현했다. |

이번 작업은 코드를 수정하지 않았다. 아래 개선 항목은 모두 재현 결과이며 수정 제안은 의견으로 표시한다.

## 2. 현재 결과물을 Drift Gate로 검증

| 실행 | 정책 | 기준 | 결과 |
|---|---|---|---|
| 자체 검사 | `.drift-gate.self.yml` | `7244969` (푸시 변경분, 248개 파일) | pass, 6개 규칙 모두 pass |
| 자체 검사 | `.drift-gate.self.yml` | `main` (PR 전체, 649개 파일) | pass, 6개 규칙 모두 pass |
| 기본 검사 | `.drift-gate.yml` | `7244969` | pass |
| 기본 검사 | `.drift-gate.yml` | `main` | pass |
| `docs-check` | README | - | 문제 없음 |
| 고정 합성 평가 (`audit_generalization.py`) | - | 현재 소스 | 지원 24/24, 경계 1/8 |
| Python | - | - | 871 통과·3 skip (이 환경에 `zstandard`가 없어 skip, 합계 874) |
| React·`tsc`·`ruff E9,F` | - | - | 122 통과·통과·통과 |

- 사용자가 올린 자체 검사 JSON(`requested_base 01e28e1`, 137개 파일)과 같은 `pass`이며, 기준 커밋이 달라 파일 수는 다르다. 보고서의 Python 874, React 122도 이 환경에서 같은 수로 재현됐다.
- 경계 사례 1/8은 지원하지 않는다고 문서에 적힌 범위다(`B01`, `B04`~`B08` 미탐지, `B03` 오탐). 지원 사례는 이전 보고(21/24)보다 늘어 24/24다.
- **자체 정책이 보지 않는 코드** (`self-pr`의 `coverage.unmatched`, 문서 제외 36개). 정책의 어떤 규칙도 이 경로와 일치하지 않아, 변경해도 문서 갱신을 요구하지 않는다:
  `action.yml`, `drift_gate/adapters/grammar_resources.py`, `drift_gate/adapters/parser_hashes.json`, `drift_gate/desktop/package_check.py`, `drift_gate/desktop/service.py`, `drift_gate/desktop/doc_links.py`, `drift_gate/adapters/eval/runner.py`, `desktop-ui/package.json`, `scripts/*.py` 등.
  파서 무결성(`grammar_resources.py`, `parser_hashes.json`)처럼 보안 의미가 큰 파일이 포함된다. 정책은 이를 `coverage`에 기록하므로 숨기지는 않는다.
- 푸시 변경분 코드 파일 61개 중 22개(36%)는 문법 분석 대신 "Partial or invalid diff fragment" 휴리스틱으로 처리됐다. PR 전체(대부분 새 파일)에서는 193개 중 13개(7%)다. 수정된 기존 파일은 diff 조각만 파싱해서 문법 분석이 자주 실패한다.

## 3. AI 주장 검증 사례

대상은 AI 작업 결과로 제출된 `docs/contracts/gate-and-inputs.md`, `docs/contracts/mcp-transport.md`와 `README.md`의 주장이다(README 문장의 작성 주체는 확인하지 못했다). 원문 그대로 `[x]`로 체크한 목록([`claims-as-asserted.md`](../assessment/ai-claim-rejection-2026-10-06/claims-as-asserted.md))을 만들고, 제품의 `self-audit`로 `7244969` 기준 변경분에 대조한 뒤 별도 실행으로 각 주장을 검증했다([`reproduce.py`](../assessment/ai-claim-rejection-2026-10-06/reproduce.py), [`results.json`](../assessment/ai-claim-rejection-2026-10-06/results.json)).

| ID | 주장 요약 | `self-audit` | 독립 검증 |
|---|---|---|---|
| C01 | 변경 수집 실패는 종료 코드 2 | supported | 수용 |
| C02 | JSON 모드 입력 실패는 `input_error` JSON | supported | **부분 수용** |
| C03 | base를 commit으로 확정, NUL 경로, literal pathspec | supported | 수용 |
| C04 | 새 파일은 index에 추가해야 수집 | supported | 수용(주의 있음) |
| C05 | 커밋한 변경은 `--base main`으로 비교 (README) | supported | **거부** |
| C06 | 1,000,000바이트 초과 줄 배출 후 다음 요청 처리 | supported | 수용 |
| C07 | 잘못된 UTF-8·JSON 한 줄이 뒤의 요청을 잃게 하지 않음 | supported | 수용 |
| C08 | JSON-RPC·기존 경로 지원, batch 미지원 | supported | **부분 수용** |
| C09 | 비유한 숫자는 직렬화하지 않음 | supported | **거부** |
| C10 | Python 환경 키는 실제 호출에서 읽음, 주석·문자열 제외 | supported | 수용 |
| C11 | `env-keys` 검사는 지원 문법에 한해 확인 | supported | **부분 수용** |
| C12 | 코멘트 전용 변경을 제외하며 포맷 변경 구별은 부정확 | supported | **거부** |
| C13 | 자체 정책 검사 pass | supported | 수용 (§2) |
| C14 | Python 874·React 122 통과 | **unsupported** | 수용 (§2) |

### 3.1 받아들이지 않은 주장

**C05 README의 `--base main` 안내 → 거부.** 기준 브랜치가 앞서 나간 뒤 기능 브랜치에서 `--base main`을 쓰면 기준 브랜치가 추가한 변경이 "내 삭제"로 잡힌다.
- 재현: `main`이 `src/routes/new.py`를 추가한 뒤 기능 브랜치에서 `check --base main` → `fail`, 위반 `api-contract-sync`, 트리거 파일 `src/routes/new.py:deleted`. 같은 브랜치를 `git merge-base`로 구한 커밋으로 비교하면 `pass`.
- 원인: `GitAdapter`가 `git diff <commit>`(작업 트리 대 기준 커밋)을 쓰고 merge-base를 계산하지 않는다(`git/client.py`).
- CI는 PR 병합 커밋을 체크아웃하므로 영향이 없다. 로컬 사용에서만 발생한다.

**C09 비유한 숫자 → 거부.** 이 주장은 레거시 경로(`{"tool":..}`)에서만 맞다.
- 재현: 저장소 밖의 JSONL에 `"score": NaN`을 넣고 `drift_gate_history`를 호출. 레거시 경로는 "Out of range float values are not JSON compliant"로 거부하지만, JSON-RPC `tools/call`은 결과 `text` 안에 `NaN` 토큰을 그대로 담아 반환한다(`json.dumps(tool_result, ...)`가 `allow_nan` 기본값 사용, `server.py`).
- `text`를 JSON으로 다시 파싱하는 클라이언트는 실패한다.

**C12 comment-only 판정 → 거부(방향이 반대).** 문서는 "의미 없는 포맷 변경을 구별하지 못한다"는 한계(불필요한 경고)만 적었다. 실제 결함은 **의미 있는 변경을 코멘트로 판정해 규칙을 건너뛰는 것**이다.
- 원인: `_is_comment_or_blank`가 줄이 `#`, `//`, `/*`, `*`로 시작하면 코멘트로 본다(`intensity.py`). 파이썬의 `*extra,`·`**options,`, C의 `#define`, Go의 `*p = v`, JS의 generator `*routes() {`가 모두 코멘트다.
- 재현(규칙: `src/**`·`include/**` 변경 시 `docs/api.md` 요구, `min_change_intensity: impl-only`):

  | 변경 | 결과 |
  |---|---|
  | 시그니처에 `*extra,` 추가 | pass (규칙 unmatched) |
  | 시그니처에 `**options,` 추가 | pass |
  | `#define API_VERSION 1` → `2` | pass |
  | 대조: `c=2,` 추가 | fail |
  | 대조: 실제 코멘트 줄 추가 | pass |

- 이 저장소의 `.drift-gate.self.yml`은 모든 규칙에 `min_change_intensity: impl-only`를 쓰므로 같은 경로로 우회된다.

### 3.2 부분 수용

- **C02**: Git 수집 실패는 `input_error` JSON(종료 2)이 맞다. 그러나 `self-audit --json`에서 체크리스트 파일이 없으면 종료 1, stdout 비어 있음, 일반 문장 오류다. 기본 체크리스트 경로도 `고쳐야할점.md`로 고정돼 있다(`runner.py:470`).
- **C08**: batch 거부, 두 경로 지원은 맞다. 그러나 JSON 파싱 실패는 JSON-RPC 오류가 아니라 `{"ok": false, "error": ...}`(id·jsonrpc 없음)이고, `id` 없는 `tools/list` 알림에도 응답한다.
- **C11**: Python은 `.env.example` 갱신 시 pass. Go·Java·Ruby·Vite(`import.meta.env`)는 `.env.example`을 정확히 갱신해도 warn("No static new environment keys could be established")이다. 문구는 정직하지만 문서화된 `.env.example` 갱신이 충족으로 인정되지 않는다.

### 3.3 도구가 주장 검증에 실패한 이유 (`self-audit`)

사실: `self-audit`는 체크된 항목이 변경분과 겹치는지만 본다(`core/self_audit/matcher.py`). 항목 문장의 경로 조각(길이 4 이상, 예 `drift_gate`, `adapters`, `core`)이 변경 파일 경로에 들어 있으면 근거로 인정한다. 결과:
- C10(근거 파일 `python_syntax.py` 하나를 지목)의 `evidence`가 30개 파일이다. 지목하지 않은 `drift_gate/desktop/*.py`까지 포함된다.
- C05(README 주장)가 무관한 `docs/assessment/**/README.md` 8개로 `supported`가 됐다.
- C14는 파일·함수 이름이 없어 근거 0개로 `unsupported`가 됐고, 이 주장은 사실이다.

즉 `supported`는 "주장과 관련 있어 보이는 파일이 바뀜"이지 "주장이 참"이 아니다. 이 도구만으로 AI의 확인 완료 표시를 걸러낼 수 없다.

## 4. 개발 필요 항목

심각도·규모는 의견이고, 재현 여부는 사실이다. 번호는 권고 순서다.

| ID | 항목 | 재현 | 심각도 | 규모 |
|---|---|---|---|---|
| D1 | comment-only 판정이 코드 줄을 코멘트로 처리해 규칙을 건너뜀 (`#`·`*`·`//` 시작 줄) | O (§3.1 C12) | 높음 | 작음~중간 |
| D2 | 정책 파일 없음·`--policy` 오타·하위 디렉터리 실행 시 `pass`(평가 규칙 0개, 종료 0) | O | 높음 | 작음 |
| D3 | `--base main`이 merge-base를 쓰지 않아 뒤처진 브랜치에서 오탐(BLOCKER까지) | O (§3.1 C05) | 높음 | 작음 |
| D4 | 잘못된 정책 파일이 traceback·종료 1(= 위반 `fail`과 같은 코드) | O | 중간 | 작음 |
| D5 | `review`를 저장소 하위 디렉터리에서 실행하면 종료 2 (이번 변경으로 생긴 회귀) | O | 중간 | 작음 |
| D6 | `self-audit` 근거 매칭이 느슨해 거짓 `supported` 양산 | O (§3.3) | 중간 | 중간 |
| D7 | `env-keys` 검사가 Python·`process.env`만 지원, 그 외는 항상 warn | O | 중간 | 중간 |
| D8 | MCP: JSON-RPC 결과 텍스트에 `NaN`, 파싱 오류·알림 응답 형식 | O | 낮음~중간 | 작음 |
| D9 | MCP 도구 인자(`path`, `policy_path`, `repo_root`)가 임의 경로를 읽음 (`drift_gate_history`가 저장소 밖 JSONL의 내용을 반환) | O | 중간(의견: 프롬프트 주입된 에이전트가 쓸 수 있음) | 작음 |
| D10 | 추적되지 않는 새 파일을 경고 없이 건너뜀 (`scanned_files: 0`, `pass`) | O | 중간 | 작음 |
| D11 | 수정된 파일의 문법 분석이 36%에서 diff 조각 파싱 실패 → 휴리스틱 | O (§2) | 중간 | 중간~큼 |
| D12 | 자체 정책이 보지 않는 보안 관련 경로(§2) | O | 낮음~중간 | 작음 |
| D13 | `push` 이벤트의 `github.event.before`가 0이면(새 브랜치 첫 푸시) 자체 검사 job이 오류 종료 | 미재현. `ci.yml`의 `github.event.before` 사용과 GitHub 이벤트 사양(새 브랜치 푸시는 `before`가 0)에 근거한 추정 | 낮음 | 작음 |

### 제안 (의견)

1. **D2·D4·D5를 한 번에**: 정책 해석 위치를 저장소 루트 기준으로 고정하고, 없거나 잘못된 정책은 종료 2의 `input_error`로 처리한다. 제품 기본 동작(정책 없음 → 안내문과 pass)은 `init` 안내가 있으므로 `--policy`를 명시한 경우만 오류로 두는 절충도 가능하다. 판단은 사용자에게 있다.
2. **D3**: `git merge-base <base> HEAD`를 기준으로 쓰고 작업 트리와 비교한다. README는 수정하거나 `--merge-base` 옵션을 문서화한다.
3. **D1**: 줄 시작 문자열 대신 언어별 코멘트 규칙을 쓴다. 최소 수정은 `*`·`#`를 파일 확장자로 제한하는 것이다(`#`은 Python·Ruby·Shell·YAML만, `*`는 `/* */` 블록 안에서만). 회귀 테스트로 §3.1 표의 5개 사례를 고정한다.
4. **D6**: 항목에 명시한 경로·함수·테스트 이름이 변경분에 있어야만 `supported`로 판정하고, 경로 조각 매칭은 보조 정보로만 표시한다. 근거 수가 많은 항목에는 경고를 둔다.
5. **D9**: MCP 경로 인자를 현재 저장소 하위로 제한하거나 `--allow-path` 같은 명시적 허용을 둔다.
6. **D10**: `git ls-files --others --exclude-standard`로 새 파일을 세어 "추적되지 않는 파일 N개를 건너뜀"을 결과에 남긴다.
7. **D11**: diff 조각 대신 기준·현재 전체 파일을 `git show`로 읽어 파싱한다. 효과는 가설이며 구현 후 기존 합성 평가와 같은 입력으로 비교해야 한다.
8. 문서 수정: `docs/contracts/gate-and-inputs.md`·`mcp-transport.md`·README의 C05·C09·C12 문장을 위 결과에 맞게 고친다. 테스트 이름이나 문서 변경만으로 주장이 참이 되지 않는다.

## 5. 이전 검토 항목의 해소 확인

| 이전 지적 | 현재 |
|---|---|
| 내보낸 초안 JSON을 앱이 읽지 못함 | 해소: `import_draft`와 `importProgressDraft` 추가, 16MB 상한, `NaN` 거부, 다른 프로젝트 초안 거부 |
| `closeDraftSessions`가 최대 10초 대기·예외 처리 없음 | 해소: 비차단 종료와 `OSError` 로그 처리 |
| 문법 분석 실패가 사용자 화면에 보이지 않음 | 해소: `AnalysisNotice` 추가 |
| GitHub Actions를 태그로 고정 | 해소: `.github/workflows/*.yml`의 외부 action 26개가 모두 커밋 해시 고정. 단 사용자에게 배포되는 `action.yml`은 `actions/upload-artifact@v4` 태그 그대로 |
| 초안 검증기의 예외 안정성 | 확인: 변형 초안 6,000개 퍼징에서 예외 0건 |

## 6. 확인하지 못한 것

- 사용자 보고서의 원격 결과 JSON 6건과 CI 아티팩트는 내려받지 않았다. 보고서 수치(CI 826/821 등)는 인용만 하고 재현하지 않았다.
- Windows·macOS에서 이번 프로브를 실행하지 않았다. 파일명·잠금·경로 동작은 Linux 결과다.
- React 화면 동작은 테스트(122개)로만 확인했고 Qt 화면을 직접 조작하지 않았다.
- 프로브 규모는 사례 단위다. 오탐·미탐 비율을 일반화하지 않는다.
- `D9` 등 보안 항목의 실제 악용 가능성은 MCP를 호출하는 에이전트의 신뢰 가정에 달려 있고, 이를 평가하지 않았다.

## 7. 재현

```bash
python main.py check --policy .drift-gate.yml --base 7244969 --json
python scripts/check_self.py --base 7244969 --out build/self-check.json
python scripts/check_self.py --base origin/main --out build/self-check-pr.json
python main.py self-audit --checklist docs/assessment/ai-claim-rejection-2026-10-06/claims-as-asserted.md --base 7244969 --json
python docs/assessment/ai-claim-rejection-2026-10-06/reproduce.py --repo . --out /tmp/results.json
python scripts/audit_generalization.py --source-root . --revision HEAD --out /tmp/generalization.json
```

파일: `claims-as-asserted.md`(입력), `self-audit.json`(도구 출력), `results.json`(독립 검증 원본), `gate-runs.json`(게이트 실행 요약), `generalization.json`(합성 평가 원본), `reproduce.py`(재현 코드).
