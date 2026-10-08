"""Run state machine (design W15 10.1); pure fold over an append-only journal.

The semantic result is complete at ``result-validated``. Publication outcomes
never delete or rewrite it. A closed run is never resumed: retry is a new run.
"""
from dataclasses import dataclass, field
import re

STAGES = ('requested', 'validated', 'captured', 'planned', 'analyzing', 'evaluated',
          'result-validated', 'persisted', 'publish-pending', 'published')
# Failure terminals. The design's single "aborted" is split by cause so the
# permanent record says whether a person, a deadline or a crash ended the run.
FAILURES = ('rejected-input', 'cancelled', 'timed-out', 'internal-error', 'abandoned')
PUBLICATION_ENDS = ('published', 'publication-skipped', 'publication-stale', 'publication-rejected')
# publication-unknown is settled for the run but may still be reconciled.
UNSETTLED_PUBLICATION = 'publication-unknown'
STATES = STAGES + FAILURES + ('publication-skipped', 'publication-stale', 'publication-rejected',
                              UNSETTLED_PUBLICATION)
CLOSED = FAILURES + PUBLICATION_ENDS
ANNOTATIONS = ('late-response-discarded', 'publication-reconciled', 'retry-created')
SEMANTIC_DONE = STAGES.index('result-validated')
_ID = re.compile('[0-9a-f]{32}')

# Failures are only meaningful before the result is durable; afterwards the
# semantic result stands and only publication outcomes may follow.
_NEXT = {stage: (STAGES[i + 1],) for i, stage in enumerate(STAGES[:-1])}
_NEXT['persisted'] = ('publish-pending', 'publication-skipped')
_NEXT['publish-pending'] = ('published', 'publication-stale', 'publication-rejected', UNSETTLED_PUBLICATION)
_NEXT[UNSETTLED_PUBLICATION] = ('published', 'publication-stale', 'publication-rejected')
_FAILABLE = set(STAGES[:STAGES.index('persisted')])


class LifecycleError(ValueError):
    """Malformed journal or event that cannot be part of any valid run."""


@dataclass(frozen=True)
class Decision:
    accepted: bool
    reason: str
    state: str


@dataclass(frozen=True)
class RunView:
    run_id: str
    owner: str
    state: str
    sequence: int
    history: tuple
    retry_of: object = None
    attempt: int = 1
    annotations: tuple = ()
    data: dict = field(default_factory=dict)

    @property
    def closed(self):
        return self.state in CLOSED

    @property
    def semantic_completed(self):
        reached = [s for s in self.history if s in STAGES]
        return bool(reached) and max(STAGES.index(s) for s in reached) >= SEMANTIC_DONE

    def to_dict(self):
        return {'schema': 'run-state-v1', 'run_id': self.run_id, 'state': self.state,
                'closed': self.closed, 'semantic_completed': self.semantic_completed,
                'history': list(self.history), 'events': self.sequence, 'retry_of': self.retry_of,
                'attempt': self.attempt, 'annotations': [dict(a) for a in self.annotations],
                **{k: v for k, v in self.data.items() if k not in {'owner'}}}


def decide(view, event):
    """Return whether ``event`` may be appended after ``view`` (None = empty)."""
    kind, state = event.get('kind'), event.get('state')
    if view is None:
        if kind != 'state' or state != 'requested':
            return Decision(False, 'run-must-start-requested', 'none')
        return Decision(True, 'started', 'requested')
    if event.get('run_id') != view.run_id:
        return Decision(False, 'foreign-run', view.state)
    if kind == 'annotation':
        if event.get('annotation') not in ANNOTATIONS:
            return Decision(False, 'unknown-annotation', view.state)
        return Decision(True, 'annotated', view.state)
    if kind != 'state' or state not in STATES:
        return Decision(False, 'unknown-event', view.state)
    controller = event.get('controller')
    if controller == 'owner' and event.get('owner') != view.owner:
        return Decision(False, 'not-run-owner', view.state)
    if view.closed:
        return Decision(False, 'run-closed', view.state)
    if state in FAILURES:
        if view.state not in _FAILABLE:
            return Decision(False, 'result-already-durable', view.state)
        if state == 'cancelled' and controller not in {'owner', 'operator'}:
            return Decision(False, 'cancel-requires-owner-or-operator', view.state)
        if state == 'abandoned' and controller != 'recovery':
            return Decision(False, 'abandon-requires-recovery', view.state)
        if state not in {'cancelled', 'abandoned'} and controller != 'owner':
            return Decision(False, 'failure-requires-owner', view.state)
        return Decision(True, 'failed', state)
    if view.state == 'publish-pending' and state == UNSETTLED_PUBLICATION and controller == 'recovery':
        return Decision(True, 'publication-outcome-lost', state)
    if (view.state == 'persisted' and controller == 'recovery'
            and state in {'publication-skipped', 'publication-rejected'}):
        return Decision(True, 'closed-after-silent-owner', state)
    if view.state == UNSETTLED_PUBLICATION:
        if controller not in {'owner', 'reconciler'}:
            return Decision(False, 'reconcile-requires-reconciler', view.state)
    elif controller != 'owner':
        return Decision(False, 'progress-requires-owner', view.state)
    if state not in _NEXT.get(view.state, ()):
        return Decision(False, 'invalid-transition', view.state)
    return Decision(True, 'advanced', state)


