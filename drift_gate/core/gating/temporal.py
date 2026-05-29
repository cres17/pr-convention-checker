"""Temporal gate helpers — pure functions, no history I/O."""
from drift_gate.core.models.result import EvaluationResult, TemporalWarning


def apply_temporal_gate(
    result: EvaluationResult,
    ignored_rule_counts: dict[str, int],
    *,
    threshold: int = 3,
) -> EvaluationResult:
    """Attach warnings when the same rule is repeatedly drift-ignored.

    History loading stays in adapters.  This helper only consumes an already
    aggregated rule -> ignored-count mapping so the gate remains deterministic.
    """
    if threshold <= 0:
        return result

    warnings = []
    for rule_id, count in sorted(ignored_rule_counts.items()):
        if count < threshold:
            continue
        warnings.append(TemporalWarning(
            rule_id=rule_id,
            ignored_count=count,
            threshold=threshold,
            severity="MAJOR",
            message=(
                f"rule '{rule_id}' was drift-ignored {count} time(s), "
                f"meeting the temporal threshold of {threshold}"
            ),
        ))

    result.temporal_warnings = warnings
    if warnings and result.result == "pass" and not result.skip and not result.no_policy:
        result.result = "warn"
    return result
