"""
Markdown report renderer.

The report is optimized for PR comments: short summary first, then concrete
fix guidance for every violation.
"""
import re
from itertools import islice

from drift_gate.core.models.result import EvaluationResult, Violation
from drift_gate.reporters.markdown_text import block, code, fenced, text

SEVERITY_ICON = {
    "BLOCKER": "[blocker]",
    "MAJOR": "[major]",
    "MINOR": "[minor]",
    "NIT": "[nit]",
}

RESULT_LABEL = {
    "fail": "FAIL",
    "warn": "WARN",
    "pass": "PASS",
}



def _enforcement(result):
    from drift_gate.core.gating.enforcement import enforcement_outcome
    return enforcement_outcome(result)

# GitHub rejects issue-comment bodies above 65,536 characters (reported by
# third parties; not stated on the REST pages this project reads). The cap
# leaves room for the publication metadata line and the artifact footer.
COMMENT_MAX_CHARS = 60_000
_OMITTED_NOTICE = (
    "> 이 보고서는 GitHub 댓글 길이 제한 때문에 줄여서 표시했습니다. "
    "전체 내용은 Actions 실행 결과의 Markdown·JSON 보고서에서 확인하세요."
)
_MINIMAL_LIST_CAP = 20
_REASON_MAX_CHARS = 500


def _reason(value):
    flat = " ".join(str(value).split())
    return text(flat if len(flat) <= _REASON_MAX_CHARS else flat[:_REASON_MAX_CHARS] + "…")
_VIOLATION_LINE_LIMITS = (None, 200, 100, 50, 20, 10, 5, 0)


