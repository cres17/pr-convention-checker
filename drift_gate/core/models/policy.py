from dataclasses import dataclass, field
from typing import List


@dataclass
class Group:
    name: str
    any_changed: List[str] = field(default_factory=list)
    all_changed: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Group":
        return cls(
            name=d.get("name", ""),
            any_changed=d.get("any_changed", []),
            all_changed=d.get("all_changed", []),
        )


@dataclass
class Require:
    groups: List[Group] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Require":
        return cls(groups=[Group.from_dict(g) for g in d.get("groups", [])])


@dataclass
class When:
    any_changed: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "When":
        return cls(any_changed=d.get("any_changed", []))


@dataclass
class Rule:
    id: str
    when: When
    require: Require
    severity: str  # blocker | major | minor | nit
    message: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Rule":
        return cls(
            id=d["id"],
            when=When.from_dict(d.get("when") or {}),
            require=Require.from_dict(d.get("require") or {}),
            severity=d.get("severity", "minor").lower(),
            message=d.get("message", ""),
        )


@dataclass
class Gate:
    fail_on_blocker: bool = True
    fail_on_major_count: int = 2

    @classmethod
    def from_dict(cls, d: dict) -> "Gate":
        return cls(
            fail_on_blocker=d.get("fail_on_blocker", True),
            fail_on_major_count=d.get("fail_on_major_count", 2),
        )

    def to_dict(self) -> dict:
        return {
            "fail_on_blocker": self.fail_on_blocker,
            "fail_on_major_count": self.fail_on_major_count,
        }


@dataclass
class Policy:
    rules: List[Rule] = field(default_factory=list)
    gate: Gate = field(default_factory=Gate)
    ignore_paths: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Policy":
        return cls(
            rules=[Rule.from_dict(r) for r in d.get("rules", [])],
            gate=Gate.from_dict(d.get("gate") or {}),
            ignore_paths=d.get("ignore_paths", []),
        )
