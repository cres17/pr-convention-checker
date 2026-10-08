"""Reconciling a write whose response was lost (design W15 10.3).

The provider offers no idempotent create, so a lost response is resolved only
by looking for the attempt's idempotency key and comparing the body digest. A
failed lookup or an absent create never proves that nothing was sent.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Reconciliation:
    state: str
    reason: str
    retry_safe: bool
    comment_id: object = None
    duplicates: int = 0

    def to_dict(self):
        return {'state': self.state, 'reason': self.reason, 'retry_safe': self.retry_safe,
                'comment_id': self.comment_id, 'duplicates': self.duplicates}


def reconcile(*, key, body_sha256, operation, target_comment_id, lookup):
    """``lookup`` is None when the read failed, else [{id, key, body_sha256}]."""
    if operation not in {'create', 'update'}:
        raise ValueError('operation must be create or update')
    if lookup is None:
        return Reconciliation('publication-unknown', 'lookup-failed', False)
    mine = [c for c in lookup if c.get('key') == key]
    exact = [c for c in mine if c.get('body_sha256') == body_sha256]
    if exact:
        # Duplicates are reported, never deleted automatically.
        return Reconciliation('published', 'idempotency-key-and-digest-found', False,
                              exact[0].get('id'), len(mine) - 1)
    if mine:
        return Reconciliation('publication-rejected', 'idempotency-key-with-different-digest', False,
                              mine[0].get('id'), len(mine) - 1)
    if operation == 'update':
        present = any(c.get('id') == target_comment_id for c in lookup)
        if present:
            # Replacing a known comment's body is idempotent; the write did not land.
            return Reconciliation('publication-unknown', 'update-not-applied', True, target_comment_id)
        return Reconciliation('publication-unknown', 'update-target-missing', False)
    return Reconciliation('publication-unknown', 'create-not-visible', False)
