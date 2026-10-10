"""Shadow comparison reports before switching a policy to a newer decision model.

Both reports evaluate one immutable snapshot twice (legacy and new model) and
classify the difference per rule/group. They never change the gate.
"""
from drift_gate.adapters.ast.analyzer import enrich_semantic_signals
from drift_gate.adapters.ast.express_routes import attach_express_routes
from drift_gate.core.change_paths import is_ignored, triggers


def _inputs(snapshot):
    data = snapshot.materialize()
    files = enrich_semantic_signals(attach_express_routes(data['changed_files']))
    return data['policy'], files


def proof_gate_report(snapshot):
    from drift_gate.core.evaluation.analysis_session import AnalysisSession
    from drift_gate.core.evaluation.contracts import content_requirement
    from drift_gate.core.evaluation.proof_gate import LEGACY_MODES, compare_decisions, contract_proof_requirement, migration_verdict
    policy, files = _inputs(snapshot)
    relevant = [f for f in files if not is_ignored(f, policy.ignore_paths)]
    rows = []
    for rule in policy.rules:
        trigger_files = [f for f in relevant if triggers(f, rule.when.any_changed)]
        for group in rule.require.groups:
            if group.content not in LEGACY_MODES or not trigger_files:
                continue
            session = AnalysisSession()
            legacy = content_requirement(group, trigger_files, relevant, session)
            proof = contract_proof_requirement(group, trigger_files, relevant, AnalysisSession())
            rows.append({'rule_id': rule.id, 'group': f'{rule.id}/{group.name}', 'legacy_mode': group.content,
                         'legacy': {'decision': legacy.decision, 'verification': legacy.verification},
                         'proof': {'decision': proof.decision, 'verification': proof.verification,
                                   'reason': proof.reason},
                         'classification': compare_decisions(legacy, proof)})
    return migration_verdict(rows)


def typed_trigger_report(snapshot):
    from drift_gate.core.classification.triggers import legacy_comparison
    from drift_gate.core.evaluation.analysis_session import AnalysisSession
    from drift_gate.core.evaluation.evaluator import _threshold_candidates
    policy, files = _inputs(snapshot)
    relevant = [f for f in files if not is_ignored(f, policy.ignore_paths)]
    rows = []
    for rule in policy.rules:
        if rule.when.min_change_intensity in (None, '', 'any'):
            continue
        trigger_files = [f for f in relevant if triggers(f, rule.when.any_changed)]
        session = AnalysisSession()
        matched, uncertain = _threshold_candidates(trigger_files, rule, session)
        row = legacy_comparison(rule, trigger_files, bool(matched), session)
        row['legacy_uncertain_paths'] = sorted(uncertain)
        rows.append(row)
    differences = [row for row in rows if row['classification'] not in {'equal', 'no-typed-equivalent'}]
    return {'schema': 'typed-trigger-migration-v1', 'rules': rows, 'differences': len(differences),
            'note': 'typed-unknown rows need an explicit on_unknown choice; they are never mapped to F'}
