"""Independent-evaluation statistics (design W10 section 14). Pure functions.

Units are case × rule obligations; PR-level action metrics are separate. U,
skip and error outcomes stay in every denominator they belong to and are also
counted on their own. Labels carry their source (``human`` or ``llm-proxy``)
and metrics are never pooled across sources: an LLM proxy review is review
material, not a blind human ground truth.
"""
from collections import Counter
from hashlib import sha256
import math

DECISIONS = ('satisfied', 'violated', 'undetermined', 'not-applicable', 'waived', 'error', 'skipped')
LABELS = ('satisfied', 'violated', 'not-applicable', 'undecidable')
LABEL_SOURCES = ('human', 'llm-proxy')


def assign_split(families, *, seed, holdout_fraction):
    """Whole source families go to one split; deterministic from the seed, never per case."""
    if not 0 < holdout_fraction < 1:
        raise ValueError('holdout_fraction must be between 0 and 1')
    ranked = sorted(set(families), key=lambda family: sha256(f'{seed}\0{family}'.encode()).hexdigest())
    count = max(1, round(len(ranked) * holdout_fraction)) if ranked else 0
    holdout = set(ranked[:count])
    return {family: ('holdout' if family in holdout else 'development') for family in sorted(set(families))}


def wilson(successes, total, z=1.959963984540054):
    """95% Wilson score interval; (None, None) when the denominator is zero."""
    if total == 0:
        return None, None
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4)


def proportion(successes, total):
    low, high = wilson(successes, total)
    return {'numerator': successes, 'denominator': total,
            'value': round(successes / total, 4) if total else None, 'wilson95': [low, high]}


def cohen_kappa(pairs):
    """Agreement of two reviewers over the same items; None when undefined."""
    pairs = list(pairs)
    if not pairs:
        return None
    observed = sum(a == b for a, b in pairs) / len(pairs)
    left, right = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(left[label] * right[label] for label in set(left) | set(right)) / (len(pairs) ** 2)
    if expected == 1:
        return None
    return round((observed - expected) / (1 - expected), 4)


def score(units, labels, *, label_source):
    """Metrics for one label source. ``units``: [{unit_id, case_id, decision, verification, expected_support}]."""
    if label_source not in LABEL_SOURCES:
        raise ValueError('unknown label source')
    by_id = {label['unit_id']: label for label in labels if label['source'] == label_source}
    rows = [(unit, by_id.get(unit['unit_id'])) for unit in units]
    labelled = [(u, l) for u, l in rows if l is not None]
    unlabelled = [u['unit_id'] for u, l in rows if l is None]
    decided = [(u, l) for u, l in labelled if u['decision'] in {'satisfied', 'violated'}]
    engine_violated = [(u, l) for u, l in labelled if u['decision'] == 'violated']
    label_violated = [(u, l) for u, l in labelled if l['label'] == 'violated']
    tp = sum(l['label'] == 'violated' for _, l in engine_violated)
    verified = [(u, l) for u, l in decided if u['verification'] == 'verified']
    false_verified = sum((u['decision'] == 'satisfied' and l['label'] == 'violated')
                         or (u['decision'] == 'violated' and l['label'] == 'satisfied') for u, l in verified)
    unsupported = [(u, l) for u, l in labelled if u.get('expected_support') == 'unsupported']
    appropriate_hold = sum(u['decision'] == 'undetermined' for u, _ in unsupported)
    known = [(u, l) for u, l in label_violated if u.get('known_violation')]
    retained = sum(u['decision'] == 'violated' for u, _ in known)
    outcome_counts = Counter(u['decision'] for u, _ in labelled)
    return {'label_source': label_source, 'units_total': len(units), 'units_labelled': len(labelled),
            'units_unlabelled': unlabelled,
            'engine_outcomes_in_denominator': dict(sorted(outcome_counts.items())),
            'confirmed_violation_precision': proportion(tp, len(engine_violated)),
            'confirmed_violation_recall': proportion(tp, len(label_violated)),
            'recall_misses_by_engine_outcome': dict(sorted(Counter(
                u['decision'] for u, l in label_violated if u['decision'] != 'violated').items())),
            'verified_coverage': proportion(len(verified), len(labelled)),
            'false_verified': proportion(false_verified, len(verified)),
            'appropriate_unsupported_hold': proportion(appropriate_hold, len(unsupported)),
            'known_violation_retained': proportion(retained, len(known)),
            'note': 'appropriate-unsupported-hold is not coverage; U/skip/error stay in denominators'}


def pr_action_metrics(cases, labels, *, label_source):
    """PR-level false block: engine fail where the labelled gate action is pass/warn."""
    by_case = {l['case_id']: l for l in labels if l['source'] == label_source and l.get('kind') == 'pr-action'}
    rows = [(case, by_case.get(case['case_id'])) for case in cases]
    labelled = [(c, l) for c, l in rows if l is not None]
    allowed = [(c, l) for c, l in labelled if l['label'] in {'pass', 'warn'}]
    false_block = sum(c['gate'] == 'fail' for c, _ in allowed)
    should_block = [(c, l) for c, l in labelled if l['label'] == 'fail']
    missed = sum(c['gate'] != 'fail' for c, _ in should_block)
    return {'label_source': label_source, 'prs_labelled': len(labelled),
            'false_block': proportion(false_block, len(allowed)),
            'missed_block': proportion(missed, len(should_block)),
            'engine_errors': sum(c['gate'] == 'error' for c, _ in labelled)}
