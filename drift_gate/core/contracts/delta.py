"""Sound identity-set delta bounds; no parser, clock or I/O dependencies."""
from drift_gate.core.models.facts import (
    BoundedDelta, BoundedFacts, ExactDelta, ExactFacts,
    FactBasis, FactOutcome, UnknownDelta, UnknownFacts,
)


def compare_facts(before: FactOutcome, after: FactOutcome):
    """Compare the same scope/profile, retaining top and open reason codes.

    This over-approximates possible deltas, ignoring correlations between
    before and after. It does not certify discovery/dependency completeness.
    """
    if not isinstance(before, (ExactFacts, BoundedFacts, UnknownFacts)) or not isinstance(after, (ExactFacts, BoundedFacts, UnknownFacts)):
        raise ValueError('before/after must be typed fact outcomes')
    if before.basis.domain != after.basis.domain:
        raise ValueError('cannot compare different scopes, families or profiles')
    basis = FactBasis(*before.basis.domain, before.basis.evidence_refs + after.basis.evidence_refs)
    if isinstance(before, ExactFacts) and isinstance(after, ExactFacts):
        return ExactDelta(basis, after.facts - before.facts, before.facts - after.facts)
    added_must = after.must - before.may if before.may is not None else frozenset()
    removed_must = before.must - after.may if after.may is not None else frozenset()
    added_may = after.may - before.must if after.may is not None else None
    removed_may = before.may - after.must if before.may is not None else None
    reasons = getattr(before, 'reasons', ()) + getattr(after, 'reasons', ())
    cls = UnknownDelta if added_may is None or removed_may is None else BoundedDelta
    return cls(basis, added_must, added_may, removed_must, removed_may, reasons)
