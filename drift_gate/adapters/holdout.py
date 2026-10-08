"""Holdout evaluation workflow: split, freeze, run, blind review packets, adjudication, scoring.

Every artifact is written once (no overwrite) and later steps admit an input only
through its SHA-256, so expectations cannot be edited after results are seen.
Each artifact also records the digest of the one it was derived from
(frozen -> packet -> labels, frozen -> results), and scoring refuses labels that
were not made for the frozen input behind the results. Cases run through the
product's own inspection path (``adapters.inspection.inspect``), so evaluation
covers the same preprocessing as a real check. Review labels are self-declared
as ``human`` or ``llm-proxy``; this tool cannot verify who produced them and
keeps the two sources apart in every metric.
"""
from datetime import date
from hashlib import sha256
import json
from pathlib import Path

from drift_gate.core import evaluation_stats as stats
from drift_gate.core.models.input_manifest import canonical_bytes

CASES = 'holdout-cases-v1'
FROZEN = 'holdout-frozen-v1'
RESULTS = 'holdout-results-v1'
LABELS = 'holdout-labels-v1'
PACKET = 'holdout-review-packet-v1'
REVIEW_LABELS = {'rule': ('satisfied', 'violated', 'not-applicable', 'undecidable'),
                 'pr-action': ('pass', 'warn', 'fail')}


class HoldoutError(ValueError):
    """Malformed, unpinned or overwritten evaluation artifact."""


def artifact_sha256(data):
    """Digest of an artifact as ``write_once`` stores it (canonical JSON bytes)."""
    return sha256(canonical_bytes(data)).hexdigest()


def write_once(path, data):
    target = Path(path)
    if target.exists():
        raise HoldoutError(f'{target} exists; evaluation artifacts are never overwritten')
    raw = canonical_bytes(data)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, 'xb') as stream:
        stream.write(raw)
    return sha256(raw).hexdigest()


def read_pinned(path, expected_sha256, schema):
    raw = Path(path).read_bytes()
    if expected_sha256 is not None and sha256(raw).hexdigest() != expected_sha256:
        raise HoldoutError(f'{path} does not match its pinned SHA-256')
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get('schema') != schema:
        raise HoldoutError(f'{path} is not a {schema} file')
    return data, sha256(raw).hexdigest()


def _validate_case(case):
    for key in ('case_id', 'repository', 'source_family', 'policy', 'changed_files', 'expected'):
        if key not in case:
            raise HoldoutError(f'case is missing {key}')
    if not isinstance(case['changed_files'], list):
        raise HoldoutError(f"case {case['case_id']}: changed_files must be a list")
    for data in case['changed_files']:
        _changed_file(data)  # unknown or malformed fields are rejected before anything is frozen
    expected = case['expected']
    if expected.get('gate') not in {'pass', 'warn', 'fail'} or not isinstance(expected.get('rules'), dict):
        raise HoldoutError(f"case {case['case_id']}: expected gate and rules are required")
    for rule_id, row in expected['rules'].items():
        if row.get('decision') not in stats.DECISIONS or row.get('support') not in {'supported', 'unsupported'}:
            raise HoldoutError(f"case {case['case_id']} rule {rule_id}: invalid expected decision/support")


def split(candidates, *, seed, holdout_fraction, regression_families=()):
    cases = candidates.get('cases') or []
    for case in cases:
        _validate_case(case)
    ids = [case['case_id'] for case in cases]
    if len(ids) != len(set(ids)):
        raise HoldoutError('duplicate case ids')
    eligible = sorted({case['source_family'] for case in cases} - set(regression_families))
    assignment = stats.assign_split(eligible, seed=seed, holdout_fraction=holdout_fraction) if eligible else {}
    rows = []
    for case in cases:
        family = case['source_family']
        split_name = 'regression-overlap' if family in regression_families else assignment[family]
        rows.append({**case, 'split': split_name})
    holdout = [row for row in rows if row['split'] == 'holdout']
    development = [row for row in rows if row['split'] != 'holdout']
    overlap = {c['repository'] for c in holdout} & {c['repository'] for c in development}
    if overlap:
        raise HoldoutError(f'repository appears in both splits: {sorted(overlap)}')
    return ({'schema': CASES, 'split': 'holdout', 'seed': seed, 'holdout_fraction': holdout_fraction,
             'cases': holdout},
            {'schema': CASES, 'split': 'development', 'seed': seed, 'cases': development})


def freeze(holdout, *, protocol):
    if holdout.get('schema') != CASES or holdout.get('split') != 'holdout':
        raise HoldoutError('freeze accepts the holdout split only')
    for case in holdout['cases']:
        _validate_case(case)
    return {'schema': FROZEN, 'protocol': protocol, 'cases': holdout['cases'],
            'axes': ['decision', 'verification', 'gate', 'support'],
            'case_count': len(holdout['cases'])}