class MarkdownReporter:
    MARKER = "<!-- drift-gate-v1 -->"

    def render(
        self,
        result: EvaluationResult,
        *,
        marker: bool = True,
        explain: bool = False,
        max_chars: int | None = None,
    ) -> str:
        """Render the report; with ``max_chars`` shorten it in steps until it fits.

        Steps: drop raw diffs, checklists and model text; then one line per
        violation; then fewer violation lines. Sections are removed whole, so
        code fences and ``<details>`` blocks stay balanced.
        """
        full = self._render(result, marker=marker, explain=explain, detail="full")
        if max_chars is None or len(full) <= max_chars:
            return full
        brief = self._render(result, marker=marker, explain=False, detail="brief", notice=True)
        if len(brief) <= max_chars:
            return brief
        for limit in _VIOLATION_LINE_LIMITS:
            minimal = self._render(result, marker=marker, explain=False, detail="minimal",
                                   notice=True, line_limit=limit)
            if len(minimal) <= max_chars:
                return minimal
        return self._stub(result, marker=marker)

    def _stub(self, result: EvaluationResult, *, marker: bool) -> str:
        """Last resort: the decision and counts only. Always short."""
        lines = [self.MARKER] if marker else []
        lines += ["## Drift Gate Report", "", _OMITTED_NOTICE, "",
                  f"**Result:** `{RESULT_LABEL.get(result.result, result.result)}`", "",
                  f"BLOCKER {result.blocker_count} / MAJOR {result.major_count} / "
                  f"MINOR {result.minor_count} / NIT {result.nit_count} "
                  f"({len(result.violations)} violation(s))"]
        return "\n".join(lines)

    def _render(
        self,
        result: EvaluationResult,
        *,
        marker: bool,
        explain: bool,
        detail: str,
        notice: bool = False,
        line_limit: int | None = None,
    ) -> str:
        lines = []
        if marker:
            lines.append(self.MARKER)

        lines += [
            "## Drift Gate Report",
            "",
        ]
        if notice:
            lines += [_OMITTED_NOTICE, ""]
        lines += [f"**No policy:** `{result.no_policy}`",
                  f"**Schema version:** `{result.to_dict()['schema_version']}`",
                  f"**Skip reason:** `{result.skip_reason or 'none'}`", ""]
        import html

        from drift_gate.core.compat.legacy_result import diagnostic_lines
        lines.extend(re.sub(r'([\\`*_\[\]()])', r'\\\1', html.escape(line)) + '\n'
                     for line in diagnostic_lines(result))
        if result.execution:
            lines += [f"**Execution:** `{result.execution.get('run_id', '')}`",
                      ""]

        if result.advisories:
            lines += ["### 확인이 필요한 환경 변수", ""]
            shown = result.advisories if detail != "minimal" else result.advisories[:_MINIMAL_LIST_CAP]
            for item in shown:
                lines += [f"- {code(item.rule_id)} / {code(item.key)}: {text(item.message)}"]
            if len(shown) < len(result.advisories):
                lines.append(f"- … {len(result.advisories) - len(shown)} more (see the JSON report)")
            lines.append("")
        if result.no_policy:
            lines += self._no_policy_section()
            return "\n".join(lines)

        if result.skip:
            lines += [
                f"**Result:** `{RESULT_LABEL.get(result.result, result.result)}`",
                "",
                f"Policy evaluation skipped because this is a `{result.skip_reason}` PR.",
            ]
            return "\n".join(lines)

        lines += self._status_section(result)
        lines += ["", f"**Verification:** `{result.verification}`"]
        limited = [d for d in result.rule_decisions if d.verification in {"partial", "unverified"}]
        if limited:
            lines += ["", "### Verification limits", "",
                      "A gate PASS is not proof that contract content was verified. Legacy auto may check paths only."]
            for decision in (limited if detail != "minimal" else limited[:_MINIMAL_LIST_CAP]):
                lines.append(f"- {code(decision.rule_id)}: {decision.decision} / {decision.verification}")
                lines.extend(f"  - {text(g.evidence)}" for g in decision.satisfied_groups + decision.unsatisfied_groups if g.verification in {"partial", "unverified"})
        if result.scan_metrics.analysis_notes:
            methods = sorted({note["method"] for note in result.scan_metrics.analysis_notes})
            lines += ["", "**Analysis methods:** " + ", ".join(f"`{method}`" for method in methods),
                      "Fallback and unavailable-input reasons are recorded in the JSON analysis_notes."]

        if not result.violations and limited:
            lines += ["", "**No verified violation recorded; some contract content remains unverified.**"]
        elif not result.violations:
            lines += [
                "",
                "**No contract drift found.** No applied rule has an unsatisfied contract.",
            ]
        else:
            lines += ["", "### Required Action", ""]
            if result.result == "fail":
                lines.append("This PR has blocking contract drift. Update the required docs or add a justified `drift-ignore`.")
            else:
                lines.append("This PR has non-blocking contract drift. Review the missing contract updates below.")
            lines.append("")
            shown_lines = hidden = 0
            for severity in ("BLOCKER", "MAJOR", "MINOR", "NIT"):
                violations = [v for v in result.violations if v.severity == severity]
                if not violations:
                    continue
                lines.append(f"### {SEVERITY_ICON[severity]} {severity}")
                lines.append("")
                for violation in violations:
                    if detail == "minimal":
                        if line_limit is not None and shown_lines >= line_limit:
                            hidden += 1
                            continue
                        shown_lines += 1
                        lines.append(self._violation_line(violation))
                    else:
                        lines += self._violation_section(violation, detail=detail)
                if detail == "minimal":
                    lines.append("")
            if hidden:
                lines += [f"… {hidden} more violation(s) are in the JSON report.", ""]

        lines += self._summary_section(result, detail=detail)
        if explain and detail == "full":
            lines += self._explain_section(result)
        return "\n".join(lines)

    def _status_section(self, result: EvaluationResult) -> list[str]:
        change_types = ", ".join(result.change_types) if result.change_types else "-"
        return [
            f"**Result:** `{RESULT_LABEL.get(result.result, result.result)}`",
            "",
            "| Signal | Value |",
            "|---|---:|",
            f"| Change types | `{change_types}` |",
            f"| Scanned files | {result.scan_metrics.scanned_files} |",
            f"| Skipped ignored files | {result.scan_metrics.skipped_ignored_files} |",
            f"| Skipped binary files | {result.scan_metrics.skipped_binary_files} |",
            f"| Skipped large files | {result.scan_metrics.skipped_large_files} |",
            f"| Evaluated rules | {result.scan_metrics.evaluated_rules} |",
            f"| Runtime | {result.scan_metrics.runtime_seconds:.3f}s |",
            f"| BLOCKER | {result.blocker_count} |",
            f"| MAJOR | {result.major_count} |",
            f"| MINOR | {result.minor_count} |",
            f"| NIT | {result.nit_count} |",
            f"| Temporal warnings | {len(result.temporal_warnings)} |",
        ]

    def _violation_line(self, violation: Violation) -> str:
        message = text(violation.message)[:200] if violation.message else "Contract drift rule was not satisfied."
        files = len(violation.trigger_files)
        return f"- {code(violation.rule_id)}: {message} ({files} trigger file(s))"

    def _violation_section(self, violation: Violation, *, detail: str = "full") -> list[str]:
        confidence = "" if violation.confidence == "high" else f" `[추정]` ({violation.confidence} confidence)"
        lines = [
            f'<a id="{self._anchor_id(violation.rule_id)}"></a>',
            f"#### {code(violation.rule_id)}{confidence}",
            "",
            text(violation.message) if violation.message else "Contract drift rule was not satisfied.",
            "",
            f"**Triggered:** {self._trigger_files(violation, table=False)}",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| Severity | `{violation.severity}` |",
            f"| Change type | `{violation.change_type}` |",
            f"| Change intensity | `{violation.change_intensity}` |",
            f"| Trigger files | {self._trigger_files(violation)} |",
            f"| Matched policy pattern | {self._trigger_patterns(violation)} |",
            f"| Missing docs/contracts | {self._missing_requirements(violation)} |",
            f"| Docs group status | {self._group_status(violation)} |",
            f"| Cross-file relation | {self._cross_file_relations(violation)} |",
            f"| Blast radius | {self._blast_radius(violation)} |",
            "",
            "**Suggested fix**",
            "",
            self._suggested_fix(violation),
            "",
        ]
        if detail == "brief":
            return lines + self._override_section(violation)
        if violation.checklist:
            evidence = [group.evidence for group in violation.unsatisfied_groups if group.evidence]
            if evidence:
                lines += ["**Verification evidence**", ""] + [f"- {text(item)}" for item in evidence] + [""]
            lines += ["**Checklist**", ""]
            lines.extend(f"- [ ] {text(item)}" for item in violation.checklist)
            lines.append("")
        enrichment = self._enrichment_section(violation)
        if enrichment:
            lines += enrichment
        raw_evidence = self._raw_evidence(violation)
        if raw_evidence:
            lines += [
                "<details>",
                "<summary>Raw evidence</summary>",
                "",
                fenced(raw_evidence, "diff"),
                "",
                "</details>",
                "",
            ]
        return lines + self._override_section(violation)

    def _override_section(self, violation: Violation) -> list[str]:
        return [
            "**Override**",
            "",
            "Only if this drift is intentional, add this to the PR description:",
            "",
            fenced(f"drift-ignore: {violation.rule_id}\nreason: <why this is safe>", "md"),
            "",
        ]

    def _summary_section(self, result: EvaluationResult, *, detail: str = "full") -> list[str]:
        cap = None if detail != "minimal" else _MINIMAL_LIST_CAP
        lines = [
            "<details>",
            "<summary>Rule summary</summary>",
            "",
            f"- Gate decision: `{RESULT_LABEL.get(result.result, result.result)}`",
            f"- Enforcement action: `{_enforcement(result)['action']}` ({_enforcement(result)['basis']})",
            f"- Violations: {len(result.violations)}",
            f"- Skipped rules: {len(result.skipped_rules)}",
            f"- Rejected ignores: {len(result.rejected_ignores)}",
            f"- Temporal warnings: {len(result.temporal_warnings)}",
            f"- Advisories: {len(result.advisories)}",
        ]

        if result.skipped_rules:
            lines += ["", "**Applied ignores / 적용된 ignore**"]
            lines.extend(
                f"- {code(rule.rule_id)} ({rule.severity}): {_reason(rule.reason) if rule.reason else 'no reason'}"
                for rule in islice(result.skipped_rules, cap)
            )

        if result.rejected_ignores:
            lines += ["", "**Rejected ignores / 거부된 ignore**"]
            lines.extend(
                f"- {code(rule.rule_id)} ({rule.severity}): {_reason(rule.reason)}"
                for rule in islice(result.rejected_ignores, cap)
            )

        if result.temporal_warnings:
            lines += ["", "**Temporal gate warnings / 반복 ignore 경고**"]
            lines.extend(
                f"- {code(warning.rule_id)} ignored {warning.ignored_count} time(s) "
                f"(threshold {warning.threshold})"
                for warning in islice(result.temporal_warnings, cap)
            )

        lines += ["", "</details>"]
        return lines

    def _explain_section(self, result: EvaluationResult) -> list[str]:
        lines = [
            "",
            "<details>",
            "<summary>Explain evaluation</summary>",
            "",
            "### Evaluated signals",
            "",
            f"- Change types: `{', '.join(result.change_types) if result.change_types else '-'}`",
            f"- Gate: fail_on_blocker={result.gate.fail_on_blocker}, fail_on_major_count={result.gate.fail_on_major_count}",
        ]

        if result.violations:
            lines += ["", "### Rule decisions", ""]
            for violation in result.violations:
                lines += [
                    f"- [{code(violation.rule_id)}](#{self._anchor_id(violation.rule_id)}) matched {len(violation.trigger_files)} trigger file(s)",
                    f"  - intensity: `{violation.change_intensity}`",
                    f"  - matched patterns: {self._trigger_patterns(violation)}",
                    f"  - missing groups: {self._missing_requirements(violation)}",
                ]

        if result.skipped_rules:
            lines += ["", "### Ignored rules", ""]
            lines.extend(
                f"- {code(rule.rule_id)} skipped because a drift-ignore was accepted"
                for rule in result.skipped_rules
            )

        if result.rejected_ignores:
            lines += ["", "### Rejected ignores", ""]
            lines.extend(
                f"- {code(rule.rule_id)} was still evaluated: {_reason(rule.reason)}"
                for rule in result.rejected_ignores
            )

        lines += ["", "</details>"]
        return lines

    def _no_policy_section(self) -> list[str]:
        return [
            "**Result:** `PASS`",
            "",
            "No `.drift-gate.yml` policy was found, so Drift Gate did not evaluate contract drift.",
            "",
            "Add a policy file to enable PR checks:",
            "",
            "```yaml",
            "rules:",
            "  - id: api-contract-sync",
            "    when:",
            '      any_changed: ["src/routes/**", "openapi/**"]',
            "    require:",
            "      groups:",
            '        - name: "API docs"',
            '          any_changed: ["docs/spec.md", "docs/api/**"]',
            "    severity: blocker",
            '    message: "API surface changed without synced contract docs"',
            "```",
        ]

    def _trigger_files(self, violation: Violation, *, table: bool = True) -> str:
        if not violation.trigger_files:
            return "-"
        return "<br>".join(self._format_file(file, table=table) for file in violation.trigger_files)

    def _format_file(self, file, *, table: bool = True) -> str:
        if file.previous_path:
            return f"{code(file.path, table=table)} ({file.status}, from {code(file.previous_path, table=table)})"
        return f"{code(file.path, table=table)} ({file.status})"

    def _trigger_patterns(self, violation: Violation) -> str:
        if not violation.trigger_patterns:
            return "-"
        return ", ".join(code(pattern, table=True) for pattern in violation.trigger_patterns)

    def _missing_requirements(self, violation: Violation) -> str:
        if not violation.unsatisfied_groups:
            return "-"
        groups = []
        for group in violation.unsatisfied_groups:
            required = ", ".join(code(item, table=True) for item in group.required)
            groups.append(f"**{text(group.name)}**: {required}")
        return "<br>".join(groups)

    def _group_status(self, violation: Violation) -> str:
        parts = []
        for group in violation.satisfied_groups:
            parts.append(f"PASS **{text(group.name)}**")
        for group in violation.unsatisfied_groups:
            parts.append(f"FAIL **{text(group.name)}**")
        return "<br>".join(parts) if parts else "-"

    def _blast_radius(self, violation: Violation) -> str:
        if not violation.blast_radius:
            return "-"
        return "<br>".join(code(item, table=True) for item in violation.blast_radius)

    def _cross_file_relations(self, violation: Violation) -> str:
        if not violation.cross_file_relations:
            return "-"
        return ", ".join(code(item, table=True) for item in violation.cross_file_relations)

    def _raw_evidence(self, violation: Violation) -> str:
        lines = []
        for file in violation.trigger_files:
            if file.patch:
                lines.append("# " + " ".join(file.path.split()))
            for raw in file.patch.splitlines():
                if raw.startswith(("diff --git", "index ")):
                    continue
                if raw.startswith(("+++", "---", "@@", "+", "-")):
                    lines.append(raw)
                if len(lines) >= 28:
                    break
            if len(lines) >= 28:
                break
        return "\n".join(lines)

    def _anchor_id(self, rule_id: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", rule_id).strip("-")
        return f"rule-{slug or 'violation'}"

    def _suggested_fix(self, violation: Violation) -> str:
        missing = []
        for group in violation.unsatisfied_groups:
            missing.extend(group.required)
        if missing:
            docs = " or ".join(code(item) for item in missing)
            return f"Update {docs} so it reflects the changed contract."
        return "Update the contract documentation required by this rule."

    def _enrichment_section(self, violation: Violation) -> list[str]:
        lines = []
        if violation.changed_contract_summary:
            lines += ["**Changed contract summary**", "", block(violation.changed_contract_summary), ""]
        if violation.missing_docs_explanation:
            lines += ["**Missing docs explanation**", "", block(violation.missing_docs_explanation), ""]
        if violation.docs_update_draft:
            lines += [
                "<details>",
                "<summary>Docs update draft</summary>",
                "",
                fenced(violation.docs_update_draft, "md"),
                "",
                "</details>",
                "",
            ]
        if violation.false_positive_note:
            lines += ["**False positive candidate**", "", block(violation.false_positive_note), ""]
        return lines
