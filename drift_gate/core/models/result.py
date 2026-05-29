from dataclasses import dataclass, field
from typing import List, Optional

from .changed_file import ChangedFile
from .policy import Gate


# Pricing constants (source: https://www.anthropic.com/pricing, checked 2026-05-21)
# All prices are per million tokens (USD).
MODEL_PRICING: dict = {
    "claude-opus-4-6": {
        "input": 15.0,
        "output": 75.0,
        "cache_write": 18.75,   # cache creation (1.25x input)
        "cache_read": 1.50,     # cache read (0.10x input)
    },
    "claude-sonnet-4-6": {
        "input": 3.0,
        "output": 15.0,
        "cache_write": 3.75,
        "cache_read": 0.30,
    },
    "claude-haiku-4-5": {
        "input": 0.80,
        "output": 4.0,
        "cache_write": 1.0,
        "cache_read": 0.08,
    },
}
# Fallback pricing used when model is not in MODEL_PRICING
_DEFAULT_PRICING = MODEL_PRICING["claude-opus-4-6"]


@dataclass
class EnrichmentMetrics:
    """Token usage and estimated cost metrics from a Claude API call."""

    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def estimated_uncached_input_tokens(self) -> int:
        """Total input tokens that would have been billed without caching."""
        return self.input_tokens + self.cache_read_input_tokens

    @property
    def saved_input_tokens(self) -> int:
        """Tokens served from cache (billed at 10% rate)."""
        return self.cache_read_input_tokens

    @property
    def estimated_savings_pct(self) -> float:
        """Estimated percentage of input cost saved by prompt caching."""
        total = self.estimated_uncached_input_tokens
        if total == 0:
            return 0.0
        saved = self.cache_read_input_tokens
        # Cache reads cost 10% of normal input price, so savings = 90% of cache_read cost
        return round(saved * 0.9 / total * 100, 1)

    def estimated_cost_usd(self) -> dict:
        """Return per-component and total estimated cost in USD."""
        pricing = MODEL_PRICING.get(self.model, _DEFAULT_PRICING)
        per_m = 1_000_000
        input_cost = self.input_tokens * pricing["input"] / per_m
        output_cost = self.output_tokens * pricing["output"] / per_m
        cache_write_cost = self.cache_creation_input_tokens * pricing["cache_write"] / per_m
        cache_read_cost = self.cache_read_input_tokens * pricing["cache_read"] / per_m
        total = input_cost + output_cost + cache_write_cost + cache_read_cost
        # Uncached equivalent (what you'd pay without caching)
        uncached_input_cost = self.estimated_uncached_input_tokens * pricing["input"] / per_m
        uncached_total = uncached_input_cost + output_cost
        return {
            "input_usd": round(input_cost, 6),
            "output_usd": round(output_cost, 6),
            "cache_write_usd": round(cache_write_cost, 6),
            "cache_read_usd": round(cache_read_cost, 6),
            "total_usd": round(total, 6),
            "uncached_total_usd": round(uncached_total, 6),
            "saved_usd": round(uncached_total - total, 6),
        }

    def to_dict(self) -> dict:
        cost = self.estimated_cost_usd()
        return {
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "estimated_uncached_input_tokens": self.estimated_uncached_input_tokens,
            "saved_input_tokens": self.saved_input_tokens,
            "estimated_savings_pct": self.estimated_savings_pct,
            "estimated_cost": cost,
        }

    def format_report(self) -> str:
        """Return a human-readable token efficiency report."""
        lines = [
            "Claude token efficiency",
            f"  model: {self.model}",
            f"  input_tokens: {self.input_tokens}",
            f"  output_tokens: {self.output_tokens}",
            f"  cache_creation_input_tokens: {self.cache_creation_input_tokens}",
            f"  cache_read_input_tokens: {self.cache_read_input_tokens}",
            f"  estimated_uncached_input_tokens: {self.estimated_uncached_input_tokens}",
            f"  saved_input_tokens: {self.saved_input_tokens}",
            f"  estimated_savings: {self.estimated_savings_pct}%",
        ]
        cost = self.estimated_cost_usd()
        lines.append(f"  estimated_cost_usd: ${cost['total_usd']:.6f}")
        lines.append(f"  estimated_saved_usd: ${cost['saved_usd']:.6f}")
        return "\n".join(lines)

    @classmethod
    def from_text_estimate(cls, prompt_text: str, model: str = "") -> "EnrichmentMetrics":
        """Estimate token usage from raw text without making an API call.

        Uses a conservative 4-chars-per-token approximation.  The system prompt
        (~200 tokens fixed) is added to the prompt estimate.  On a warm cache the
        system prompt portion is served from cache, so cache_read is set to the
        system-prompt estimate and input_tokens to the remainder.

        This is an *estimate only* — actual token counts depend on the model tokeniser.
        """
        _CHARS_PER_TOKEN = 4
        _SYSTEM_PROMPT_TOKENS = 200  # conservative fixed estimate

        user_tokens = max(1, len(prompt_text) // _CHARS_PER_TOKEN)
        # Assume warm cache: system prompt is a cache hit, user message is fresh input
        return cls(
            model=model,
            input_tokens=user_tokens,
            output_tokens=0,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=_SYSTEM_PROMPT_TOKENS,
        )


@dataclass
class DriftIgnoreDirective:
    rule_id: str
    reason: Optional[str] = None
    expires: Optional[str] = None
    approved_by: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "DriftIgnoreDirective":
        return cls(
            rule_id=d["rule_id"],
            reason=d.get("reason"),
            expires=d.get("expires"),
            approved_by=d.get("approved_by"),
        )

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "reason": self.reason,
            "expires": self.expires,
            "approved_by": self.approved_by,
        }