def _units(case, result):
    units = []
    by_rule = {d.rule_id: d for d in result.rule_decisions} if result is not None else {}
    status_map = {'pass': 'satisfied', 'fail': 'violated', 'rejected-ignore': 'violated',
                  'undetermined': 'undetermined', 'unmatched': 'not-applicable', 'skipped': 'waived'}
    for rule_id, expected in sorted(case['expected']['rules'].items()):
        decision = by_rule.get(rule_id)
        if result is None:
            observed, verification = 'error', 'unverified'
        elif decision is None:
            observed, verification = 'skipped', 'unverified'
        else:
            observed = status_map.get(decision.status, 'undetermined')
            groups = decision.satisfied_groups + decision.unsatisfied_groups
            levels = {g.verification for g in groups}
            verification = ('verified' if levels <= {'verified', 'not-applicable'} and groups else
                            'partial' if 'partial' in levels or ('verified' in levels) else 'unverified')
        units.append({'unit_id': f"{case['case_id']}::{rule_id}", 'case_id': case['case_id'], 'rule_id': rule_id,
                      'decision': observed, 'verification': verification,
                      'expected_decision': expected['decision'], 'expected_support': expected['support'],
                      'known_violation': bool(expected.get('known_violation'))})
    return units


def _changed_file(data):
    """Full observation including sources (the legacy from_dict drops raw sources)."""
    from dataclasses import fields
    from drift_gate.core.models.changed_file import ChangedFile
    names = {item.name for item in fields(ChangedFile)}
    unknown = set(data) - names
    if unknown:
        raise HoldoutError(f'unknown changed-file fields {sorted(unknown)}')
    values = dict(data)
    for key in ('before_routes', 'after_routes'):
        if values.get(key) is not None:
            values[key] = [tuple(route) for route in values[key]]
    return ChangedFile(**values)


def run_frozen(frozen, frozen_sha256):
    """Evaluate every frozen case through the product inspection path with the case's fixed context."""
    from drift_gate.adapters.evidence_bundle import producer_identity
    from drift_gate.adapters.inspection import inspect
    from drift_gate.core.models.evaluation_context import EvaluationContext
    from drift_gate.core.models.result import DriftIgnoreDirective
    from drift_gate.core.policy.loader import load_policy_from_dict
    if frozen.get('schema') != FROZEN:
        raise HoldoutError('run accepts a frozen holdout file only')
    if artifact_sha256(frozen) != frozen_sha256:
        raise HoldoutError('frozen input does not match the SHA-256 given for it')
    units, cases = [], []
    for case in frozen['cases']:
        error = ''
        context = EvaluationContext(date.fromisoformat(case.get('evaluated_on', '2026-01-01')))
        try:
            policy = load_policy_from_dict(case['policy'])
            ignores = [DriftIgnoreDirective.from_dict(d) for d in case.get('drift_ignores', [])]
            result = inspect(changed_files=[_changed_file(f) for f in case['changed_files']], policy=policy,
                             drift_ignores=ignores, context=context)
        except Exception as exc:  # kept as an error outcome, never dropped from denominators
            result, error = None, f'{type(exc).__name__}: {exc}'[:500]
        units.extend(_units(case, result))
        cases.append({'case_id': case['case_id'], 'gate': result.result if result else 'error',
                      'expected_gate': case['expected']['gate'], 'error': error,
                      'evaluation_context': context.to_dict(),
                      'input_sha256': result.execution.get('input_sha256') if result else None})
    return {'schema': RESULTS, 'frozen_sha256': frozen_sha256, 'protocol': frozen['protocol'],
            'inspection_path': 'drift_gate.adapters.inspection.inspect',
            'engine': producer_identity(), 'units': units, 'cases': cases}


def review_packet(frozen, *, instructions):
    """Blind items: inputs and the rule only; no engine output and no frozen expectation."""
    items = []
    for case in frozen['cases']:
        rules = {rule['id']: rule for rule in case['policy'].get('rules', [])}
        files = [{k: f.get(k) for k in ('path', 'status', 'previous_path', 'patch', 'before_source', 'after_source')}
                 for f in case['changed_files']]
        # Context the outcome depends on (evaluation date, waivers); never the expectation.
        context = {'evaluated_on': case.get('evaluated_on', '2026-01-01'),
                   'drift_ignores': case.get('drift_ignores', [])}
        for rule_id in sorted(case['expected']['rules']):
            items.append({'item_id': f"{case['case_id']}::{rule_id}", 'case_id': case['case_id'], 'kind': 'rule',
                          'rule': rules.get(rule_id), 'changed_files': files, 'context': context,
                          'allowed_labels': list(REVIEW_LABELS['rule'])})
        items.append({'item_id': f"{case['case_id']}::pr-action", 'case_id': case['case_id'], 'kind': 'pr-action',
                      'policy_gate': case['policy'].get('gate', {}), 'rules': list(rules.values()),
                      'changed_files': files, 'context': context, 'allowed_labels': list(REVIEW_LABELS['pr-action'])})
    return {'schema': PACKET, 'frozen_sha256': artifact_sha256(frozen), 'protocol': frozen['protocol'],
            'instructions': instructions, 'items': items, 'blind': ['engine-output', 'frozen-expectation']}


