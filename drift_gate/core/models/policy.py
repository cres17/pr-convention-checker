from dataclasses import asdict, dataclass, field
from typing import List, Optional


@dataclass
class Group:
    name: str
    any_changed: List[str] = field(default_factory=list)
    all_changed: List[str] = field(default_factory=list)
    required: bool = True
    # auto (legacy) | auto-strict | paths | api-routes | env-keys | api-schema
    # | contract-proof (needs gate.proof_gate: v1) | api-compatibility
    content: str = "auto"
    direction: str = ""  # api-compatibility: request | response | both

    @classmethod
    def from_dict(cls, d: dict) -> "Group":
        return cls(
            name=d.get("name", ""),
            any_changed=d.get("any_changed", []),
            all_changed=d.get("all_changed", []),
            required=d.get("required", True),
            content=d.get("content", "auto"),
            direction=d.get("direction", ""),
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
class Trigger:
    """Typed trigger (design W13): change family, predicate, scope and unknown handling."""
    family: str
    predicate: str
    scope: str = "selected-modules"
    on_unknown: str = "review"   # review | trigger | ignore-with-audit
    min_magnitude: int = 1

    @classmethod
    def from_dict(cls, d: dict) -> "Trigger":
        return cls(family=d.get("family", ""), predicate=d.get("predicate", ""),
                   scope=d.get("scope", "selected-modules"), on_unknown=d.get("on_unknown", "review"),
                   min_magnitude=d.get("min_magnitude", 1))


@dataclass
class When:
    any_changed: List[str] = field(default_factory=list)
    min_change_intensity: str = "any"
    trigger: Optional[Trigger] = None

    @classmethod
    def from_dict(cls, d: dict) -> "When":
        return cls(
            any_changed=d.get("any_changed", []),
            min_change_intensity=d.get("min_change_intensity", "any"),
            trigger=Trigger.from_dict(d["trigger"]) if d.get("trigger") is not None else None,
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
    on_unverified: str = "fail"
    proof_gate: str = "off"  # off | v1: contract-proof groups decide through the proof DAG

    @classmethod
    def from_dict(cls, d: dict) -> "Gate":
        return cls(
            fail_on_blocker=d.get("fail_on_blocker", True),
            fail_on_major_count=d.get("fail_on_major_count", 2),
            on_unverified=d.get("on_unverified", "fail"),
            proof_gate=d.get("proof_gate", "off"),
        )

    def to_dict(self) -> dict:
        data = {
            "fail_on_blocker": self.fail_on_blocker,
            "fail_on_major_count": self.fail_on_major_count,
            "on_unverified": self.on_unverified,
        }
        if self.proof_gate != "off":
            data["proof_gate"] = self.proof_gate
        return data


@dataclass
class ServiceSpec:
    """A declared service: module globs and its entrypoint modules (design W11)."""
    id: str
    paths: List[str] = field(default_factory=list)
    entrypoints: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "ServiceSpec":
        return cls(id=d.get("id", ""), paths=d.get("paths", []), entrypoints=d.get("entrypoints", []))


@dataclass
class Budget:
    """Whole-inspection resource limits (design W12). None leaves a limit at its default."""
    max_files: Optional[int] = None
    max_total_bytes: Optional[int] = None
    max_git_calls: Optional[int] = None
    max_wall_seconds: Optional[int] = None
    max_graph_edges: Optional[int] = None
    max_report_bytes: Optional[int] = None
    max_memory_bytes: Optional[int] = None

    @classmethod
    def from_dict(cls, d: dict) -> "Budget":
        return cls(**{name: d.get(name) for name in cls.__dataclass_fields__})


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
    services: List[ServiceSpec] = field(default_factory=list)
    budget: Optional[Budget] = None

    @classmethod
    def from_dict(cls, d: dict) -> "Policy":
        return cls(
            rules=[Rule.from_dict(r) for r in d.get("rules", [])],
            gate=Gate.from_dict(d.get("gate") or {}),
            ignore_paths=d.get("ignore_paths", []),
            suppression=SuppressionPolicy.from_dict(d.get("suppression") or {}),
            enrichment=EnrichmentPolicy.from_dict(d.get("enrichment") or {}),
            services=[ServiceSpec.from_dict(item) for item in d.get("services", [])],
            budget=Budget.from_dict(d["budget"]) if d.get("budget") is not None else None,
        )


def policy_identity_dict(policy):
    """asdict(policy) without fields added after inspection-snapshot-v1 while they hold defaults.

    Keeps the identity (and stored-bundle policy binding) of every policy that
    does not use the newer options unchanged.
    """
    data = asdict(policy)
    if not data.get("services"):
        data.pop("services", None)
    if data.get("budget") is None:
        data.pop("budget", None)
    if data["gate"].get("proof_gate") == "off":
        data["gate"].pop("proof_gate", None)
    for rule in data["rules"]:
        if rule["when"].get("trigger") is None:
            rule["when"].pop("trigger", None)
        for group in rule["require"]["groups"]:
            if group.get("direction") == "":
                group.pop("direction", None)
    return data
