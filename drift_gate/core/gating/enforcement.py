"""Organisation action, kept apart from the policy truth (design section 7).

``EnforcementOutcome`` is a projection of an evaluated result. It never re-decides a
rule: confirmed violations, unresolved obligations and waivers are read from the rule
decisions, and the action follows from them and the existing gate:

  block   the policy gate failed
  review  otherwise, when any rule is violated, undetermined or only partially verified
  allow   otherwise

``allow`` therefore means "no confirmed violation and nothing left unresolved by this
policy", and ``review`` on a passing gate means the gate tolerated something a person
should look at (a warn-level violation, or an unknown the policy lets through). A run
that produced no result has no enforcement outcome at all and is never ``allow``.
"""
ACTIONS = ('allow', 'review', 'block')


def enforcement_outcome(result):
    decisions = list(result.rule_decisions)
    confirmed = sorted({d.rule_id for d in decisions if d.decision == 'violated'})
    unresolved = sorted({d.rule_id for d in decisions if d.decision == 'undetermined'})
    partial = sorted({d.rule_id for d in decisions
                      if d.decision == 'satisfied' and d.verification == 'partial'})
    waived = sorted({d.rule_id for d in decisions if d.decision == 'waived'})
    if result.skip:
        action, basis = 'allow', 'evaluation-skipped:' + (result.skip_reason or 'skip')
    elif result.result == 'fail':
        action, basis = 'block', 'gate-failed'
    elif confirmed or unresolved or partial:
        action, basis = 'review', 'gate-passed-with-open-items'
    else:
        action, basis = 'allow', 'no-violation-and-nothing-unresolved'
    return {'schema': 'enforcement-outcome-v1', 'action': action, 'basis': basis, 'gate_result': result.result,
            'confirmed_violation_rule_ids': confirmed, 'unresolved_rule_ids': unresolved,
            'partially_verified_rule_ids': partial, 'waived_rule_ids': waived,
            'policy_ref': 'execution.policy_sha256',
            'semantics': 'projection of rule decisions; the policy gate is unchanged'}


def execution_outcome(status, *, publication_state=None):
    """Map an execution status (``execution.status``) to the design's four outcomes."""
    mapping = {'success': 'completed', 'input_error': 'rejected-input', 'resource_limit': 'aborted',
               'cancelled': 'aborted', 'timed_out': 'aborted', 'abandoned': 'aborted',
               'result_validation_error': 'internal-error', 'execution_error': 'internal-error',
               'internal_error': 'internal-error'}
    return {'schema': 'execution-outcome-v1', 'status': mapping.get(status, 'internal-error'),
            'source_status': status, 'publication_state': publication_state,
            'result_available': status == 'success'}
