#!/usr/bin/env bash
# PR Convention Checker — GitHub Actions 진입점
# 환경변수: ANTHROPIC_API_KEY, GITHUB_TOKEN, PR_NUMBER, REPO,
#            BASE_SHA, HEAD_SHA, CONVENTION_FILES, MODEL
set -euo pipefail

REPORT_FILE="${RUNNER_TEMP:-/tmp}/convention_report.md"
MARKER="<!-- convention-checker-v1 -->"
MODEL="${MODEL:-claude-opus-4-6}"

# ─── 유틸 함수 ───────────────────────────────────────────────────────────────

log() { echo "[convention-checker] $*" >&2; }
fail() { log "ERROR: $*"; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "'$1' 명령어가 필요합니다."
}

# ─── 사전 요건 확인 ───────────────────────────────────────────────────────────

require_cmd curl
require_cmd jq
[ -n "${ANTHROPIC_API_KEY:-}" ] || fail "ANTHROPIC_API_KEY가 설정되지 않았습니다."

# ─── Step 1: 설정 파일 로드 ───────────────────────────────────────────────────

log "설정 파일 로드 중..."

CONFIG_FILE=".convention-checker.yml"
EXCLUDE_PATTERNS=('*.test.ts' '*.test.js' '*.spec.ts' '*.spec.js' '*.snap' '.github/*' 'dist/*' 'build/*' 'node_modules/*' '*.lock' '*-lock.json')

# CONVENTION_FILES 환경변수 > 설정 파일 > 기본값
if [ -n "${CONVENTION_FILES:-}" ]; then
  IFS=',' read -ra CONV_FILE_LIST <<< "$CONVENTION_FILES"
else
  CONV_FILE_LIST=("CLAUDE.md" "SKILLS.md" ".claude/instructions.md" "docs/conventions.md")
fi

# ─── Step 2: 컨벤션 파일 수집 ────────────────────────────────────────────────

log "컨벤션 파일 수집 중..."

CONVENTION_CONTENT=""
LOADED_FILES=()

for f in "${CONV_FILE_LIST[@]}"; do
  f=$(echo "$f" | xargs)  # trim
  if [ -f "$f" ]; then
    CONVENTION_CONTENT+=$'\n\n'"<!-- source: ${f} -->"$'\n'
    CONVENTION_CONTENT+=$(cat "$f")
    LOADED_FILES+=("$f")
    log "  로드: $f"
  else
    log "  건너뜀 (없음): $f"
  fi
done

if [ -z "$CONVENTION_CONTENT" ]; then
  log "WARNING: 컨벤션 파일을 하나도 찾지 못했습니다."
  cat > "$REPORT_FILE" <<EOF
${MARKER}
## 🔍 PR 컨벤션 체크 결과

⚠️ **컨벤션 파일을 찾을 수 없습니다.**

