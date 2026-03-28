"""
Markdown 리포트 생성기.
I/O 없음 — 문자열 반환.
"""
from drift_gate.core.models.result import EvaluationResult, Violation

SEVERITY_ICON = {
    "BLOCKER": "🚫",
    "MAJOR":   "⚠️",
    "MINOR":   "💬",
    "NIT":     "🔧",
}

RESULT_ICON = {
    "fail": "FAIL ❌",
    "warn": "WARN ⚠️",
    "pass": "PASS ✅",
}


class MarkdownReporter:
    MARKER = "<!-- drift-gate-v1 -->"

    def render(self, result: EvaluationResult, *, marker: bool = True) -> str:
        lines = []
        if marker:
            lines.append(self.MARKER)

        lines.append("## 🔍 Drift Gate 분석 결과")
        lines.append("")

        if result.no_policy:
            lines += self._no_policy_section()
            return "\n".join(lines)

        if result.skip:
            lines.append(f"✅ **드리프트 평가 생략** — `{result.skip_reason}` PR입니다.")
            return "\n".join(lines)

        change_types_str = ", ".join(result.change_types) if result.change_types else "-"
        lines.append(
            f"> 변경 파일 유형: `{change_types_str}` | "
            f"위반: BLOCKER {result.blocker_count} · MAJOR {result.major_count} · "
            f"MINOR {result.minor_count} · NIT {result.nit_count}"
        )
        lines.append("")

        if not result.violations:
            lines.append("✅ **계약 문서 동기화 완료** — 모든 정책 규칙 통과.")
        else:
            if result.result == "fail":
                lines.append(
                    f"🚫 **머지 전 수정 필요** — "
                    f"BLOCKER {result.blocker_count}개 · MAJOR {result.major_count}개"
                )
            else:
                lines.append(
                    f"⚠️ **문서 동기화 권장** — "
                    f"MAJOR {result.major_count}개 · MINOR {result.minor_count}개"
                )
            lines.append("")

            for severity in ("BLOCKER", "MAJOR", "MINOR", "NIT"):
                sevs = [v for v in result.violations if v.severity == severity]
                if not sevs:
                    continue
                icon = SEVERITY_ICON[severity]
                lines.append(f"### {icon} {severity} ({len(sevs)})")
                lines.append("")
                for v in sevs:
                    lines += self._violation_section(v)

        lines += self._summary_section(result)
        return "\n".join(lines)

    def _violation_section(self, v: Violation) -> list:
        confidence_tag = "" if v.confidence == "high" else " `[추정]`"
        lines = [
            f"**[`{v.rule_id}`]**{confidence_tag} {v.message}",
            "",
            f"변경 유형: `{v.change_type}`",
            "",
            "**트리거 파일:**",
        ]
        for f in v.trigger_files:
            lines.append(f"- `{f.path}` ({f.status})")
        lines.append("")
        lines.append("**불충족 묶음:**")
        for g in v.unsatisfied_groups:
            req = "`, `".join(g.required)
            lines.append(f"- **{g.name}** — `{req}` ({g.type}) 없음")
        lines.append("")
        if v.checklist:
            lines.append("**체크리스트:**")
            for item in v.checklist:
                lines.append(f"- [ ] {item}")
            lines.append("")
        lines.append(
            f"> 무시하려면: `drift-ignore: {v.rule_id}` + "
            f"`reason: <이유>` 를 PR description에 추가"
        )
        lines += ["", "---", ""]
        return lines

    def _summary_section(self, result: EvaluationResult) -> list:
        lines = [
            "<details>",
            "<summary>📊 요약 · ℹ️ 이 체크에 대해</summary>",
            "",
            "| 심각도 | 수 |",
            "|--------|-----|",
            f"| 🚫 BLOCKER | {result.blocker_count} |",
            f"| ⚠️ MAJOR | {result.major_count} |",
            f"| 💬 MINOR | {result.minor_count} |",
            f"| 🔧 NIT | {result.nit_count} |",
            "",
            f"**CI 판정:** {RESULT_ICON.get(result.result, result.result)}",
        ]

        if result.skipped_rules:
            skipped = ", ".join(
                f"{s.rule_id} ({s.severity})" for s in result.skipped_rules
            )
            lines += ["", f"**적용된 ignore ({len(result.skipped_rules)}):** {skipped}"]

        if result.rejected_ignores:
            rejected = ", ".join(
                f"{r.rule_id} ({r.severity})" for r in result.rejected_ignores
            )
            lines += [
                "",
                f"**거부된 ignore — reason 없음 ({len(result.rejected_ignores)}):** {rejected}",
                "",
                "> ⚠️ BLOCKER/MAJOR drift-ignore는 `reason:`이 필수입니다.",
            ]

        lines += [
            "",
            "BLOCKER/MAJOR 규칙을 무시하려면 PR description에 추가:",
            "```",
            "drift-ignore: <rule-id>",
            "reason: <이유>   ← BLOCKER/MAJOR 필수",
            "```",
            "",
            "</details>",
        ]
        return lines

    def _no_policy_section(self) -> list:
        return [
            "",
            "⚠️ **`.drift-gate.yml`이 없습니다.**",
            "",
            "레포 루트에 정책 파일을 추가하면 팀 규칙 기반 drift 검사를 시작할 수 있습니다.",
            "",
            "```yaml",
            "rules:",
            "  - id: api-contract-sync",
            "    when:",
            '      any_changed: ["src/routes/**", "openapi/**"]',
            "    require:",
            "      groups:",
            '        - name: "API 계약 문서"',
            '          any_changed: ["docs/spec.md", "docs/api/**"]',
            '        - name: "릴리즈 공지"',
            '          all_changed: ["CHANGELOG.md"]',
            "    severity: blocker",
            '    message: "API surface changed without synced contract/docs"',
            "gate:",
            "  fail_on_blocker: true",
            "  fail_on_major_count: 2",
            "```",
        ]
