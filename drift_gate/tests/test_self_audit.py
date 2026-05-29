"""
Tests for self-audit checklist parser and evidence matcher.
Covers: checklist parsing, evidence matching, warnings, fixtures.
No network or subprocess calls.
"""
from __future__ import annotations

import pytest

from drift_gate.adapters.docs.checklist import (
    ChecklistItem,
    parse_checklist_text,
    _extract_hints,
)
from drift_gate.core.self_audit.matcher import (
    AuditedItem,
    DiffEvidence,
    SelfAuditResult,
    SelfAuditWarning,
    match_checklist,
)


# ── checklist parser ───────────────────────────────────────────────────────────

class TestChecklistParser:
    def test_parses_checked_item(self):
        md = "- [x] Update docs/spec.md\n"
        items = parse_checklist_text(md)
        assert len(items) == 1
        assert items[0].checked is True
        assert items[0].text == "Update docs/spec.md"

    def test_parses_unchecked_item(self):
        md = "- [ ] Implement self-audit\n"
        items = parse_checklist_text(md)
        assert items[0].checked is False

    def test_parses_uppercase_x(self):
        md = "- [X] Done\n"
        items = parse_checklist_text(md)
        assert items[0].checked is True

    def test_parses_multiple_items(self):
        md = (
            "- [x] First item\n"
            "- [ ] Second item\n"
            "- [x] Third item\n"
        )
        items = parse_checklist_text(md)
        assert len(items) == 3
        assert items[0].checked is True
        assert items[1].checked is False
        assert items[2].checked is True

    def test_captures_section_heading(self):
        md = (
            "## Section A\n\n"
            "- [x] Do something\n"
        )
        items = parse_checklist_text(md)
        assert items[0].section == "Section A"

    def test_line_number_is_correct(self):
        md = "\n\n- [x] Item on line 3\n"
        items = parse_checklist_text(md)
        assert items[0].line_number == 3

    def test_ignores_non_checkbox_list_items(self):
        md = "- Regular list item (no checkbox)\n- [x] Real checkbox\n"
        items = parse_checklist_text(md)
        assert len(items) == 1
        assert items[0].text == "Real checkbox"

    def test_indented_items_captured(self):
        md = "  - [x] Indented item\n"
        items = parse_checklist_text(md)
        assert len(items) == 1
        assert items[0].indent_level == 2

    def test_extracts_file_hint_from_backtick(self):
        md = "- [x] Update `drift_gate/adapters/claude/enricher.py`\n"
        items = parse_checklist_text(md)
        assert any("enricher.py" in h for h in items[0].file_hints)

    def test_extracts_rule_id_hint(self):
        md = "- [x] Fix api-contract-sync rule\n"
        items = parse_checklist_text(md)
        assert "api-contract-sync" in items[0].rule_id_hints

    def test_empty_document(self):
        items = parse_checklist_text("")
        assert items == []

    def test_document_with_only_headings(self):
        md = "# Title\n## Section\n"
        items = parse_checklist_text(md)
        assert items == []


# ── diff evidence ──────────────────────────────────────────────────────────────

class TestDiffEvidence:
    def test_from_raw_extracts_changed_files(self):
        ev = DiffEvidence.from_raw(
            changed_files=["drift_gate/adapters/claude/enricher.py"],
            patch_text="",
        )
        assert "drift_gate/adapters/claude/enricher.py" in ev.changed_files

    def test_from_raw_extracts_added_functions(self):
        patch = "+    def _call_api(self, prompt):\n"
        ev = DiffEvidence.from_raw(changed_files=[], patch_text=patch)
        assert "_call_api" in ev.added_functions

    def test_from_raw_extracts_added_classes(self):
        patch = "+class EnrichmentMetrics:\n"
        ev = DiffEvidence.from_raw(changed_files=[], patch_text=patch)
        assert "EnrichmentMetrics" in ev.added_classes

    def test_from_raw_extracts_test_names(self):
        patch = "+    def test_usage_parsing(self):\n"
        ev = DiffEvidence.from_raw(changed_files=[], patch_text=patch)
        assert "test_usage_parsing" in ev.added_test_names

    def test_from_raw_ignores_removed_lines(self):
        patch = "-    def old_function(self):\n"
        ev = DiffEvidence.from_raw(changed_files=[], patch_text=patch)
        assert "old_function" not in ev.added_functions


# ── matcher ────────────────────────────────────────────────────────────────────