@dataclass
class UnsatisfiedGroup:
    name: str
    required: List[str]
    type: str  # any_changed | all_changed

    def to_dict(self) -> dict:
        return {"name": self.name, "required": self.required, "type": self.type}


@dataclass
class SatisfiedGroup:
    name: str
    required: List[str]
    type: str  # any_changed | all_changed

    def to_dict(self) -> dict:
        return {"name": self.name, "required": self.required, "type": self.type}


@dataclass
class RuleDecision:
    rule_id: str
    severity: str
    status: str  # pass | fail | skipped | rejected-ignore | unmatched
    reason: str
    matched_patterns: List[str] = field(default_factory=list)
    trigger_files: List[str] = field(default_factory=list)
    satisfied_groups: List[SatisfiedGroup] = field(default_factory=list)
    unsatisfied_groups: List[UnsatisfiedGroup] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "status": self.status,
            "reason": self.reason,
            "matched_patterns": self.matched_patterns,
            "trigger_files": self.trigger_files,
            "satisfied_groups": [g.to_dict() for g in self.satisfied_groups],
            "unsatisfied_groups": [g.to_dict() for g in self.unsatisfied_groups],
        }


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
    change_intensity: str = "unknown"
    change_intensities: List[str] = field(default_factory=list)
    trigger_patterns: List[str] = field(default_factory=list)
    blast_radius: List[str] = field(default_factory=list)
    satisfied_groups: List[SatisfiedGroup] = field(default_factory=list)
    cross_file_relations: List[str] = field(default_factory=list)
    missing_docs_explanation: str = ""
    changed_contract_summary: str = ""
    docs_update_draft: str = ""
    false_positive_note: str = ""

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "confidence": self.confidence,
            "change_types": self.change_types,
            "change_type": self.change_type,
            "message": self.message,
            "trigger_files": [f.to_dict() for f in self.trigger_files],
            "satisfied_groups": [g.to_dict() for g in self.satisfied_groups],
            "unsatisfied_groups": [g.to_dict() for g in self.unsatisfied_groups],
            "checklist": self.checklist,
            "ignored": self.ignored,
            "change_intensity": self.change_intensity,
            "change_intensities": self.change_intensities,
            "trigger_patterns": self.trigger_patterns,
            "blast_radius": self.blast_radius,
            "missing_docs_explanation": self.missing_docs_explanation,
            "changed_contract_summary": self.changed_contract_summary,
            "docs_update_draft": self.docs_update_draft,
            "false_positive_note": self.false_positive_note,
            "cross_file_relations": self.cross_file_relations,
        }


@dataclass
class TemporalWarning:
    rule_id: str
    ignored_count: int
    threshold: int
    severity: str
    message: str

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "ignored_count": self.ignored_count,
            "threshold": self.threshold,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass
class ScanMetrics:
    scanned_files: int = 0
    skipped_ignored_files: int = 0
    skipped_binary_files: int = 0
    skipped_large_files: int = 0
    evaluated_rules: int = 0
    runtime_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "scanned_files": self.scanned_files,
            "skipped_ignored_files": self.skipped_ignored_files,
            "skipped_binary_files": self.skipped_binary_files,
            "skipped_large_files": self.skipped_large_files,
            "evaluated_rules": self.evaluated_rules,
            "runtime_seconds": self.runtime_seconds,
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
    reason: str = "reason is required"

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "message": self.message,
            "reason": self.reason,
        }


@dataclass
class IgnoreAuditEntry:
    rule_id: str
    action: str  # accepted | rejected
    reason: str
    approved_by: Optional[str] = None
    expires: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "action": self.action,
            "reason": self.reason,
            "approved_by": self.approved_by,
            "expires": self.expires,
        }


@dataclass
class EvaluationResult:
    change_types: List[str]
    violations: List[Violation]
    skipped_rules: List[SkippedRule]
    rejected_ignores: List[RejectedIgnore]
    gate: Gate
    rule_decisions: List[RuleDecision] = field(default_factory=list)
    ignore_audit: List[IgnoreAuditEntry] = field(default_factory=list)
    temporal_warnings: List[TemporalWarning] = field(default_factory=list)
    scan_metrics: ScanMetrics = field(default_factory=ScanMetrics)
    enrichment_metrics: Optional[EnrichmentMetrics] = None
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
        d = {
            "summary": {
                "blocker": self.blocker_count,
                "major": self.major_count,
                "minor": self.minor_count,
                "nit": self.nit_count,
                "gate_decision": self.result,
            },
            "scan_metrics": self.scan_metrics.to_dict(),
            "result": self.result,
            "change_types": self.change_types,
            "violations": [v.to_dict() for v in self.violations],
            "rule_decisions": [d.to_dict() for d in self.rule_decisions],
            "skipped_rules": [s.to_dict() for s in self.skipped_rules],
            "rejected_ignores": [r.to_dict() for r in self.rejected_ignores],
            "ignore_audit": [entry.to_dict() for entry in self.ignore_audit],
            "temporal_warnings": [
                warning.to_dict() for warning in self.temporal_warnings
            ],
            "gate": self.gate.to_dict(),
        }
        if self.enrichment_metrics is not None:
            d["enrichment_metrics"] = self.enrichment_metrics.to_dict()
        return d