레포 루트에 \`CLAUDE.md\` 또는 \`SKILLS.md\`를 작성하거나,
\`.convention-checker.yml\`의 \`convention_files\` 경로를 확인하세요.
EOF
  echo "result=skip" >> "${GITHUB_OUTPUT:-/dev/null}"
  echo "blocker_count=0" >> "${GITHUB_OUTPUT:-/dev/null}"
  exit 0
fi

# 컨벤션 텍스트 크기 제한 (약 16,000자)
MAX_CONV_CHARS=16000
if [ ${#CONVENTION_CONTENT} -gt $MAX_CONV_CHARS ]; then
  log "컨벤션 파일이 큽니다. 압축 중 (${#CONVENTION_CONTENT}자 → ${MAX_CONV_CHARS}자)..."
  CONVENTION_CONTENT="${CONVENTION_CONTENT:0:$MAX_CONV_CHARS}"$'\n\n[... 이후 내용 생략됨 ...]'
fi

# ─── Step 3: PR Diff 수집 ─────────────────────────────────────────────────────

log "PR diff 수집 중..."

if [ -n "${PR_NUMBER:-}" ] && [ -n "${REPO:-}" ] && [ -n "${GITHUB_TOKEN:-}" ]; then
  # GitHub API로 diff 가져오기
  RAW_DIFF=$(curl -sf \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github.v3.diff" \
    "https://api.github.com/repos/${REPO}/pulls/${PR_NUMBER}/files?per_page=100" \
    2>/dev/null || true)

  # files API로 파일 목록 가져오기 (JSON)
  PR_FILES_JSON=$(curl -sf \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github.v3+json" \
    "https://api.github.com/repos/${REPO}/pulls/${PR_NUMBER}/files?per_page=100" \
    2>/dev/null || echo "[]")

  # patch 필드에서 diff 재구성
  RAW_DIFF=$(echo "$PR_FILES_JSON" | jq -r '
    .[] |
    "diff --git a/\(.filename) b/\(.filename)\n" +
    (if .patch then .patch else "(binary or no changes)" end)
  ')

  CHANGED_FILES=$(echo "$PR_FILES_JSON" | jq -r '.[].filename')
  TOTAL_FILES=$(echo "$PR_FILES_JSON" | jq 'length')
elif [ -n "${BASE_SHA:-}" ] && [ -n "${HEAD_SHA:-}" ]; then
  # git diff 폴백
  RAW_DIFF=$(git diff "${BASE_SHA}...${HEAD_SHA}" 2>/dev/null || git diff HEAD~1 2>/dev/null || true)
  CHANGED_FILES=$(git diff --name-only "${BASE_SHA}...${HEAD_SHA}" 2>/dev/null || true)
  TOTAL_FILES=$(echo "$CHANGED_FILES" | grep -c . || true)
else
  RAW_DIFF=$(git diff HEAD~1 2>/dev/null || true)
  CHANGED_FILES=$(git diff --name-only HEAD~1 2>/dev/null || true)
  TOTAL_FILES=$(echo "$CHANGED_FILES" | grep -c . || true)
fi

if [ -z "$RAW_DIFF" ]; then
  log "분석할 diff가 없습니다."
  echo "result=skip" >> "${GITHUB_OUTPUT:-/dev/null}"
  echo "blocker_count=0" >> "${GITHUB_OUTPUT:-/dev/null}"
  exit 0
fi

# ─── Step 4: Diff 전처리 ─────────────────────────────────────────────────────

log "Diff 전처리 중..."

# 제외할 파일 패턴 필터링
FILTERED_DIFF=""
EXCLUDED_COUNT=0
CURRENT_FILE=""
SKIP_CURRENT=false
INCLUDED_COUNT=0

while IFS= read -r line; do
  # 파일 헤더 감지
  if [[ "$line" =~ ^diff\ --git\ a/(.+)\ b/(.+)$ ]]; then
    CURRENT_FILE="${BASH_REMATCH[2]}"
    SKIP_CURRENT=false

    # 제외 패턴 확인
    for pat in "${EXCLUDE_PATTERNS[@]}"; do
      if [[ "$CURRENT_FILE" == $pat ]]; then
        SKIP_CURRENT=true
        ((EXCLUDED_COUNT++)) || true
        break
      fi
    done

    # 민감 파일 제외
    if [[ "$CURRENT_FILE" == *.env* ]] || [[ "$CURRENT_FILE" == *secret* ]] || [[ "$CURRENT_FILE" == *credential* ]]; then
      SKIP_CURRENT=true
      ((EXCLUDED_COUNT++)) || true
    fi

    if [ "$SKIP_CURRENT" = false ]; then
      FILTERED_DIFF+="${line}"$'\n'
      ((INCLUDED_COUNT++)) || true
    fi
    continue
  fi

  if [ "$SKIP_CURRENT" = false ]; then
    # 민감 정보 마스킹
    if echo "$line" | grep -qiE '(password|secret|api_key|apikey|token)\s*[=:]\s*[^\s]'; then
      line=$(echo "$line" | sed -E 's/(password|secret|api_key|apikey|token)(\s*[=:]\s*).*/\1\2[REDACTED]/gi')
    fi
    FILTERED_DIFF+="${line}"$'\n'
  fi
done <<< "$RAW_DIFF"

# Diff 크기 제한 (약 20,000자)
MAX_DIFF_CHARS=20000
if [ ${#FILTERED_DIFF} -gt $MAX_DIFF_CHARS ]; then
  log "Diff가 큽니다. 잘라냄 (${#FILTERED_DIFF}자 → ${MAX_DIFF_CHARS}자)..."
  FILTERED_DIFF="${FILTERED_DIFF:0:$MAX_DIFF_CHARS}"$'\n\n[... diff 이후 생략됨 ...]'
fi

if [ -z "$FILTERED_DIFF" ]; then
  log "필터링 후 분석할 내용이 없습니다."
  echo "result=skip" >> "${GITHUB_OUTPUT:-/dev/null}"
  echo "blocker_count=0" >> "${GITHUB_OUTPUT:-/dev/null}"
  exit 0
fi

# convention-ignore 블록 처리
PROCESSED_DIFF=""
IN_IGNORE_BLOCK=false
IGNORED_LINES=0

while IFS= read -r line; do
  if echo "$line" | grep -q 'convention-ignore-start'; then
    IN_IGNORE_BLOCK=true
    continue
  fi
  if echo "$line" | grep -q 'convention-ignore-end'; then
    IN_IGNORE_BLOCK=false
    continue
  fi
  if [ "$IN_IGNORE_BLOCK" = true ]; then
    ((IGNORED_LINES++)) || true
    continue
  fi
  if echo "$line" | grep -q 'convention-ignore'; then
    ((IGNORED_LINES++)) || true
    continue
  fi
  PROCESSED_DIFF+="${line}"$'\n'
done <<< "$FILTERED_DIFF"

log "전처리 완료: 포함 ${INCLUDED_COUNT}개, 제외 ${EXCLUDED_COUNT}개, convention-ignore ${IGNORED_LINES}줄"

# ─── Step 5: Claude API 호출 ─────────────────────────────────────────────────

log "Claude API 호출 중 (모델: ${MODEL})..."

LOADED_FILES_STR=$(IFS=', '; echo "${LOADED_FILES[*]}")

PROMPT=$(cat <<PROMPT
당신은 팀 컨벤션 준수 여부를 체크하는 PR 리뷰어입니다.

아래 "컨벤션 문서"와 "PR diff"를 대조하여, diff에서 추가(+)된 코드가
컨벤션 문서에 명시된 규칙을 위반하는지 분석하세요.

## 분석 원칙
- 컨벤션 문서에 명시적으로 기술된 규칙만 체크합니다.
- 범용 코드 품질 조언은 하지 않습니다.
- 삭제(-) 줄은 분석하지 않습니다.
- 규칙 적용 범위가 불명확하면 [추정] 라벨을 붙이고 신뢰도를 low로 표시합니다.

## 심각도 기준
- BLOCKER: "must", "반드시", "절대", "금지", "never", "always" 등 강제 규칙 위반
- MAJOR: "should", "권장", "필요", "required" 등 권고 규칙 위반
- MINOR: 명확한 위반이지만 경미, 또는 개선 여지
- NIT: "prefer", "가급적" 등 선호 표현의 미준수

## 출력 형식 (GitHub Markdown)

결과를 아래 형식으로 출력하세요. 위반이 없으면 "위반 없음" 섹션만 출력합니다.

${MARKER}
## 🔍 PR 컨벤션 체크 결과

> 분석 기준: \`${LOADED_FILES_STR}\` | 분석한 파일: ${INCLUDED_COUNT}개

[위반이 있으면 심각도별 섹션과 항목을 출력]
[위반이 없으면: ✅ **컨벤션 이슈 없음** — 모든 규칙을 준수합니다.]

---
📊 요약: BLOCKER N개 · MAJOR N개 · MINOR N개 · NIT N개

<details>
<summary>ℹ️ 이 체크에 대해</summary>
이 코멘트는 팀 컨벤션 문서를 기준으로 자동 생성됩니다.
특정 지적이 잘못되었다면 해당 줄에 \`// convention-ignore\` 주석을 추가하세요.
</details>

---

## 컨벤션 문서

${CONVENTION_CONTENT}

---

## PR Diff

${PROCESSED_DIFF}
PROMPT
)

# Claude API 호출
API_RESPONSE=$(curl -sf \
  -X POST \
  -H "Content-Type: application/json" \
  -H "x-api-key: ${ANTHROPIC_API_KEY}" \
  -H "anthropic-version: 2023-06-01" \
  "https://api.anthropic.com/v1/messages" \
  -d "$(jq -n \
    --arg model "$MODEL" \
    --arg prompt "$PROMPT" \
    '{
      model: $model,
      max_tokens: 4096,
      messages: [{ role: "user", content: $prompt }]
    }'
  )"
) || fail "Claude API 호출 실패"

# 응답 파싱
REPORT=$(echo "$API_RESPONSE" | jq -r '.content[0].text // empty')

if [ -z "$REPORT" ]; then
  fail "Claude API 응답을 파싱할 수 없습니다: $(echo "$API_RESPONSE" | head -c 500)"
fi

# ─── Step 6: 결과 저장 및 출력 ───────────────────────────────────────────────

echo "$REPORT" > "$REPORT_FILE"
log "리포트 저장: $REPORT_FILE"

# BLOCKER 수 계산
BLOCKER_COUNT=$(echo "$REPORT" | grep -c '\[BLOCKER\]' || true)

if [ "$BLOCKER_COUNT" -gt 0 ]; then
  RESULT="fail"
else
  MAJOR_COUNT=$(echo "$REPORT" | grep -c '\[MAJOR\]' || true)
  if [ "$MAJOR_COUNT" -gt 0 ]; then
    RESULT="warn"
  else
    RESULT="pass"
  fi
fi

log "체크 완료: ${RESULT} (BLOCKER: ${BLOCKER_COUNT})"

# GitHub Actions 출력
{
  echo "result=${RESULT}"
  echo "blocker_count=${BLOCKER_COUNT}"
} >> "${GITHUB_OUTPUT:-/dev/null}"

# 터미널에도 출력
echo ""
echo "========================================"
echo "PR Convention Checker 결과"
echo "========================================"
cat "$REPORT_FILE"
echo ""