class TestMatcher:
    def _make_item(
        self,
        text: str,
        checked: bool = True,
        file_hints: list[str] | None = None,
        rule_id_hints: list[str] | None = None,
    ) -> ChecklistItem:
        item = ChecklistItem(
            text=text,
            checked=checked,
            line_number=1,
            indent_level=0,
            section="Test",
            file_hints=file_hints or [],
            rule_id_hints=rule_id_hints or [],
        )
        return item

    def test_checked_item_with_matching_file_is_supported(self):
        item = self._make_item(
            "Update enricher.py", file_hints=["enricher.py"]
        )
        ev = DiffEvidence.from_raw(
            changed_files=["drift_gate/adapters/claude/enricher.py"]
        )
        result = match_checklist([item], ev)
        assert result.checklist_items[0].status == "supported"
        assert len(result.warnings) == 0

    def test_checked_item_without_evidence_is_unsupported(self):
        item = self._make_item(
            "Update README with new API docs", file_hints=["README.md"]
        )
        ev = DiffEvidence.from_raw(changed_files=["drift_gate/core/engine.py"])
        result = match_checklist([item], ev)
        assert result.checklist_items[0].status == "unsupported"

    def test_checklist_code_mismatch_warning_on_unsupported(self):
        item = self._make_item(
            "Update missing-file.py", file_hints=["missing-file.py"]
        )
        ev = DiffEvidence.from_raw(changed_files=[])
        result = match_checklist([item], ev)
        kinds = [w.kind for w in result.warnings]
        assert "checklist-code-mismatch" in kinds

    def test_unchecked_item_is_status_unchecked(self):
        item = self._make_item("Not done yet", checked=False)
        # Use a non-source file so no missing-progress-entry warning is triggered
        ev = DiffEvidence.from_raw(changed_files=["docs/notes.md"])
        result = match_checklist([item], ev)
        assert result.checklist_items[0].status == "unchecked"
        assert len(result.warnings) == 0

    def test_missing_progress_entry_warning(self):
        """A changed source file with no matching checked item gets a warning."""
        items = []  # no items at all
        ev = DiffEvidence.from_raw(
            changed_files=["drift_gate/core/new_feature.py"]
        )
        result = match_checklist(items, ev)
        kinds = [w.kind for w in result.warnings]
        assert "missing-progress-entry" in kinds

    def test_no_missing_progress_for_non_source_files(self):
        """Markdown and YAML changes don't trigger missing-progress-entry."""
        items = []
        ev = DiffEvidence.from_raw(
            changed_files=["README.md", ".drift-gate.yml", "docs/spec.md"]
        )
        result = match_checklist(items, ev)
        kinds = [w.kind for w in result.warnings]
        assert "missing-progress-entry" not in kinds

    def test_evidence_includes_file_path(self):
        item = self._make_item(
            "Updated enricher", file_hints=["enricher.py"]
        )
        ev = DiffEvidence.from_raw(
            changed_files=["drift_gate/adapters/claude/enricher.py"]
        )
        result = match_checklist([item], ev)
        assert "drift_gate/adapters/claude/enricher.py" in result.checklist_items[0].evidence

    def test_evidence_includes_function_name(self):
        item = ChecklistItem(
            text="implement _call_api()",
            checked=True,
            line_number=1,
            indent_level=0,
            section="",
            function_hints=["_call_api"],
        )
        ev = DiffEvidence.from_raw(
            changed_files=[],
            patch_text="+    def _call_api(self, prompt):\n",
        )
        result = match_checklist([item], ev)
        assert any("function:" in e for e in result.checklist_items[0].evidence)

    def test_to_dict_structure(self):
        item = self._make_item("Some item", checked=True, file_hints=["foo.py"])
        ev = DiffEvidence.from_raw(changed_files=["foo.py"])
        result = match_checklist([item], ev)
        d = result.to_dict()
        assert "self_audit" in d
        assert "checklist_items" in d["self_audit"]
        assert "warnings" in d["self_audit"]

    def test_multiple_items_mixed(self):
        items = [
            self._make_item("Add EnrichmentMetrics", file_hints=["result.py"]),
            self._make_item("Not done item", checked=False, file_hints=["other.py"]),
            self._make_item("Uncovered checked item", checked=True, file_hints=["ghost.py"]),
        ]
        ev = DiffEvidence.from_raw(
            changed_files=["drift_gate/core/models/result.py"]
        )
        result = match_checklist(items, ev)
        statuses = [i.status for i in result.checklist_items]
        assert statuses[0] == "supported"
        assert statuses[1] == "unchecked"
        assert statuses[2] == "unsupported"


