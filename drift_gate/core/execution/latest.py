"""Latest-result fencing (design W15 10.2); pure fold over a target ledger.

An immutable result stays bound to its subject. Only the mutable "latest"
pointer is fenced. ``generation`` advances whenever the observed head or
authority differs from the previous observation, so head A->B->A yields a new
generation and an old attempt for A cannot become latest again. ``ticket``
orders observations, so reverse completion inside one generation cannot
replace a newer result with an older one.

Observations happen when a run captures its subject; this is not a provider
webhook. A pointer can therefore be stale relative to a head no run observed.
"""
from dataclasses import dataclass, field
import re

_OID = re.compile('[0-9a-f]{40}([0-9a-f]{24})?')
_SHA = re.compile('[0-9a-f]{64}')
_ID = re.compile('[0-9a-f]{32}')


class LedgerError(ValueError):
    """Malformed or self-contradicting target ledger."""


@dataclass(frozen=True)
class Latest:
    run_id: str
    ticket: int
    generation: int
    head_oid: str
    authority_sha256: str
    receipt_sha256: str
    result_sha256: str

    def to_dict(self):
        return dict(run_id=self.run_id, ticket=self.ticket, generation=self.generation, head_oid=self.head_oid,
                    authority_sha256=self.authority_sha256, receipt_sha256=self.receipt_sha256,
                    result_sha256=self.result_sha256)


@dataclass(frozen=True)
class TargetState:
    target: str
    generation: int = 0
    tickets: int = 0
    head_oid: object = None
    authority_sha256: object = None
    latest: object = None
    entries: int = 0
    issued: dict = field(default_factory=dict, compare=False, repr=False)

    def to_dict(self):
        current = (self.latest is not None and self.latest.generation == self.generation)
        return {'schema': 'latest-target-v1', 'target': self.target, 'generation': self.generation,
                'observed_head_oid': self.head_oid, 'observed_authority_sha256': self.authority_sha256,
                'tickets_issued': self.tickets, 'ledger_entries': self.entries,
                'latest': self.latest.to_dict() if self.latest else None,
                'latest_status': 'none' if self.latest is None else 'current' if current else 'stale',
                'freshness_scope': 'last-observation-by-a-run-not-provider-head'}


@dataclass(frozen=True)
class PublishDecision:
    accepted: bool
    reason: str


def _check(value, pattern, label):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise LedgerError(f'invalid {label}')


def observe(state, *, head_oid, authority_sha256):
    """Return (entry, ticket, generation) for a run that captured this subject."""
    _check(head_oid, _OID, 'head OID'); _check(authority_sha256, _SHA, 'authority digest')
    changed = (head_oid, authority_sha256) != (state.head_oid, state.authority_sha256)
    generation = state.generation + 1 if changed else state.generation
    ticket = state.tickets + 1
    return ({'kind': 'observe', 'head_oid': head_oid, 'authority_sha256': authority_sha256,
             'ticket': ticket, 'generation': generation}, ticket, generation)


def decide_publish(state, request, *, completed):
    """Compare-and-set guard for the latest pointer."""
    if not completed:
        return PublishDecision(False, 'run-not-semantically-completed')
    ticket, generation = request.get('ticket'), request.get('generation')
    if type(ticket) is not int or ticket not in state.issued:
        return PublishDecision(False, 'unknown-ticket')
    if state.issued[ticket] != (generation, request.get('head_oid'), request.get('authority_sha256')):
        return PublishDecision(False, 'ticket-observation-mismatch')
    if type(generation) is not int or generation != state.generation:
        return PublishDecision(False, 'generation-changed')
    if (request.get('head_oid'), request.get('authority_sha256')) != (state.head_oid, state.authority_sha256):
        return PublishDecision(False, 'head-or-authority-changed')
    if state.latest is not None and state.latest.ticket >= ticket:
        return PublishDecision(False, 'newer-or-same-result-already-latest')
    return PublishDecision(True, 'compare-and-set-matched')


def publish_entry(request):
    entry = {'kind': 'publish', **{k: request[k] for k in (
        'run_id', 'ticket', 'generation', 'head_oid', 'authority_sha256', 'receipt_sha256', 'result_sha256')}}
    _check(entry['run_id'], _ID, 'run ID')
    for key in ('receipt_sha256', 'result_sha256'):
        _check(entry[key], _SHA, key)
    return entry


def fold(target, entries):
    state = TargetState(target)
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or entry.get('sequence') != index:
            raise LedgerError('ledger sequence gap or malformed entry')
        if entry.get('kind') == 'observe':
            expected, ticket, generation = observe(state, head_oid=entry.get('head_oid'),
                                                    authority_sha256=entry.get('authority_sha256'))
            if {k: entry.get(k) for k in expected} != expected:
                raise LedgerError('observation does not follow from the previous state')
            issued = state.issued  # one map per fold; intermediate states are not exposed
            issued[ticket] = (generation, entry['head_oid'], entry['authority_sha256'])
            state = TargetState(target, generation, ticket, entry['head_oid'], entry['authority_sha256'],
                                state.latest, index + 1, issued)
        elif entry.get('kind') == 'publish':
            request = publish_entry(entry)
            decision = decide_publish(state, request, completed=True)
            if not decision.accepted:
                raise LedgerError(f'ledger contains a rejected publication: {decision.reason}')
            latest = Latest(**{k: v for k, v in request.items() if k != 'kind'})
            state = TargetState(target, state.generation, state.tickets, state.head_oid,
                                state.authority_sha256, latest, index + 1, state.issued)
        else:
            raise LedgerError('unknown ledger entry')
    return state
