"""
Markdown report renderer.

The report is optimized for PR comments: short summary first, then concrete
fix guidance for every violation.
"""
from drift_gate.core.models.result import EvaluationResult, Violation
import re


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


class MarkdownReporter:
    MARKER = "<!-- drift-gate-v1 -->"

    def render(
        self,
        result: EvaluationResult,
        *,
        marker: bool = True,
        explain: bool = False,
    ) -> str:
        lines = []
        if marker:
            lines.append(self.MARKER)

        lines += [
            "## Drift Gate Report",
            "",
        ]

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

        if not result.violations:
            lines += [
                "",
                "**No contract drift found.** All configured policy rules passed.",
            ]
        else:
            lines += ["", "### Required Action", ""]
            if result.result == "fail":
                lines.append("This PR has blocking contract drift. Update the required docs or add a justified `drift-ignore`.")
            else:
                lines.append("This PR has non-blocking contract drift. Review the missing contract updates below.")
            lines.append("")
            for severity in ("BLOCKER", "MAJOR", "MINOR", "NIT"):
                violations = [v for v in result.violations if v.severity == severity]
                if not violations:
                    continue
                lines.append(f"### {SEVERITY_ICON[severity]} {severity}")
                lines.append("")
                for violation in violations:
                    lines += self._violation_section(violation)

        lines += self._summary_section(result)
        if explain:
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

    def _violation_section(self, violation: Violation) -> list[str]:
        confidence = "" if violation.confidence == "high" else f" `[추정]` ({violation.confidence} confidence)"
        lines = [
            f'<a id="{self._anchor_id(violation.rule_id)}"></a>',
            f"#### `{violation.rule_id}`{confidence}",
            "",
            violation.message or "Contract drift rule was not satisfied.",
            "",
            f"**Triggered:** {self._trigger_files(violation)}",
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
        if violation.checklist:
            lines += ["**Checklist**", ""]
            lines.extend(f"- [ ] {item}" for item in violation.checklist)
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
                "```diff",
                raw_evidence,
                "```",
                "",
                "</details>",
                "",
            ]
        lines += [
            "**Override**",
            "",
            "Only if this drift is intentional, add this to the PR description:",
            "",
            "```md",
            f"drift-ignore: {violation.rule_id}",
            "reason: <why this is safe>",
            "```",
            "",
        ]
        return lines

    def _summary_section(self, result: EvaluationResult) -> list[str]:
        lines = [
            "<details>",
            "<summary>Rule summary</summary>",
            "",
            f"- Gate decision: `{RESULT_LABEL.get(result.result, result.result)}`",
            f"- Violations: {len(result.violations)}",
            f"- Skipped rules: {len(result.skipped_rules)}",
            f"- Rejected ignores: {len(result.rejected_ignores)}",
            f"- Temporal warnings: {len(result.temporal_warnings)}",
        ]

        if result.skipped_rules:
            lines += ["", "**Applied ignores / 적용된 ignore**"]
            lines.extend(
                f"- `{rule.rule_id}` ({rule.severity}): {rule.reason or 'no reason'}"
                for rule in result.skipped_rules
            )

        if result.rejected_ignores:
            lines += ["", "**Rejected ignores / 거부된 ignore**"]
            lines.extend(
                f"- `{rule.rule_id}` ({rule.severity}): {rule.reason}"
                for rule in result.rejected_ignores
            )

        if result.temporal_warnings:
            lines += ["", "**Temporal gate warnings / 반복 ignore 경고**"]
            lines.extend(
                f"- `{warning.rule_id}` ignored {warning.ignored_count} time(s) "
                f"(threshold {warning.threshold})"
                for warning in result.temporal_warnings
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
                    f"- [`{violation.rule_id}`](#{self._anchor_id(violation.rule_id)}) matched {len(violation.trigger_files)} trigger file(s)",
                    f"  - intensity: `{violation.change_intensity}`",
                    f"  - matched patterns: {self._trigger_patterns(violation)}",
                    f"  - missing groups: {self._missing_requirements(violation)}",
                ]

        if result.skipped_rules:
            lines += ["", "### Ignored rules", ""]
            lines.extend(
                f"- `{rule.rule_id}` skipped because a drift-ignore was accepted"
                for rule in result.skipped_rules
            )

        if result.rejected_ignores:
            lines += ["", "### Rejected ignores", ""]
            lines.extend(
                f"- `{rule.rule_id}` was still evaluated: {rule.reason}"
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

    def _trigger_files(self, violation: Violation) -> str:
        if not violation.trigger_files:
            return "-"
        return "<br>".join(self._format_file(file) for file in violation.trigger_files)

    def _format_file(self, file) -> str:
        if file.previous_path:
            return f"`{file.path}` ({file.status}, from `{file.previous_path}`)"
        return f"`{file.path}` ({file.status})"

    def _trigger_patterns(self, violation: Violation) -> str:
        if not violation.trigger_patterns:
            return "-"
        return "`" + "`, `".join(violation.trigger_patterns) + "`"

    def _missing_requirements(self, violation: Violation) -> str:
        if not violation.unsatisfied_groups:
            return "-"
        groups = []
        for group in violation.unsatisfied_groups:
            required = "`, `".join(group.required)
            groups.append(f"**{group.name}**: `{required}`")
        return "<br>".join(groups)

    def _group_status(self, violation: Violation) -> str:
        parts = []
        for group in violation.satisfied_groups:
            parts.append(f"PASS **{group.name}**")
        for group in violation.unsatisfied_groups:
            parts.append(f"FAIL **{group.name}**")
        return "<br>".join(parts) if parts else "-"

    def _blast_radius(self, violation: Violation) -> str:
        if not violation.blast_radius:
            return "-"
        return "<br>".join(f"`{item}`" for item in violation.blast_radius)

    def _cross_file_relations(self, violation: Violation) -> str:
        if not violation.cross_file_relations:
            return "-"
        return "`" + "`, `".join(violation.cross_file_relations) + "`"

    def _raw_evidence(self, violation: Violation) -> str:
        lines = []
        for file in violation.trigger_files:
            if file.patch:
                lines.append(f"# {file.path}")
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
            docs = "` or `".join(missing)
            return f"Update `{docs}` so it reflects the changed contract."
        return "Update the contract documentation required by this rule."

    def _enrichment_section(self, violation: Violation) -> list[str]:
        lines = []
        if violation.changed_contract_summary:
            lines += ["**Changed contract summary**", "", violation.changed_contract_summary, ""]
        if violation.missing_docs_explanation:
            lines += ["**Missing docs explanation**", "", violation.missing_docs_explanation, ""]
        if violation.docs_update_draft:
            lines += [
                "<details>",
                "<summary>Docs update draft</summary>",
                "",
                violation.docs_update_draft,
                "",
                "</details>",
                "",
            ]
        if violation.false_positive_note:
            lines += ["**False positive candidate**", "", violation.false_positive_note, ""]
        return lines
