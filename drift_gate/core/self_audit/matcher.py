"""
Self-audit evidence matcher (core, pure logic — no I/O).

Matches checklist items against a set of diff evidence (changed file paths,
function/class names, test names, rule IDs) and produces structured results.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class DiffEvidence:
    """All evidence extracted from a git diff."""

    changed_files: List[str] = field(default_factory=list)
    added_functions: List[str] = field(default_factory=list)
    added_classes: List[str] = field(default_factory=list)
    added_test_names: List[str] = field(default_factory=list)
    rule_ids_mentioned: List[str] = field(default_factory=list)

    @classmethod
    def from_raw(
        cls,
        *,
        changed_files: List[str],
        patch_text: str = "",
    ) -> "DiffEvidence":
        """Build DiffEvidence from a list of file paths and an optional unified diff."""
        import re

        funcs = re.findall(r"^\+\s*def\s+([a-zA-Z_][a-zA-Z0-9_]*)\(", patch_text, re.MULTILINE)
        classes = re.findall(r"^\+\s*class\s+([A-Z][a-zA-Z0-9_]*)\b", patch_text, re.MULTILINE)
        tests = re.findall(r"^\+\s*def\s+(test[_a-zA-Z0-9]+)\(", patch_text, re.MULTILINE)
        rule_ids = re.findall(r"\b([a-z][a-z0-9]{2,}-[a-z0-9-]+)\b", patch_text)
        return cls(
            changed_files=changed_files,
            added_functions=funcs,
            added_classes=classes,
            added_test_names=tests,
            rule_ids_mentioned=rule_ids,
        )


@dataclass
class AuditedItem:
    """Result of matching a single checklist item against diff evidence."""

    text: str
    checked: bool
    line_number: int
    section: str
    evidence: List[str]
    status: str  # "supported" | "unsupported" | "unchecked"

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "checked": self.checked,
            "line_number": self.line_number,
            "section": self.section,
            "evidence": self.evidence,
            "status": self.status,
        }


@dataclass
class SelfAuditWarning:
    kind: str   # "checklist-code-mismatch" | "missing-progress-entry"
    message: str
    details: str = ""

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class SelfAuditResult:
    checklist_items: List[AuditedItem]
    warnings: List[SelfAuditWarning]

    def to_dict(self) -> dict:
        return {
            "self_audit": {
                "checklist_items": [i.to_dict() for i in self.checklist_items],
                "warnings": [w.to_dict() for w in self.warnings],
            }
        }


def match_checklist(
    items,  # List[ChecklistItem] — imported from adapters layer, passed in
    evidence: DiffEvidence,
) -> SelfAuditResult:
    """Match checklist items against diff evidence.

    Rules:
    - Checked items with matching evidence → "supported"
    - Checked items without matching evidence → "unsupported" + checklist-code-mismatch warning
    - Unchecked items → "unchecked" (no warning)
    - Changed files in evidence that match NO checked item → missing-progress-entry warning
    """
    audited: List[AuditedItem] = []
    warnings: List[SelfAuditWarning] = []

    # Track which evidence files are matched by some checked item
    evidence_files_lower = {f.lower() for f in evidence.changed_files}
    matched_evidence_files: set[str] = set()

    for item in items:
        ev = _find_evidence(item, evidence)
        if item.checked:
            status = "supported" if ev else "unsupported"
            if not ev:
                warnings.append(SelfAuditWarning(
                    kind="checklist-code-mismatch",
                    message=f"Checked item has no evidence in diff: \"{item.text}\"",
                    details=f"line {item.line_number} in section '{item.section}'",
                ))
            else:
                for e in ev:
                    matched_evidence_files.add(e.lower())
        else:
            status = "unchecked"

        audited.append(AuditedItem(
            text=item.text,
            checked=item.checked,
            line_number=item.line_number,
            section=item.section,
            evidence=ev,
            status=status,
        ))

    # Warn about changed files that no checked item claimed
    _SOURCE_EXTENSIONS = {
        ".py", ".ts", ".js", ".go", ".java", ".rb", ".kt", ".rs", ".cpp", ".c",
    }
    for f in evidence.changed_files:
        from pathlib import Path as _Path
        if _Path(f).suffix not in _SOURCE_EXTENSIONS:
            continue
        if f.lower() not in matched_evidence_files:
            warnings.append(SelfAuditWarning(
                kind="missing-progress-entry",
                message=f"Changed file has no corresponding checked checklist item: {f}",
                details="Add or check an item in the checklist that documents this change.",
            ))

    return SelfAuditResult(checklist_items=audited, warnings=warnings)


def _find_evidence(item, evidence: DiffEvidence) -> List[str]:
    """Return a list of evidence strings that match the checklist item."""
    found: List[str] = []

    item_text_lower = item.text.lower()

    # Match against changed file paths
    for f in evidence.changed_files:
        # Partial path match: any hint appears in the file path or vice-versa
        f_lower = f.lower()
        for hint in item.file_hints:
            hint_lower = hint.lower()
            if hint_lower in f_lower or f_lower.endswith(hint_lower):
                found.append(f)
                break
        else:
            # Fallback: any segment of the file path appears in the item text
            from pathlib import PurePosixPath
            parts = PurePosixPath(f).parts
            for part in parts:
                if len(part) > 3 and part.lower() in item_text_lower:
                    found.append(f)
                    break

    # Match against added functions
    for func in evidence.added_functions:
        func_lower = func.lower()
        if func_lower in item_text_lower or any(h.lower() == func_lower for h in item.function_hints):
            found.append(f"function:{func}")

    # Match against added classes
    for cls in evidence.added_classes:
        cls_lower = cls.lower()
        if cls_lower in item_text_lower or any(h.lower() == cls_lower for h in item.class_hints):
            found.append(f"class:{cls}")

    # Match against test names
    for test in evidence.added_test_names:
        test_lower = test.lower()
        if test_lower in item_text_lower or any(h.lower() == test_lower for h in item.test_hints):
            found.append(f"test:{test}")

    # Match against rule IDs
    for rule_id in evidence.rule_ids_mentioned:
        if rule_id in item_text_lower or rule_id in item.rule_id_hints:
            found.append(f"rule:{rule_id}")

    return list(dict.fromkeys(found))  # deduplicate while preserving order
