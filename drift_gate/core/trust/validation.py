"""TrustedValidation vs CandidateTests (design W09).

The merge basis is the verdict of an engine pinned outside the candidate,
evaluated with a separately pinned policy on the candidate's immutable bytes.
The candidate's own engine result is a shadow: it can make a review necessary,
never sufficient. A candidate that changes the checker, policy or workflow is
flagged so its own pass cannot be read as approval of that change.
"""
from dataclasses import dataclass

from drift_gate.utils.glob_matcher import matches_any

TRUST_SENSITIVE = ('drift_gate/**', '.drift-gate*.yml', '.drift-gate*.yaml', '.github/workflows/**',
                   'action.yml', 'action.yaml', 'packaging/**', 'pyproject.toml', 'setup.py', 'setup.cfg',
                   'scripts/check_self.py', 'requirements*.txt')
GATE_RESULTS = ('pass', 'warn', 'fail')


@dataclass(frozen=True)
class EngineRun:
    """One engine's verdict on the same subject; produced by an adapter."""
    role: str               # trusted | candidate
    gate_result: str | None  # None: the engine did not complete
    engine_ref: str
    attested: bool
    error: str = ''

    def __post_init__(self):
        if self.role not in {'trusted', 'candidate'}:
            raise ValueError('role must be trusted or candidate')
        if self.gate_result is not None and self.gate_result not in GATE_RESULTS:
            raise ValueError('invalid gate result')
        if type(self.attested) is not bool or not isinstance(self.engine_ref, str):
            raise ValueError('invalid engine identity')
        if self.gate_result is None and not self.error:
            raise ValueError('an incomplete run requires an error')


@dataclass(frozen=True)
class TrustDecision:
    action: str           # allow | review | block
    merge_basis: str      # trusted-engine | none
    reasons: tuple[str, ...]
    trust_sensitive_paths: tuple[str, ...]

    def to_dict(self):
        return {'schema': 'trusted-validation-decision-v1', 'action': self.action, 'merge_basis': self.merge_basis,
                'reasons': list(self.reasons), 'trust_sensitive_paths': list(self.trust_sensitive_paths),
                'candidate_pass_is_not_merge_basis': True}


def trust_sensitive_paths(changed_paths):
    return tuple(sorted({path for path in changed_paths if matches_any(path, list(TRUST_SENSITIVE))}))


def decide(trusted, candidate, changed_paths, *, subject_mismatches=()):
    """Combine a trusted run and a candidate shadow run into an action.

    ``subject_mismatches`` lists identity fields (commits, policy, comparison, evaluation
    context, input digest) on which the two runs disagree. A verdict about a different
    subject is never a merge basis for this one.
    """
    if not isinstance(trusted, EngineRun) or trusted.role != 'trusted':
        raise ValueError('expected the trusted engine run')
    if candidate is not None and (not isinstance(candidate, EngineRun) or candidate.role != 'candidate'):
        raise ValueError('expected the candidate engine run')
    sensitive = trust_sensitive_paths(changed_paths)
    reasons = []
    if subject_mismatches:
        reasons.extend(f'trusted-subject-mismatch:{field}' for field in subject_mismatches)
        return TrustDecision('review', 'none', tuple(reasons), sensitive)
    if trusted.gate_result is None or not trusted.attested:
        reasons.append('trusted-engine-unavailable' if trusted.gate_result is None else 'trusted-engine-unattested')
        # Without an independent verdict nothing, including a candidate pass, is a merge basis.
        return TrustDecision('review', 'none', tuple(reasons), sensitive)
    action = {'pass': 'allow', 'warn': 'allow', 'fail': 'block'}[trusted.gate_result]
    if candidate is None or candidate.gate_result is None:
        reasons.append('candidate-shadow-unavailable')
    elif candidate.gate_result != trusted.gate_result:
        stricter = GATE_RESULTS.index(candidate.gate_result) > GATE_RESULTS.index(trusted.gate_result)
        reasons.append('candidate-engine-stricter' if stricter else 'candidate-engine-weaker')
        if action == 'allow':
            # A difference needs a reviewed explanation; it is neither auto-fail nor auto-waived.
            action = 'review'
    if sensitive:
        reasons.append('candidate-changes-checker-policy-or-workflow')
        if action == 'allow':
            action = 'review'
    return TrustDecision(action, 'trusted-engine', tuple(reasons), sensitive)
