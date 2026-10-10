"""Versioned switch from shadow proof diagnostics to a policy decision (design Migration, W08).

``gate.proof_gate: v1`` lets a group with ``content: contract-proof`` decide
through the validated proof DAG. Every supported profile found in the trigger
modules is bound to the group's document selectors (an explicit mapping, not
the legacy unmapped shadow). The projection follows design section 7:
proven T/F with closed scope -> verified, proven T/F with open scope ->
partial, U -> undetermined/unverified. The gate's existing ``on_unverified``
setting then applies; this module never turns U into a pass.

``compare_decisions`` is the compatibility check used before switching a
legacy group: it classifies, per group, how the proof decision differs.
"""
from drift_gate.core.evaluation.content_result import ContentCheck, unknown

VERSION = 'v1'
LEGACY_MODES = ('auto', 'auto-strict', 'api-routes', 'env-keys', 'api-schema')


def contract_proof_requirement(group, triggers, changed_files, session=None):
    from drift_gate.core.contracts.discovery import discover_contracts
    from drift_gate.core.contracts.planner import DocumentBinding, DocumentBindings, PlanRequest, Truth
    from drift_gate.core.evaluation.analysis_session import AnalysisSession
    from drift_gate.core.evaluation.obligations import assess_contracts, evaluate_contract_plan
    from drift_gate.core.contracts.planner import plan_contracts
    from drift_gate.core.evaluation.contract_proof import prove_contract_evaluation
    from drift_gate.utils.glob_matcher import matches_any
    triggers = tuple(triggers)
    if not triggers:
        return ContentCheck('satisfied', 'not-applicable', 'No contract-proof trigger modules', 'contract-proof')
    session = session or AnalysisSession()
    selectors = tuple(group.any_changed or group.all_changed)
    try:
        discovery = discover_contracts(triggers, session=session)
        profiles = sorted({domain.profile_ref for domain in discovery.domains if domain.profile_ref is not None})
        bindings = DocumentBindings('contract-document-bindings-v1', tuple(
            DocumentBinding(f'{group.name or "group"}:{profile[0]}', profile, selectors, bool(group.all_changed))
            for profile in profiles))
        request = PlanRequest('proof-gate-v1', group.name or 'unnamed', tuple(file.path for file in triggers), bindings)
        plan = plan_contracts(request, discovery, assess_contracts(request, discovery, triggers, session))
        documents = tuple(file for file in changed_files if matches_any(file.path, list(selectors)))
        proof = prove_contract_evaluation(evaluate_contract_plan(plan, triggers, documents, session))
    except ValueError as exc:
        return unknown(f'contract proof unavailable: {exc}', 'contract-proof')
    session.record_contract_plan(proof.evaluation)
    root = proof.root
    reason = (f'proof-gate {VERSION}: truth {root.truth.value}, decision_proven={root.decision_proven}, '
              f'scope {"closed" if root.coverage.complete else "open"}')
    if root.truth == Truth.UNKNOWN or not root.decision_proven:
        return ContentCheck('undetermined', 'unverified', reason, 'contract-proof')
    verification = 'verified' if root.coverage.complete else 'partial'
    return ContentCheck('satisfied' if root.truth == Truth.TRUE else 'violated', verification, reason, 'contract-proof')


def compare_decisions(legacy, proof):
    """Classify one group's legacy vs proof decision for a migration review."""
    order = {'violated': 2, 'undetermined': 1, 'satisfied': 0}
    if legacy.decision not in order or proof.decision not in order:
        return 'not-comparable'
    if legacy.decision == proof.decision:
        return 'equal'
    if proof.decision == 'violated':
        return 'proof-stricter'
    if legacy.decision == 'violated':
        return 'proof-weaker'          # a legacy fail would disappear: never switch automatically
    if proof.decision == 'undetermined':
        return 'proof-more-unknown'
    return 'proof-more-decided'


def migration_verdict(rows):
    """A switch is acceptable only without proof-weaker or not-comparable groups."""
    blockers = [row for row in rows if row['classification'] in {'proof-weaker', 'not-comparable'}]
    return {'schema': 'proof-gate-migration-v1', 'target_version': VERSION, 'groups': rows,
            'safe_to_switch': not blockers, 'blocking_groups': [row['group'] for row in blockers],
            'note': 'proof-stricter and proof-more-unknown rows change outcomes and need review, not silence'}
