"""Owner side of one run: journaled stages, deadline, cancel and late replies.

Analysis runs in a daemon thread so the owner can stop waiting at a deadline
or cancellation. Python cannot kill that thread: it may keep computing until
the process exits, and its reply is then discarded by the closed journal.
Stages outside ``call`` (argument checks, persistence) check the deadline only
at their boundaries. This is not process isolation (design W12 worker).
"""
from hashlib import sha256
import threading
import time
import uuid

from drift_gate.adapters.run_store import RunJournal, RunStoreError
from drift_gate.core.execution import lifecycle
from drift_gate.core.models.input_manifest import canonical_bytes


class RunTerminated(RuntimeError):
    """The run closed (cancelled, timed out or recovered) before this step."""

    def __init__(self, state, reason, view=None):
        super().__init__(f'run {state}: {reason}')
        self.state, self.reason, self.view = state, reason, view


class RunController:
    def __init__(self, root, *, run_id, timeout_seconds=None, poll_seconds=0.1,
                 heartbeat_seconds=5.0, late_grace_seconds=0.0, clock=time.monotonic):
        if timeout_seconds is not None:
            try:
                timeout_seconds = lifecycle.finite_seconds(timeout_seconds, 'timeout', positive=True)
            except lifecycle.LifecycleError as exc:
                raise RunStoreError(str(exc)) from exc
        self.journal = RunJournal(root, run_id)
        self.root, self.run_id = root, run_id
        self.owner = uuid.uuid4().hex
        self.clock = clock
        self.deadline = None if timeout_seconds is None else clock() + timeout_seconds
        self.timeout_seconds = timeout_seconds
        self.poll, self.heartbeat_every, self.late_grace = poll_seconds, heartbeat_seconds, late_grace_seconds
        self.started = False

    # -- journal -----------------------------------------------------------------
    def start(self, *, data, retry_of=None):
        attempt = 1
        if retry_of is not None:
            previous = RunJournal(self.root, retry_of).view()
            admission = lifecycle.retry_admission(previous)
            if not admission.accepted:
                raise RunStoreError(f'retry refused: {admission.reason}')
            attempt = previous.attempt + 1
        if self.journal.events():
            raise RunStoreError('run ID already has a journal; a closed run is never resumed')
        decision = self.journal.append({'kind': 'state', 'state': 'requested', 'controller': 'owner',
                                        'owner': self.owner, 'retry_of': retry_of, 'attempt': attempt,
                                        'data': {**data, 'timeout_seconds': self.timeout_seconds}})
        if not decision.accepted:
            raise RunStoreError(f'run start refused: {decision.reason}')
        self.started = True
        if retry_of is not None:
            # Lineage on the predecessor is an append-only note; its record is unchanged.
            RunJournal(self.root, retry_of).append({'kind': 'annotation', 'annotation': 'retry-created',
                                                    'data': {'retry_run_id': self.run_id, 'attempt': attempt}})
        self.journal.heartbeat(self.owner)

    def view(self):
        return self.journal.view()

    def advance(self, state, **data):
        # The deadline bounds analysis; it never discards a validated result.
        if state in lifecycle.STAGES[:lifecycle.SEMANTIC_DONE]:
            self._check_deadline(state)
        decision = self.journal.append({'kind': 'state', 'state': state, 'controller': 'owner',
                                        'owner': self.owner, 'data': data})
        if not decision.accepted:
            view = self.view()
            raise RunTerminated(view.state, decision.reason, view)
        return decision

    def fail(self, state, code, message):
        """Record a failure terminal; returns the resulting view (never raises on refusal)."""
        if not self.started:
            return None
        termination = {'state': state, 'code': code, 'message': str(message)[:2000]}
        try:
            self.journal.append({'kind': 'state', 'state': state, 'controller': 'owner', 'owner': self.owner,
                                 'data': {'termination': termination}})
            return self.view()
        except (RunStoreError, OSError):
            return None

    def _check_deadline(self, stage):
        if self.deadline is not None and self.clock() >= self.deadline:
            self._timed_out(stage)

    def _timed_out(self, stage):
        decision = self.journal.append({'kind': 'state', 'state': 'timed-out', 'controller': 'owner',
            'owner': self.owner, 'data': {'termination': {'state': 'timed-out', 'code': 'deadline',
            'message': f'deadline of {self.timeout_seconds}s reached', 'stage': stage}}})
        view = self.view()
        raise RunTerminated(view.state, 'deadline' if decision.accepted else decision.reason, view)

    # -- bounded wait for one stage ----------------------------------------------
    def call(self, stage, function):
        """Run ``function`` while watching deadline and operator cancellation."""
        outcome = {}
        done = threading.Event()

        def work():
            try:
                outcome['value'] = function()
            except BaseException as exc:  # reported to the owner, never swallowed
                outcome['error'] = exc
            finally:
                done.set()

        worker = threading.Thread(target=work, name=f'drift-gate-{stage}-{self.run_id[:8]}', daemon=True)
        worker.start()
        last_beat = self.clock()
        try:
            while not done.wait(self.poll):
                if self.clock() - last_beat >= self.heartbeat_every:
                    self.journal.heartbeat(self.owner)
                    last_beat = self.clock()
                view = self.view()
                if view.closed:
                    raise RunTerminated(view.state, 'closed-by-another-controller', view)
                self._check_deadline(stage)
        except RunTerminated:
            self._discard_late(stage, done, outcome, grace=self.late_grace)
            raise
        except KeyboardInterrupt:
            self.fail('cancelled', 'interrupt', 'interrupted by the operator')
            self._discard_late(stage, done, outcome, grace=self.late_grace)
            raise RunTerminated('cancelled', 'interrupt', self.view()) from None
        if 'error' in outcome:
            raise outcome['error']
        view = self.view()
        if view.closed:
            # Reply arrived, but cancellation/recovery closed the run first.
            self._discard_late(stage, done, outcome, grace=0)
            raise RunTerminated(view.state, 'reply-after-close', view)
        return outcome['value']

    def _discard_late(self, stage, done, outcome, *, grace):
        if not done.wait(grace):
            return
        kind = 'error' if 'error' in outcome else 'value'
        note = {'stage': stage, 'outcome': kind}
        value = outcome.get('value')
        if kind == 'value' and hasattr(value, 'result'):
            note['gate_result'] = value.result
        try:
            self.journal.append({'kind': 'annotation', 'annotation': 'late-response-discarded', 'data': note})
        except (RunStoreError, OSError):
            pass


def cancel_run(root, run_id, *, reason='operator-request'):
    journal = RunJournal(root, run_id)
    if journal.view() is None:
        raise RunStoreError('unknown run')
    decision = journal.append({'kind': 'state', 'state': 'cancelled', 'controller': 'operator',
                               'data': {'termination': {'state': 'cancelled', 'code': 'operator',
                                                        'message': str(reason)[:2000]}}})
    return decision, journal.view()


def result_digest(result_dict):
    return sha256(canonical_bytes(result_dict)).hexdigest()
