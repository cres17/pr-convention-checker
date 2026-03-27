#!/usr/bin/env bash
# Spec/Contract Drift Gate — GitHub Actions 진입점
#
# 환경변수:
#   ANTHROPIC_API_KEY  — Claude API 키 (필수)
#   GITHUB_TOKEN       — PR 코멘트 게시용 토큰 (필수)
#   PR_NUMBER          — PR 번호
#   REPO               — owner/repo 형식
#   BASE_SHA           — base commit SHA (폴백용)
#   HEAD_SHA           — head commit SHA (폴백용)
#   MODEL              — Claude 모델 ID (기본: claude-opus-4-6)
#   POLICY_FILE        — 정책 파일 경로 (기본: .drift-gate.yml)
set -euo pipefail

REPORT_MD="${RUNNER_TEMP:-/tmp}/drift_gate_report.md"
REPORT_JSON="${RUNNER_TEMP:-/tmp}/drift_gate_report.json"
MARKER="<!-- drift-gate-v1 -->"
MODEL="${MODEL:-claude-opus-4-6}"
POLICY_FILE="${POLICY_FILE:-.drift-gate.yml}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ─── 유틸 함수 ───────────────────────────────────────────────────────────────

log()  { echo "[drift-gate] $*" >&2; }
fail() { log "ERROR: $*"; exit 1; }
require_cmd() { command -v "$1" >/dev/null 2>&1 || fail "'$1' 명령어가 필요합니다."; }

output() {
  local key="$1" val="$2"
  echo "${key}=${val}" >> "${GITHUB_OUTPUT:-/dev/null}"
}

# ─── 사전 요건 확인 ───────────────────────────────────────────────────────────

require_cmd curl
require_cmd jq
require_cmd python3
[ -n "${ANTHROPIC_API_KEY:-}" ] || fail "ANTHROPIC_API_KEY가 설정되지 않았습니다."

# pyyaml 확인 (없으면 설치)
python3 -c "import yaml" 2>/dev/null || {
  log "pyyaml 설치 중..."
  pip3 install --quiet pyyaml || fail "pyyaml 설치 실패"
}

# ─── Step 1: 변경 파일 수집 ──────────────────────────────────────────────────

log "변경 파일 수집 중..."

PR_BODY=""
CHANGED_FILES_JSON="[]"