def adjudicate(packet, reviews, resolutions=()):
    if packet.get('schema') != PACKET or not packet.get('frozen_sha256'):
        raise HoldoutError('adjudicate needs a review packet bound to its frozen input')
    items = {item['item_id']: item for item in packet['items']}
    by_source = {source: {} for source in stats.LABEL_SOURCES}
    for row in reviews:
        if row.get('reviewer_kind') not in stats.LABEL_SOURCES:
            raise HoldoutError('reviewer_kind must be human or llm-proxy')
        item = items.get(row.get('item_id'))
        if item is None or row.get('label') not in item['allowed_labels']:
            raise HoldoutError(f"invalid review row for {row.get('item_id')}")
        by_source[row['reviewer_kind']].setdefault(row['item_id'], {})[row['reviewer_id']] = row['label']
    resolved = {}
    for row in resolutions:
        item = items.get(row.get('item_id'))
        if row.get('source') not in stats.LABEL_SOURCES or item is None or row.get('label') not in item['allowed_labels']:
            raise HoldoutError(f"invalid resolution row for {row.get('item_id')}")
        resolved[(row['item_id'], row['source'])] = row['label']
    labels, unresolved, agreement = [], [], {}
    for source, votes in by_source.items():
        reviewers = sorted({reviewer for item_votes in votes.values() for reviewer in item_votes})
        if len(reviewers) >= 2:
            first, second = reviewers[:2]
            pairs = [(v[first], v[second]) for v in votes.values() if first in v and second in v]
            agreement[source] = {'reviewers': [first, second], 'items': len(pairs), 'cohen_kappa': stats.cohen_kappa(pairs)}
        for item_id, item_votes in sorted(votes.items()):
            counts = sorted(((list(item_votes.values()).count(label), label) for label in set(item_votes.values())),
                            reverse=True)
            final = resolved.get((item_id, source))
            if final is None and len(item_votes) >= 2 and (len(counts) == 1 or counts[0][0] > counts[1][0]):
                final = counts[0][1]
            elif final is None and len(item_votes) == 1:
                final = counts[0][1]
            if final is None:
                unresolved.append({'item_id': item_id, 'source': source, 'votes': item_votes})
                continue
            item = items[item_id]
            labels.append({'unit_id': item_id, 'case_id': item['case_id'], 'kind': item['kind'], 'source': source,
                           'label': final, 'reviewers': sorted(item_votes),
                           'unanimous': len(set(item_votes.values())) == 1,
                           'resolved_by_adjudicator': (item_id, source) in resolved})
    return {'schema': LABELS, 'packet_sha256': artifact_sha256(packet), 'frozen_sha256': packet['frozen_sha256'],
            'protocol': packet['protocol'], 'labels': labels, 'unresolved': unresolved, 'agreement': agreement,
            'sources_kept_separate': True}


def score_all(results, labels):
    # The labels must be judgments of the very frozen input the results were computed from.
    if labels.get('frozen_sha256') != results.get('frozen_sha256'):
        raise HoldoutError('labels were made for a different frozen input than the results')
    if labels.get('protocol') != results.get('protocol'):
        raise HoldoutError('labels and results use different protocols')
    known = {u['unit_id'] for u in results['units']} | {f"{c['case_id']}::pr-action" for c in results['cases']}
    stray = sorted({l['unit_id'] for l in labels['labels']} - known)
    if stray:
        raise HoldoutError(f'labels name items the results do not contain: {stray[:5]}')
    units = [u for u in results['units']]
    rule_labels = [l for l in labels['labels'] if l['kind'] == 'rule']
    pr_labels = [l for l in labels['labels'] if l['kind'] == 'pr-action']
    report = {'schema': 'holdout-metrics-v1', 'frozen_sha256': results['frozen_sha256'],
              'packet_sha256': labels['packet_sha256'],
              'protocol': results['protocol'], 'engine_source_sha256': results['engine']['source_sha256'],
              'by_label_source': {}, 'unresolved_reviews': len(labels['unresolved']),
              'frozen_expectation_agreement': stats.proportion(
                  sum(u['decision'] == u['expected_decision'] for u in units), len(units))}
    for source in stats.LABEL_SOURCES:
        if not any(l['source'] == source for l in labels['labels']):
            report['by_label_source'][source] = None
            continue
        report['by_label_source'][source] = {
            'obligations': stats.score(units, rule_labels, label_source=source),
            'pr_actions': stats.pr_action_metrics(results['cases'], pr_labels, label_source=source)}
    report['independence'] = ('human labels present' if report['by_label_source']['human'] else
                              'no human labels: llm-proxy metrics are review material, not blind ground truth')
    return report
