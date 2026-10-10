"""Content evidence is independent of the final policy gate (no I/O)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ContentCheck:
    decision: str  # satisfied | violated | undetermined | paths
    verification: str  # verified | partial | unverified | not-applicable
    reason: str
    mode: str


def unknown(reason, mode):
    return ContentCheck("undetermined", "unverified", reason, mode)


def checked(ok, reason, mode):
    return ContentCheck("satisfied" if ok else "violated", "verified", reason, mode)


def combine(checks, *, require_all, mode):
    """Strong Kleene logic with order-independent, composable evidence coverage.

    A verified witness proves a disjunction. A failed conjunction retains its
    unknown siblings; wrapping that partial result in a disjunction must not
    silently upgrade it to fully verified.
    """
    checks = list(checks)
    if not checks:
        return checked(require_all, "No applicable alternatives", mode)
    decisive = "violated" if require_all else "satisfied"
    witnesses = [c for c in checks if c.decision == decisive]
    decision = decisive if witnesses else (
        "undetermined" if any(c.decision == "undetermined" for c in checks)
        else "satisfied" if require_all else "violated")
    relevant = checks
    if not require_all and witnesses:
        # Unused alternatives do not weaken a complete positive witness.
        complete = [c for c in witnesses if c.verification == "verified"]
        relevant = complete or witnesses
    if decision == "undetermined":
        verification = "unverified"
    elif any(c.verification in {"partial", "unverified"} for c in relevant):
        verification = "partial"
    elif all(c.verification == "not-applicable" for c in relevant):
        verification = "not-applicable"
    else:
        verification = "verified"
    reason = "; ".join(sorted({c.reason for c in relevant if c.reason}))
    return ContentCheck(decision, verification, reason, mode)
