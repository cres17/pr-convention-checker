"""Reconciling a write whose response was lost (design W15 10.3).

The provider offers no idempotent create, so a lost response is resolved only
by looking for the attempt's idempotency key. The key proves that this
attempt's write landed; whether the stored body still equals what was sent is
reported separately, because an intermediary or a later edit can alter it
(observed live: an appended footer). A failed lookup or an absent create never
proves that nothing was sent.
"""
from dataclasses import dataclass

BODY_MATCHES = ('exact', 'suffix-appended', 'different', 'unverified')


@dataclass(frozen=True)
class Reconciliation:
    state: str
    reason: str
    retry_safe: bool
    comment_id: object = None
    duplicates: int = 0
    body_match: object = None

    def to_dict(self):
        return {'state': self.state, 'reason': self.reason, 'retry_safe': self.retry_safe,
                'comment_id': self.comment_id, 'duplicates': self.duplicates, 'body_match': self.body_match,
                'content_verified': self.body_match == 'exact'}


def reconcile(*, key, operation, target_comment_id, lookup, order=None):
    """``lookup`` is None when the read failed, else [{id, key, body_match, order}].

    ``order`` is (workflow digest, run number, run attempt) of this attempt. A
    missing key next to a later order of the same workflow means the write may
    have landed and was then replaced: retrying would put an older result back.
    """
    if operation not in {'create', 'update'}:
        raise ValueError('operation must be create or update')
    if lookup is None:
        return Reconciliation('publication-unknown', 'lookup-failed', False)
    mine = [c for c in lookup if c.get('key') == key]
    if mine:
        # Prefer an exact copy; duplicates are reported, never deleted automatically.
        rank = {match: index for index, match in enumerate(BODY_MATCHES)}
        best = min(mine, key=lambda c: rank.get(c.get('body_match'), len(rank)))
        match = best.get('body_match') if best.get('body_match') in BODY_MATCHES else 'unverified'
        reason = 'idempotency-key-found' if match == 'exact' else f'idempotency-key-found-body-{match}'
        return Reconciliation('published', reason, False, best.get('id'), len(mine) - 1, match)
    if order is not None and any(
            isinstance(c.get('order'), tuple) and c['order'][0] == order[0] and c['order'][1:] > tuple(order[1:])
            for c in lookup):
        return Reconciliation('publication-stale', 'superseded-by-later-attempt', False)
    if operation == 'update':
        present = any(c.get('id') == target_comment_id for c in lookup)
        if present:
            # Replacing a known comment's body is idempotent; the write did not land.
            return Reconciliation('publication-unknown', 'update-not-applied', True, target_comment_id)
        return Reconciliation('publication-unknown', 'update-target-missing', False)
    return Reconciliation('publication-unknown', 'create-not-visible', False)
