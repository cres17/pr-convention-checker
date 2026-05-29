from dataclasses import dataclass, field
from typing import List


@dataclass
class Group:
    name: str
    any_changed: List[str] = field(default_factory=list)
    all_changed: List[str] = field(default_factory=list)
    required: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "Group":
        return cls(
            name=d.get("name", ""),
            any_changed=d.get("any_changed", []),
            all_changed=d.get("all_changed", []),
            required=d.get("required", True),
        )


@dataclass
class CrossFileRelation:
    name: str
    when_any_changed: List[str] = field(default_factory=list)
    require_groups: List[str] = field(default_factory=list)
    message: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "CrossFileRelation":
        return cls(
            name=d.get("name", ""),
            when_any_changed=d.get("when_any_changed", []),
            require_groups=d.get("require_groups", []),
            message=d.get("message", ""),
        )


@dataclass
class Require:
    groups: List[Group] = field(default_factory=list)
    cross_file: List[CrossFileRelation] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Require":
        return cls(
            groups=[Group.from_dict(g) for g in d.get("groups", [])],
            cross_file=[
                CrossFileRelation.from_dict(r)
                for r in d.get("cross_file", [])
            ],
        )


@dataclass
class When:
    any_changed: List[str] = field(default_factory=list)
    min_change_intensity: str = "any"

    @classmethod
    def from_dict(cls, d: dict) -> "When":
        return cls(
            any_changed=d.get("any_changed", []),
            min_change_intensity=d.get("min_change_intensity", "any"),
        )


@dataclass
class Rule:
    id: str
    when: When
    require: Require
    severity: str  # blocker | major | minor | nit
    message: str = ""
    allow_ignore: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "Rule":
        return cls(
            id=d["id"],
            when=When.from_dict(d.get("when") or {}),
            require=Require.from_dict(d.get("require") or {}),
            severity=d.get("severity", "minor").lower(),
            message=d.get("message", ""),
            allow_ignore=d.get("allow_ignore", True),
        )


@dataclass
class SuppressionPolicy:
    allow_ignores: bool = True
    require_codeowners_approval: bool = False
    allowed_rules: List[str] = field(default_factory=list)
    repeated_ignore_threshold: int = 3

    @classmethod
    def from_dict(cls, d: dict) -> "SuppressionPolicy":
        return cls(
            allow_ignores=d.get("allow_ignores", True),
            require_codeowners_approval=d.get("require_codeowners_approval", False),
            allowed_rules=d.get("allowed_rules", []),
            repeated_ignore_threshold=d.get("repeated_ignore_threshold", 3),
        )

    def to_dict(self) -> dict:
        return {
            "allow_ignores": self.allow_ignores,
            "require_codeowners_approval": self.require_codeowners_approval,
            "allowed_rules": self.allowed_rules,
            "repeated_ignore_threshold": self.repeated_ignore_threshold,
        }


@dataclass
class EnrichmentPolicy:
    provider: str = ""
    mode: str = "comment-only"

    @property
    def enabled(self) -> bool:
        return bool(self.provider)

    @classmethod
    def from_dict(cls, d: dict) -> "EnrichmentPolicy":
        return cls(
            provider=d.get("provider", ""),
            mode=d.get("mode", "comment-only"),
        )

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "mode": self.mode,
        }


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
    suppression: SuppressionPolicy = field(default_factory=SuppressionPolicy)
    enrichment: EnrichmentPolicy = field(default_factory=EnrichmentPolicy)
    # Populated by load_policy() — callers (adapters) should print/log these.
    # core never writes to stdout/stderr.
    load_warnings: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Policy":
        return cls(
            rules=[Rule.from_dict(r) for r in d.get("rules", [])],
            gate=Gate.from_dict(d.get("gate") or {}),
            ignore_paths=d.get("ignore_paths", []),
            suppression=SuppressionPolicy.from_dict(d.get("suppression") or {}),
            enrichment=EnrichmentPolicy.from_dict(d.get("enrichment") or {}),
        )
