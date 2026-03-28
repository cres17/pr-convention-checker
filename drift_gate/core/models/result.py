from dataclasses import dataclass, field
from typing import List, Optional

from .changed_file import ChangedFile
from .policy import Gate


@dataclass
class DriftIgnoreDirective:
    rule_id: str
    reason: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "DriftIgnoreDirective":
        return cls(rule_id=d["rule_id"], reason=d.get("reason"))


@dataclass
class UnsatisfiedGroup:
    name: str
    required: List[str]
    type: str  # any_changed | all_changed

    def to_dict(self) -> dict:
        return {"name": self.name, "required": self.required, "type": self.type}


@dataclass
class Violation:
    rule_id: str
    severity: str       # BLOCKER | MAJOR | MINOR | NIT
    confidence: str     # high | medium | low
    change_types: List[str]
    change_type: str    # primary type (change_types[0])
    message: str
    trigger_files: List[ChangedFile]
    unsatisfied_groups: List[UnsatisfiedGroup]
    checklist: List[str]
    ignored: bool = False

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "confidence": self.confidence,
            "change_types": self.change_types,
            "change_type": self.change_type,
            "message": self.message,
            "trigger_files": [f.to_dict() for f in self.trigger_files],
            "unsatisfied_groups": [g.to_dict() for g in self.unsatisfied_groups],
            "checklist": self.checklist,
            "ignored": self.ignored,
        }


@dataclass
class SkippedRule:
    rule_id: str
    severity: str
    reason: str
    message: str

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "reason": self.reason,
            "message": self.message,
        }


@dataclass
class RejectedIgnore:
    rule_id: str
    severity: str
    message: str

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass
class EvaluationResult:
    change_types: List[str]
    violations: List[Violation]
    skipped_rules: List[SkippedRule]
    rejected_ignores: List[RejectedIgnore]
    gate: Gate
    result: str = "pass"        # pass | warn | fail
    skip: bool = False
    skip_reason: str = ""
    no_policy: bool = False

    @property
    def blocker_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "BLOCKER")

    @property
    def major_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "MAJOR")

    @property
    def minor_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "MINOR")

    @property
    def nit_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "NIT")

    def to_dict(self) -> dict:
        return {
            "summary": {
                "blocker": self.blocker_count,
                "major": self.major_count,
                "minor": self.minor_count,
                "nit": self.nit_count,
                "gate_decision": self.result,
            },
            "result": self.result,
            "change_types": self.change_types,
            "violations": [v.to_dict() for v in self.violations],
            "skipped_rules": [s.to_dict() for s in self.skipped_rules],
            "rejected_ignores": [r.to_dict() for r in self.rejected_ignores],
            "gate": self.gate.to_dict(),
        }