def fold(events):
    """Validate a whole journal; any rejected event makes the journal invalid."""
    view = None
    for sequence, event in enumerate(events):
        if not isinstance(event, dict) or event.get('sequence') != sequence:
            raise LifecycleError('journal sequence gap or malformed event')
        if sequence == 0:
            run_id, owner = event.get('run_id'), event.get('owner')
            if (not isinstance(run_id, str) or not _ID.fullmatch(run_id)
                    or not isinstance(owner, str) or not _ID.fullmatch(owner)):
                raise LifecycleError('run and owner identifiers must be 32 lowercase hex digits')
            retry_of, attempt = event.get('retry_of'), event.get('attempt', 1)
            if (retry_of is not None and (not isinstance(retry_of, str) or not _ID.fullmatch(retry_of)
                                          or retry_of == run_id)) or type(attempt) is not int or attempt < 1:
                raise LifecycleError('invalid retry lineage')
            if (retry_of is None) != (attempt == 1):
                raise LifecycleError('attempt number contradicts retry lineage')
        decision = decide(view, event)
        if not decision.accepted:
            raise LifecycleError(f'journal contains a rejected event: {decision.reason}')
        if view is None:
            view = RunView(event['run_id'], event['owner'], 'requested', 1, ('requested',),
                           event.get('retry_of'), event.get('attempt', 1), (), dict(event.get('data') or {}))
            continue
        data = {**view.data, **(event.get('data') or {})}
        if event['kind'] == 'annotation':
            view = RunView(view.run_id, view.owner, view.state, sequence + 1, view.history, view.retry_of,
                           view.attempt, view.annotations + ({'annotation': event['annotation'],
                                                              **(event.get('data') or {})},), view.data)
        else:
            view = RunView(view.run_id, view.owner, decision.state, sequence + 1,
                           view.history + (decision.state,), view.retry_of, view.attempt, view.annotations, data)
    if view is None:
        raise LifecycleError('empty journal')
    return view


def recovery_event(view, *, now_seconds, last_activity_seconds, stale_after_seconds):
    """Abnormal-termination rule: silence beyond the lease closes the run.

    A pending publication becomes unknown, never "not sent": the request may
    have reached the provider before the process died.
    """
    if view.closed or view.state == UNSETTLED_PUBLICATION:
        return None
    if now_seconds - last_activity_seconds < stale_after_seconds:
        return None
    if view.state == 'publish-pending':
        return {'kind': 'state', 'state': UNSETTLED_PUBLICATION, 'controller': 'recovery',
                'data': {'publication': {'state': UNSETTLED_PUBLICATION, 'reason': 'owner-silent-during-publication'}}}
    if view.state in _FAILABLE:
        return {'kind': 'state', 'state': 'abandoned', 'controller': 'recovery',
                'data': {'termination': {'state': 'abandoned', 'reason': 'owner-silent-beyond-lease',
                                         'last_state': view.state}}}
    if view.state == 'persisted':
        # publish-pending is journaled before any send, so nothing was sent.
        intended = bool(view.data.get('publication_target'))
        state = 'publication-rejected' if intended else 'publication-skipped'
        return {'kind': 'state', 'state': state, 'controller': 'recovery',
                'data': {'publication': {'state': state, 'reason': 'owner-silent-before-send' if intended
                                         else 'no-publication-requested'}}}
    return None


def retry_admission(previous):
    """A retry never reopens a run. An unknown publication must be reconciled first."""
    if previous is None:
        return Decision(False, 'unknown-previous-run', 'none')
    if not previous.closed:
        return Decision(False, 'previous-run-not-closed', previous.state)
    return Decision(True, 'new-attempt', previous.state)
