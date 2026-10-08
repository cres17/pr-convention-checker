"""Typed triggers: change family, predicate, magnitude and unknown handling (design W13).

The legacy ``min_change_intensity`` puts every change on one order. A typed
trigger instead names a family and predicate, counts changed identities as the
magnitude, and returns T/F/U. U is never collapsed into F: ``on_unknown``
decides explicitly whether it reviews (conditional A=U), triggers, or is ignored
with an audit note. Severity stays on the rule (enforcement), not the trigger.
"""
from dataclasses import dataclass

from drift_gate.core.contracts.planner import Truth

PREDICATES = {
    'api-route': ('route-added', 'route-removed', 'route-changed'),
    'api-response': ('response-shape-changed',),
    'env-key': ('key-added',),
    'paths': ('path-changed',),
}
ON_UNKNOWN = ('review', 'trigger', 'ignore-with-audit')
SCOPES = ('selected-modules',)
# Legacy intensity -> nearest typed trigger, used only by the migration report.
LEGACY_MAP = {
    'route-contract-change': ('api-route', 'route-changed'),
    'config-key-added': ('env-key', 'key-added'),
}


def validate_trigger(trigger):
    errors = []
    if trigger.family not in PREDICATES:
        errors.append(f"unknown trigger family '{trigger.family}'")
    elif trigger.predicate not in PREDICATES[trigger.family]:
        errors.append(f"trigger predicate '{trigger.predicate}' is not defined for {trigger.family}")
    if trigger.on_unknown not in ON_UNKNOWN:
        errors.append(f"trigger on_unknown must be one of {', '.join(ON_UNKNOWN)}")
    if trigger.scope not in SCOPES:
        errors.append(f"trigger scope '{trigger.scope}' is not supported (selected-modules only)")
    if type(trigger.min_magnitude) is not int or trigger.min_magnitude < 1:
        errors.append('trigger min_magnitude must be a positive integer')
    return errors


@dataclass(frozen=True)
class TriggerOutcome:
    truth: Truth
    magnitude_lower: int
    magnitude_upper: int | None   # None: unbounded
    reasons: tuple

    def to_dict(self):
        return {'truth': self.truth.value, 'magnitude': [self.magnitude_lower, self.magnitude_upper],
                'reasons': list(self.reasons)}


def _threshold(lower, upper, minimum, reasons):
    if lower >= minimum:
        return TriggerOutcome(Truth.TRUE, lower, upper, tuple(reasons))
    if upper is not None and upper < minimum:
        return TriggerOutcome(Truth.FALSE, lower, upper, tuple(reasons))
    return TriggerOutcome(Truth.UNKNOWN, lower, upper, tuple(reasons) or ('magnitude-open',))


def evaluate_trigger(trigger, files, session=None):
    """Truth of the typed predicate over the rule's path-matched files."""
    from drift_gate.core.contracts.delta import compare_facts
    from drift_gate.core.evaluation.membership import delta_bounds
    from drift_gate.core.evaluation.routes import analyze_route_facts
    files = tuple(files)
    if not files:
        return TriggerOutcome(Truth.FALSE, 0, 0, ('no-path-match',))
    if trigger.family == 'paths':
        return _threshold(len(files), len(files), trigger.min_magnitude, ())
    if trigger.family == 'api-route':
        pair = analyze_route_facts(files, session)
        added, removed = delta_bounds(compare_facts(pair.before, pair.after))
        parts = {'route-added': (added,), 'route-removed': (removed,), 'route-changed': (added, removed)}[trigger.predicate]
        lower = sum(len(b.lower) for b in parts)
        upper = None if any(b.upper is None for b in parts) else sum(len(b.upper) for b in parts)
        return _threshold(lower, upper, trigger.min_magnitude, (pair.diagnostic,) if pair.diagnostic else ())
    if trigger.family == 'env-key':
        from drift_gate.core.evaluation.environment import environment_delta
        facts = environment_delta(files)
        return _threshold(len(facts.keys), None if facts.uncertain else len(facts.keys), trigger.min_magnitude,
                          ('binding-uncertain',) if facts.uncertain else ())
    from drift_gate.core.evaluation.api_schema import UnknownResponse, UnsupportedContract, response_changes
    try:
        changes = response_changes([f for f in files if f.path.endswith('.py')], session)
    except UnsupportedContract as exc:
        return TriggerOutcome(Truth.UNKNOWN, 0, None, (str(exc),))
    known = sum(not isinstance(shape, UnknownResponse) for shape in changes.values())
    unknown = len(changes) - known
    return _threshold(known, None if unknown else known, trigger.min_magnitude, ('response-shape-open',) if unknown else ())


def resolve_unknown(outcome, on_unknown):
    """Map U per policy: review keeps A=U, trigger treats as T, ignore-with-audit as F (audited)."""
    if outcome.truth != Truth.UNKNOWN:
        return outcome.truth, ''
    if on_unknown == 'trigger':
        return Truth.TRUE, 'typed trigger unknown; policy treats unknown as triggered'
    if on_unknown == 'ignore-with-audit':
        return Truth.FALSE, 'typed trigger unknown; policy ignores unknown (audited)'
    return Truth.UNKNOWN, 'typed trigger unknown; applicability left open for review'


def legacy_comparison(rule, files, legacy_matched, session=None):
    """Shadow row comparing a legacy intensity filter with its nearest typed trigger."""
    from drift_gate.core.models.policy import Trigger
    mapped = LEGACY_MAP.get(rule.when.min_change_intensity)
    if mapped is None:
        return {'rule_id': rule.id, 'legacy_intensity': rule.when.min_change_intensity, 'mapped_trigger': None,
                'classification': 'no-typed-equivalent'}
    outcome = evaluate_trigger(Trigger(*mapped), files, session)
    typed = outcome.truth
    legacy = Truth.TRUE if legacy_matched else Truth.FALSE
    classification = ('equal' if typed == legacy else 'typed-unknown' if typed == Truth.UNKNOWN
                      else 'typed-triggers-more' if typed == Truth.TRUE else 'typed-triggers-less')
    return {'rule_id': rule.id, 'legacy_intensity': rule.when.min_change_intensity,
            'mapped_trigger': {'family': mapped[0], 'predicate': mapped[1]}, 'legacy': legacy.value,
            'typed': outcome.to_dict(), 'classification': classification}