if [ -n "${PR_NUMBER:-}" ] && [ -n "${REPO:-}" ] && [ -n "${GITHUB_TOKEN:-}" ]; then
  # GitHub API로 변경 파일 목록 수집 (status, patch 포함)
  API_FILES=$(curl -sf \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github.v3+json" \
    "https://api.github.com/repos/${REPO}/pulls/${PR_NUMBER}/files?per_page=100" \
    2>/dev/null) || API_FILES="[]"

  CHANGED_FILES_JSON=$(echo "$API_FILES" | jq '[.[] | {
    path: .filename,
    status: .status,
    previous_path: (.previous_filename // null),
    patch: (.patch // "")
  }]')

  # PR body — drift-ignore 파싱용
  PR_BODY=$(curl -sf \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github.v3+json" \
    "https://api.github.com/repos/${REPO}/pulls/${PR_NUMBER}" \
    2>/dev/null | jq -r '.body // ""') || PR_BODY=""
else
  log "GitHub API 환경변수 미설정. git 폴백 사용..."
  BASE="${BASE_SHA:-HEAD~1}"

  GIT_STATUS=$(git diff --name-status "${BASE}...HEAD" 2>/dev/null \
    || git diff --name-status HEAD~1 2>/dev/null \
    || true)

  CHANGED_FILES_JSON=$(python3 - <<'PYEOF'
import sys, json

lines = """${GIT_STATUS}""".strip().splitlines()
files = []
STATUS_MAP = {"A": "added", "M": "modified", "D": "deleted"}

for line in lines:
    if not line.strip():
        continue
    parts = line.split("\t")
    if parts[0].startswith("R"):
        files.append({"path": parts[2], "status": "renamed",
                      "previous_path": parts[1], "patch": ""})
    elif len(parts) >= 2:
        files.append({"path": parts[1],
                      "status": STATUS_MAP.get(parts[0], "modified"),
                      "previous_path": None, "patch": ""})

print(json.dumps(files))
PYEOF
  )
fi

FILE_COUNT=$(echo "$CHANGED_FILES_JSON" | jq 'length')
log "변경 파일: ${FILE_COUNT}개"

if [ "$FILE_COUNT" -eq 0 ]; then
  log "변경 파일이 없습니다."
  output result skip
  output blocker_count 0
  output major_count 0
  output violation_count 0
  exit 0
fi

# ─── Step 2: drift-ignore 파싱 ───────────────────────────────────────────────

log "PR body에서 drift-ignore 파싱 중..."

IGNORED_RULES_JSON=$(python3 - <<PYEOF
import sys, json, re
body = ${PR_BODY@Q}
ignored = [m.group(1) for m in re.finditer(r'drift-ignore:\s*(\S+)', body)]
print(json.dumps(ignored))
PYEOF
)

IGNORED_COUNT=$(echo "$IGNORED_RULES_JSON" | jq 'length')
if [ "$IGNORED_COUNT" -gt 0 ]; then
  IGNORED_LIST=$(echo "$IGNORED_RULES_JSON" | jq -r '.[]' | tr '\n' ' ')
  log "drift-ignore 규칙: ${IGNORED_LIST}"

  # reason 없는 drift-ignore 경고
  python3 - <<PYEOF
import re, sys
body = ${PR_BODY@Q}
for m in re.finditer(r'drift-ignore:\s*(\S+)', body):
    rule_id = m.group(1)
    after = body[m.end():]
    if not re.search(r'reason\s*:', after.split('\n')[0] + '\n' + (after.split('\n')[1] if len(after.split('\n')) > 1 else '')):
        print(f"[drift-gate] WARNING: drift-ignore '{rule_id}' — reason 없음. 감사 추적을 위해 reason 추가를 권장합니다.", file=sys.stderr)
PYEOF

fi

# ─── Step 3: 정책 평가 ───────────────────────────────────────────────────────

log "정책 평가 중 (${POLICY_FILE})..."

EVAL_RESULT=$(python3 "${SCRIPT_DIR}/evaluate.py" \
  "$POLICY_FILE" \
  "$CHANGED_FILES_JSON" \
  "$IGNORED_RULES_JSON" 2>&1) || {
  EXIT_CODE=$?
  if [ $EXIT_CODE -eq 2 ]; then
    fail "$(echo "$EVAL_RESULT" | grep 'ERROR:' | head -1)"
  fi
  fail "정책 평가 실패: ${EVAL_RESULT}"
}

# 정책 파일 없음
if echo "$EVAL_RESULT" | jq -e '.no_policy' >/dev/null 2>&1; then
  log "WARNING: ${POLICY_FILE}이 없습니다."
  cat > "$REPORT_MD" <<EOF
${MARKER}
## ⚙️ Drift Gate

⚠️ **\`.drift-gate.yml\`이 없습니다.**

레포 루트에 정책 파일을 추가하면 팀 규칙 기반 drift 검사를 시작할 수 있습니다.

\`\`\`yaml
rules:
  - id: api-contract-sync
    when:
      any_changed:
        - "src/routes/**"
        - "openapi/**"
    require:
      groups:
        - name: "API 계약 문서"
          any_changed:
            - "docs/spec.md"
            - "docs/api/**"
        - name: "릴리즈 공지"
          all_changed:
            - "CHANGELOG.md"
    severity: blocker
    message: "API surface changed without synced contract/docs"
gate:
  fail_on_blocker: true
  fail_on_major_count: 2
\`\`\`
EOF
  output result skip
  output blocker_count 0
  output major_count 0
  output violation_count 0
  exit 0
fi

# docs-only / test-only 스킵
if echo "$EVAL_RESULT" | jq -e '.skip' >/dev/null 2>&1; then
  SKIP_REASON=$(echo "$EVAL_RESULT" | jq -r '.reason')
  log "드리프트 평가 건너뜀: ${SKIP_REASON}"
  cat > "$REPORT_MD" <<EOF
${MARKER}
## 🔍 Drift Gate 분석 결과

✅ **드리프트 평가 건너뜀** — \`${SKIP_REASON}\` PR입니다.
계약 문서 동기화 점검이 필요하지 않습니다.
EOF
  output result pass
  output blocker_count 0
  output major_count 0
  output violation_count 0
  exit 0
fi

CHANGE_TYPES=$(echo "$EVAL_RESULT" | jq -r '.change_types | join(", ")')
VIOLATIONS=$(echo "$EVAL_RESULT" | jq '.violations')
VIOLATION_COUNT=$(echo "$VIOLATIONS" | jq 'length')
GATE=$(echo "$EVAL_RESULT" | jq '.gate')

BLOCKER_COUNT=$(echo "$VIOLATIONS" | jq '[.[] | select(.severity == "BLOCKER")] | length')
MAJOR_COUNT=$(echo "$VIOLATIONS"   | jq '[.[] | select(.severity == "MAJOR")]   | length')
MINOR_COUNT=$(echo "$VIOLATIONS"   | jq '[.[] | select(.severity == "MINOR")]   | length')
NIT_COUNT=$(echo "$VIOLATIONS"     | jq '[.[] | select(.severity == "NIT")]     | length')

log "변경 유형: ${CHANGE_TYPES}"
log "위반: BLOCKER=${BLOCKER_COUNT} MAJOR=${MAJOR_COUNT} MINOR=${MINOR_COUNT} NIT=${NIT_COUNT}"

# ─── Step 4: Claude API — 근거 및 체크리스트 생성 ────────────────────────────

CLAUDE_ENRICHMENT=""

if [ "$VIOLATION_COUNT" -gt 0 ]; then
  log "Claude API 호출 중 (모델: ${MODEL})..."

  VIOLATIONS_SUMMARY=$(echo "$VIOLATIONS" | jq -r '.[] |
    "[" + .severity + "] " + .rule_id + "\n" +
    "  메시지: " + .message + "\n" +
    "  트리거 파일: " + ([.trigger_files[].path] | join(", ")) + "\n" +
    "  불충족 묶음: " + (
      [.unsatisfied_groups[] |
        .name + " — " + .type + "(" + (.required | join(", ")) + ")"
      ] | join("; ")
    ) + "\n"
  ')

  PROMPT="당신은 팀 계약 문서(spec/runbook/CHANGELOG 등)와 코드 변경의 정합성을 점검하는 분석가입니다.

아래 \"정책 위반 목록\"을 검토하고, 각 항목에 대해 다음 두 가지를 작성하세요:
1. 왜 필요한가: 해당 문서나 산출물이 이 변경에서 왜 중요한지 1-2문장으로 설명
2. 체크리스트: 개발자가 수행해야 할 구체적 액션 3-5개 (마크다운 체크박스 형식)

각 항목을 아래 형식으로 출력하세요:

### [SEVERITY] rule-id
왜 필요한가: <설명>

체크리스트:
- [ ] <액션 1>
- [ ] <액션 2>
- [ ] <액션 3>

---

## 정책 위반 목록

${VIOLATIONS_SUMMARY}"

  API_RESPONSE=$(curl -sf \
    -X POST \
    -H "Content-Type: application/json" \
    -H "x-api-key: ${ANTHROPIC_API_KEY}" \
    -H "anthropic-version: 2023-06-01" \
    "https://api.anthropic.com/v1/messages" \
    -d "$(jq -n \
      --arg model "$MODEL" \
      --arg prompt "$PROMPT" \
      '{model: $model, max_tokens: 2048, messages: [{role: "user", content: $prompt}]}'
    )") || { log "WARNING: Claude API 호출 실패. 기본 메시지로 대체."; API_RESPONSE=""; }

  if [ -n "$API_RESPONSE" ]; then
    CLAUDE_ENRICHMENT=$(echo "$API_RESPONSE" | jq -r '.content[0].text // ""')
  fi
fi

# ─── Step 5: Markdown 리포트 생성 ────────────────────────────────────────────

log "리포트 생성 중..."

FAIL_ON_BLOCKER=$(echo "$GATE" | jq -r '.fail_on_blocker // true')
FAIL_ON_MAJOR=$(echo "$GATE" | jq -r '.fail_on_major_count // 2')

if [ "$BLOCKER_COUNT" -gt 0 ] && [ "$FAIL_ON_BLOCKER" = "true" ]; then
  RESULT="fail"
elif [ "$MAJOR_COUNT" -ge "$FAIL_ON_MAJOR" ]; then
  RESULT="fail"
elif [ "$MAJOR_COUNT" -gt 0 ] || [ "$MINOR_COUNT" -gt 0 ]; then
  RESULT="warn"
else
  RESULT="pass"
fi

{
  echo "${MARKER}"
  echo "## 🔍 Drift Gate 분석 결과"
  echo ""
  echo "> 정책: \`${POLICY_FILE}\` | 변경 파일: ${FILE_COUNT}개 | 유형: ${CHANGE_TYPES}"
  echo ""

  if [ "$VIOLATION_COUNT" -eq 0 ]; then
    echo "✅ **계약 문서 동기화 완료** — 모든 정책 규칙을 통과합니다."
  else
    if [ "$RESULT" = "fail" ]; then
      echo "🚫 **머지 전 수정 필요** — BLOCKER ${BLOCKER_COUNT}개 · MAJOR ${MAJOR_COUNT}개"
    else
      echo "⚠️ **문서 동기화 권장** — MAJOR ${MAJOR_COUNT}개 · MINOR ${MINOR_COUNT}개"
    fi
    echo ""

    for severity in BLOCKER MAJOR MINOR NIT; do
      SEV_VIOLATIONS=$(echo "$VIOLATIONS" | jq --arg s "$severity" '[.[] | select(.severity == $s)]')
      SEV_COUNT=$(echo "$SEV_VIOLATIONS" | jq 'length')
      [ "$SEV_COUNT" -eq 0 ] && continue

      case "$severity" in
        BLOCKER) echo "### 🚫 BLOCKER (${SEV_COUNT})" ;;
        MAJOR)   echo "### ⚠️ MAJOR (${SEV_COUNT})" ;;
        MINOR)   echo "### 💬 MINOR (${SEV_COUNT})" ;;
        NIT)     echo "### 🔧 NIT (${SEV_COUNT})" ;;
      esac
      echo ""

      while IFS= read -r violation; do
        RULE_ID=$(echo "$violation" | jq -r '.rule_id')
        MESSAGE=$(echo "$violation" | jq -r '.message')

        echo "**[\`${RULE_ID}\`]** ${MESSAGE}"
        echo ""

        # 트리거 파일
        echo "**트리거 파일:**"
        echo "$violation" | jq -r '.trigger_files[] | "- `" + .path + "` (" + .status + ")"'
        echo ""

        # 불충족 묶음
        echo "**불충족 묶음:**"
        echo "$violation" | jq -r '
          .unsatisfied_groups[] |
          "- **" + .name + "** (`" + (.required | join("`, `")) + "` " + .type + " — 없음)"
        '
        echo ""

        # Claude 근거 + 체크리스트 (rule_id 섹션 추출)
        if [ -n "$CLAUDE_ENRICHMENT" ]; then
          ENRICHMENT=$(python3 - <<PYEOF
import re, sys
content = """${CLAUDE_ENRICHMENT}"""
rule_id = "${RULE_ID}"
pattern = r'###[^\n]*' + re.escape(rule_id) + r'[^\n]*\n(.*?)(?=###|\Z)'
m = re.search(pattern, content, re.DOTALL)
if m:
    print(m.group(1).strip())
PYEOF
          )
          if [ -n "$ENRICHMENT" ]; then
            echo "$ENRICHMENT"
            echo ""
          fi
        fi

        echo "> 무시하려면 PR description에 추가: \`drift-ignore: ${RULE_ID}\`"
        echo ""
        echo "---"
        echo ""
      done < <(echo "$SEV_VIOLATIONS" | jq -c '.[]')
    done
  fi

  # 요약 및 안내
  echo "<details>"
  echo "<summary>📊 요약 · ℹ️ 이 체크에 대해</summary>"
  echo ""
  echo "| 심각도 | 수 |"
  echo "|--------|-----|"
  echo "| 🚫 BLOCKER | ${BLOCKER_COUNT} |"
  echo "| ⚠️ MAJOR | ${MAJOR_COUNT} |"
  echo "| 💬 MINOR | ${MINOR_COUNT} |"
  echo "| 🔧 NIT | ${NIT_COUNT} |"
  echo ""
  echo "**CI 판정:** $([ "$RESULT" = "fail" ] && echo "FAIL ❌" || ([ "$RESULT" = "warn" ] && echo "WARN ⚠️" || echo "PASS ✅"))"
  if [ "$IGNORED_COUNT" -gt 0 ]; then
    echo ""
    echo "**건너뛴 규칙:** $(echo "$IGNORED_RULES_JSON" | jq -r '.[]' | tr '\n' ' ')"
  fi
  echo ""
  echo "이 코멘트는 \`.drift-gate.yml\` 기반으로 팀 계약 문서와 코드 변경의 정합성을 점검합니다."
  echo "규칙을 무시하려면 PR description에 아래를 추가하세요:"
  echo ""
  echo "\`\`\`"
  echo "drift-ignore: <rule-id>"
  echo "reason: <이유>"
  echo "\`\`\`"
  echo ""
  echo "</details>"
} > "$REPORT_MD"

# ─── Step 6: JSON 리포트 생성 ────────────────────────────────────────────────

jq -n \
  --argjson violations "$VIOLATIONS" \
  --argjson blocker "$BLOCKER_COUNT" \
  --argjson major "$MAJOR_COUNT" \
  --argjson minor "$MINOR_COUNT" \
  --argjson nit "$NIT_COUNT" \
  --argjson change_types "$(echo "$EVAL_RESULT" | jq '.change_types')" \
  --argjson gate "$GATE" \
  --argjson ignored "$IGNORED_RULES_JSON" \
  --arg result "$RESULT" \
  --arg policy "$POLICY_FILE" \
  '{
    summary: {
      blocker: $blocker, major: $major, minor: $minor, nit: $nit,
      passed: ($result == "pass")
    },
    result: $result,
    change_types: $change_types,
    violations: $violations,
    ignored_rules: $ignored,
    gate: $gate,
    policy_file: $policy
  }' > "$REPORT_JSON"

log "리포트 저장: ${REPORT_MD} | ${REPORT_JSON}"

# ─── Step 7: 출력 ────────────────────────────────────────────────────────────

output result         "$RESULT"
output blocker_count  "$BLOCKER_COUNT"
output major_count    "$MAJOR_COUNT"
output violation_count "$VIOLATION_COUNT"

echo ""
echo "========================================"
echo " Drift Gate 분석 결과"
echo "========================================"
cat "$REPORT_MD"
echo ""
