#!/usr/bin/env bash
# Drift Gate — Claude Code 플러그인 설치 스크립트
# 프로젝트 루트에서 실행: curl -fsSL .../install.sh | bash
set -euo pipefail

BASE="https://raw.githubusercontent.com/cres17/pr-convention-checker/main"
CMDS=".claude/commands"
SKILLS=".claude/skills"

echo "[drift-gate] 설치 중..."

mkdir -p "$CMDS" "$SKILLS"

curl -fsSL "${BASE}/commands/drift-gate.md" -o "${CMDS}/drift-gate.md"
curl -fsSL "${BASE}/skills/drift-gate.md"   -o "${SKILLS}/drift-gate.md"

echo "[drift-gate] 설치 완료."
echo "  커맨드: ${CMDS}/drift-gate.md"
echo "  스킬:   ${SKILLS}/drift-gate.md"
echo ""
echo "Claude Code에서 /drift-gate:review 로 실행하세요."