# ── fixture scenarios ─────────────────────────────────────────────────────────

FIXTURE_SUPPORTED_MD = """\
## 7-2. Token savings

- [x] Parse `usage.cache_read_input_tokens` from Claude response
- [x] Add `EnrichmentMetrics` to `drift_gate/core/models/result.py`
"""

FIXTURE_UNSUPPORTED_MD = """\
## 7-3. Docs check

- [x] Add `docs-check` command — no evidence in diff
"""

FIXTURE_MISSING_PROGRESS_MD = """\
## Section

- [ ] Not yet implemented
"""


class TestFixtureScenarios:
    def test_fixture_supported(self):
        """Items that reference changed files should be 'supported'."""
        items = parse_checklist_text(FIXTURE_SUPPORTED_MD)
        ev = DiffEvidence.from_raw(
            changed_files=[
                "drift_gate/core/models/result.py",
                "drift_gate/adapters/claude/enricher.py",
            ],
            patch_text="+class EnrichmentMetrics:\n",
        )
        result = match_checklist(items, ev)
        supported = [i for i in result.checklist_items if i.status == "supported"]
        assert len(supported) >= 1

    def test_fixture_unsupported(self):
        """Checked item with no diff evidence should be 'unsupported'."""
        items = parse_checklist_text(FIXTURE_UNSUPPORTED_MD)
        ev = DiffEvidence.from_raw(changed_files=[])
        result = match_checklist(items, ev)
        assert result.checklist_items[0].status == "unsupported"
        assert any(w.kind == "checklist-code-mismatch" for w in result.warnings)

    def test_fixture_missing_progress_entry(self):
        """Changed source file with only unchecked items triggers missing-progress-entry."""
        items = parse_checklist_text(FIXTURE_MISSING_PROGRESS_MD)
        ev = DiffEvidence.from_raw(
            changed_files=["drift_gate/core/self_audit/matcher.py"]
        )
        result = match_checklist(items, ev)
        assert any(w.kind == "missing-progress-entry" for w in result.warnings)


# ── table-cell checkbox parser (3-column tables) ──────────────────────────────

TABLE_3COL_MD = """\
## 2-1. CLI 명령 동작

| 명령 | 검증 방법 | 상태 |
|------|-----------|------|
| `py main.py check` | 로컬 diff 분석 후 결과 출력 | `[x]` 확인 (`doctor` 출력에서 48 files diff) |
| `py main.py doctor` | OK/WARN 체크리스트 출력 | `[x]` 확인 |
| `py main.py demo` | benchmark.html 생성 | `[x]` 확인 (벤치마크 마크다운 출력) |
| `py main.py init --preset api` | `.drift-gate.yml` 생성 | `[ ]` 직접 실행 후 파일 생성 확인 필요 |
"""

TABLE_2COL_MD = """\
## 2-2. 핵심 정책 엔진

| 기능 | 상태 |
|------|------|
| docs-only PR → pass | `[x]` 258 passed |
| BLOCKER → fail | `[ ]` 미확인 |
"""


class TestTableCellParser:
    def test_3col_table_checked_count(self):
        items = parse_checklist_text(TABLE_3COL_MD)
        checked = [i for i in items if i.checked]
        assert len(checked) == 3

    def test_3col_table_unchecked_count(self):
        items = parse_checklist_text(TABLE_3COL_MD)
        unchecked = [i for i in items if not i.checked]
        assert len(unchecked) == 1

    def test_2col_table_checked(self):
        items = parse_checklist_text(TABLE_2COL_MD)
        checked = [i for i in items if i.checked]
        assert len(checked) == 1

    def test_table_item_has_section(self):
        items = parse_checklist_text(TABLE_3COL_MD)
        assert all(i.section == "2-1. CLI 명령 동작" for i in items)

    def test_table_item_text_contains_subject(self):
        items = parse_checklist_text(TABLE_3COL_MD)
        subjects = [i.text for i in items]
        assert any("py main.py check" in s for s in subjects)

    def test_mixed_table_and_list(self):
        md = (
            "## Section\n\n"
            "| cmd | desc | `[x]` done |\n"
            "- [x] List item\n"
            "- [ ] Unchecked\n"
        )
        items = parse_checklist_text(md)
        checked = [i for i in items if i.checked]
        assert len(checked) == 2
