"""
Markdown checkbox parser for self-audit.

Parses `[x]` / `[ ]` checklist items from Markdown files.
Only reads files — no network, no subprocess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


_CHECKBOX_RE = re.compile(
    r"^(?P<indent>[ \t]*)[-*+]\s+\[(?P<mark>[xX ])\]\s+(?P<text>.+)$",
    re.MULTILINE,
)
# Table-cell checkbox: `| cmd | desc | `[x]` 확인 |`
# Captures the first cell as subject, skips exactly one middle column, then finds `[x]` in the last cell.
# Works for both 2-column (| subject | `[x]` note |) and 3-column
# (| subject | middle | `[x]` note |) tables.
# The original (?:[^|]*\|)* pattern was too greedy and consumed the whole row in practice.
_TABLE_CHECKBOX_RE = re.compile(
    r"^\|(?P<subject>[^|]+)\|(?:[^|]*\|){0,3}\s*`\[(?P<mark>[xX ])\]`(?P<suffix>[^|]*)\|",
    re.MULTILINE,
)
# Patterns used for evidence extraction from checklist item text
_FILE_PATH_RE = re.compile(r"`([^`]+\.[a-zA-Z]{1,10})`|([a-zA-Z0-9_./-]+\.[a-zA-Z]{2,6})")
_RULE_ID_RE = re.compile(r"\b([a-z][a-z0-9-]{3,})\b")
_FUNCTION_RE = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\(\)")
_CLASS_RE = re.compile(r"\b([A-Z][A-Za-z0-9]+)\b")
_TEST_NAME_RE = re.compile(r"\btest[_A-Za-z0-9]+\b")


@dataclass
class ChecklistItem:
    """A single checkbox line parsed from a Markdown document."""

    text: str
    checked: bool
    line_number: int
    indent_level: int
    section: str = ""

    # Extracted keyword hints used for evidence matching
    file_hints: List[str] = field(default_factory=list)
    rule_id_hints: List[str] = field(default_factory=list)
    function_hints: List[str] = field(default_factory=list)
    class_hints: List[str] = field(default_factory=list)
    test_hints: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "checked": self.checked,
            "line_number": self.line_number,
            "section": self.section,
            "file_hints": self.file_hints,
            "rule_id_hints": self.rule_id_hints,
            "function_hints": self.function_hints,
            "class_hints": self.class_hints,
            "test_hints": self.test_hints,
        }


def parse_checklist(path: Path) -> List[ChecklistItem]:
    """Parse all `[ ]` / `[x]` checkbox items from a Markdown file.

    Returns a list of ChecklistItem, preserving document order.
    Items are enriched with keyword hints extracted from their text.
    """
    content = path.read_text(encoding="utf-8", errors="replace")
    return parse_checklist_text(content)


def parse_checklist_text(content: str) -> List[ChecklistItem]:
    """Parse checkbox items from a Markdown string."""
    items: List[ChecklistItem] = []
    current_section = ""

    lines = content.splitlines()
    line_starts: dict[int, int] = {}  # offset -> line_number
    offset = 0
    for i, line in enumerate(lines, start=1):
        line_starts[offset] = i
        offset += len(line) + 1  # +1 for newline

    # Track sections (headings)
    heading_re = re.compile(r"^(#{1,6})\s+(.+)$")
    # Build line-number to section mapping
    section_at_line: dict[int, str] = {}
    cur_section = ""
    for i, line in enumerate(lines, start=1):
        h = heading_re.match(line)
        if h:
            cur_section = h.group(2).strip()
        section_at_line[i] = cur_section

    seen_lines: set[int] = set()

    for match in _CHECKBOX_RE.finditer(content):
        start = match.start()
        line_num = _offset_to_line(start, lines)
        section = section_at_line.get(line_num, "")
        indent = len(match.group("indent"))
        mark = match.group("mark")
        text = match.group("text").strip()

        item = ChecklistItem(
            text=text,
            checked=mark.lower() == "x",
            line_number=line_num,
            indent_level=indent,
            section=section,
        )
        _extract_hints(item)
        items.append(item)
        seen_lines.add(line_num)

    # Also parse table-cell checkboxes: `| cmd | desc | `[x]` 확인 |`
    for match in _TABLE_CHECKBOX_RE.finditer(content):
        start = match.start()
        line_num = _offset_to_line(start, lines)
        if line_num in seen_lines:
            continue
        section = section_at_line.get(line_num, "")
        mark = match.group("mark")
        subject = match.group("subject").strip().strip("`")
        suffix = match.group("suffix").strip()
        text = (subject + " " + suffix).strip() if suffix else subject

        item = ChecklistItem(
            text=text,
            checked=mark.lower() == "x",
            line_number=line_num,
            indent_level=0,
            section=section,
        )
        _extract_hints(item)
        items.append(item)
        seen_lines.add(line_num)

    items.sort(key=lambda i: i.line_number)
    return items


def _offset_to_line(offset: int, lines: List[str]) -> int:
    pos = 0
    for i, line in enumerate(lines, start=1):
        end = pos + len(line) + 1
        if offset < end:
            return i
        pos = end
    return len(lines)


def _extract_hints(item: ChecklistItem) -> None:
    """Populate hint lists on the item by pattern-matching its text."""
    text = item.text

    # File paths: backtick-quoted or bare paths with extensions
    for m in _FILE_PATH_RE.finditer(text):
        candidate = m.group(1) or m.group(2)
        if candidate and "/" in candidate or "." in candidate:
            item.file_hints.append(candidate)

    # Rule IDs: dash-separated lowercase slugs (e.g. api-contract-sync)
    for m in _RULE_ID_RE.finditer(text):
        slug = m.group(1)
        if "-" in slug and len(slug) > 6:
            item.rule_id_hints.append(slug)

    # Function names: word()
    for m in _FUNCTION_RE.finditer(text):
        item.function_hints.append(m.group(1))

    # Class names: PascalCase
    for m in _CLASS_RE.finditer(text):
        item.class_hints.append(m.group(1))

    # Test names
    for m in _TEST_NAME_RE.finditer(text):
        item.test_hints.append(m.group(0))
