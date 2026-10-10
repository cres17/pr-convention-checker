"""PR comment publication with freshness checks and lost-response recovery.

GitHub's issue-comment API offers neither conditional writes nor idempotent
create, so this adapter cannot provide a compare-and-set. It narrows the race:
the evaluated head is compared before and after the write, a comment written
by a later run of the same workflow is never replaced, and a write whose
response was lost is resolved by searching for this attempt's idempotency key
instead of blindly posting again. A read-check-write race between concurrent
runs remains and is reported as ``race_window`` in every record.
"""
from hashlib import sha256
import json
import re
import socket
import urllib.error
import urllib.request

from drift_gate.core.execution.publication import reconcile
from drift_gate.core.models.input_manifest import canonical_bytes

MARKER = '<!-- drift-gate-v1 -->'
_META = re.compile(r'<!-- drift-gate-publication v1 key=([0-9a-f]{64}) body=([0-9a-f]{64}) '
                   r'head=([0-9a-f]{40}|[0-9a-f]{64}) order=([0-9a-f]{64}):([0-9]{1,18}):([0-9]{1,18}) -->')
RACE_WINDOW = 'read-check-write-not-atomic-on-provider'


class ProviderError(RuntimeError):
    """A definite provider answer (HTTP status) as opposed to a lost response."""

    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


class LostResponse(RuntimeError):
    """The request may or may not have been applied."""


def identity(*, repo, pr_number, head_oid, workflow_ref, run_id, run_number, run_attempt, result_sha256):
    for name, value in (('run_number', run_number), ('run_attempt', run_attempt)):
        if type(value) is not int or value < 1:
            raise ValueError(f'{name} must be a positive integer')
    if not re.fullmatch('[0-9a-f]{40}|[0-9a-f]{64}', head_oid or ''):
        raise ValueError('publication needs the evaluated head commit OID')
    basis = {'schema': 'pr-comment-publication-v1', 'repo': repo, 'pr': pr_number, 'head_oid': head_oid,
             'workflow_ref': workflow_ref, 'run_id': str(run_id), 'run_number': run_number,
             'run_attempt': run_attempt, 'result_sha256': result_sha256}
    return {**basis,
            'key': sha256(canonical_bytes(basis)).hexdigest(),
            'workflow_sha256': sha256((workflow_ref or '').encode('utf-8')).hexdigest()}


def render(body, ident):
    if not body.startswith(MARKER + '\n'):
        raise ValueError('report body must start with the Drift Gate marker line')
    digest = sha256(body.encode('utf-8')).hexdigest()
    meta = (f'<!-- drift-gate-publication v1 key={ident["key"]} body={digest} head={ident["head_oid"]} '
            f'order={ident["workflow_sha256"]}:{ident["run_number"]}:{ident["run_attempt"]} -->')
    return MARKER + '\n' + meta + body[len(MARKER):], digest


def parse(comment_body):
    """Return metadata for a Drift Gate comment, {'legacy': True} without it, None otherwise."""
    if not isinstance(comment_body, str) or not comment_body.startswith(MARKER):
        return None
    lines = comment_body.split('\n', 2)
    match = _META.fullmatch(lines[1]) if len(lines) > 1 else None
    if not match:
        return {'legacy': True}
    key, digest, head, workflow, number, attempt = match.groups()
    visible = MARKER + ('\n' + lines[2] if len(lines) > 2 else '')
    return {'legacy': False, 'key': key, 'body_sha256': digest, 'head_oid': head, 'workflow_sha256': workflow,
            'run_number': int(number), 'run_attempt': int(attempt),
            'body_intact': sha256(visible.encode('utf-8')).hexdigest() == digest}


class CommentApi:
    def __init__(self, token, repo, *, timeout=30):
        self._token, self._repo, self._timeout = token, repo, timeout
        self._base = 'https://api.github.com'

    def pr_head(self, pr_number):
        data = self.request('GET', f'{self._base}/repos/{self._repo}/pulls/{pr_number}')
        try:
            return data['head']['sha']
        except (KeyError, TypeError) as exc:
            raise ProviderError('pull request response has no head SHA', 0) from exc

    def comments(self, pr_number, *, max_pages=50):
        found = []
        for page in range(1, max_pages + 1):
            batch = self.request('GET', f'{self._base}/repos/{self._repo}/issues/{pr_number}'
                                        f'/comments?per_page=100&page={page}')
            if not isinstance(batch, list):
                raise ProviderError('unexpected comment listing', 0)
            found.extend(batch)
            if len(batch) < 100:
                return found
        raise ProviderError('comment listing exceeds page bound', 0)

    def create(self, pr_number, body):
        return self.request('POST', f'{self._base}/repos/{self._repo}/issues/{pr_number}/comments', {'body': body})

    def update(self, comment_id, body):
        return self.request('PATCH', f'{self._base}/repos/{self._repo}/issues/comments/{comment_id}',
                            {'body': body})

    def request(self, method, url, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            'Authorization': f'Bearer {self._token}', 'Accept': 'application/vnd.github.v3+json',
            'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code >= 500:
                # A server error does not prove the write was not applied.
                raise LostResponse(f'GitHub {exc.code} on {method}') from exc
            raise ProviderError(f'GitHub {exc.code} on {method}', exc.code) from exc
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, ValueError) as exc:
            raise LostResponse(f'{method} response lost: {exc}') from exc


def pub_meta(body):
    return parse(body) or {}


def _ours(comments):
    entries = []
    for comment in comments:
        meta = parse(comment.get('body'))
        if meta is not None:
            entries.append((comment, meta))
    return entries


def body_match(stored, sent, meta):
    """Compare a stored comment with the sent body (``sent`` None: digest only)."""
    if sent is not None and stored == sent:
        return 'exact'
    if sent is not None and isinstance(stored, str) and stored.startswith(sent):
        return 'suffix-appended'
    if sent is None:
        return 'exact' if meta.get('body_intact') else 'unverified'
    return 'different'


def _lookup(api, pr_number, sent=None):
    try:
        return [{'id': c.get('id'), 'key': m.get('key'), 'body_match': body_match(c.get('body'), sent, m),
                 'order': None if m.get('legacy') else (m['workflow_sha256'], m['run_number'], m['run_attempt'])}
                for c, m in _ours(api.comments(pr_number))]
    except (ProviderError, LostResponse):
        return None


def publish(api, *, pr_number, body, ident):
    """Publish one report; returns a publication record (never raises for provider faults)."""
    full, digest = render(body, ident)
    record = {'schema': 'pr-comment-publication-record-v1', 'idempotency_key': ident['key'],
              'body_sha256': digest, 'expected_head_oid': ident['head_oid'], 'race_window': RACE_WINDOW,
              'operation': None, 'comment_id': None, 'url': None, 'attempts': [],
              'body_match': None, 'content_verified': False,
              'order': {'workflow_sha256': ident['workflow_sha256'], 'run_number': ident['run_number'],
                        'run_attempt': ident['run_attempt']}}

    def done(state, reason, **extra):
        record.update(state=state, reason=reason, **extra)
        return record

    try:
        before = api.pr_head(pr_number)
    except (ProviderError, LostResponse) as exc:
        return done('publication-rejected', f'head-precheck-unavailable: {exc}')
    record['head_before'] = before
    if before != ident['head_oid']:
        return done('publication-stale', 'head-changed-before-write')
    try:
        existing = _ours(api.comments(pr_number))
    except (ProviderError, LostResponse) as exc:
        return done('publication-rejected', f'comment-lookup-unavailable: {exc}')
    for comment, meta in existing:
        if meta.get('key') == ident['key']:
            # This attempt already landed. Rewriting an altered copy would loop if
            # an intermediary alters every write, so the mismatch is only reported.
            match = body_match(comment.get('body'), full, meta)
            return done('published', 'already-published-by-this-attempt', comment_id=comment.get('id'),
                        url=comment.get('html_url'), body_match=match, content_verified=match == 'exact')
    target = existing[0] if existing else None
    if target is not None and not target[1].get('legacy'):
        meta = target[1]
        if meta['workflow_sha256'] != ident['workflow_sha256']:
            return done('publication-rejected', 'comment-owned-by-another-workflow', comment_id=target[0].get('id'))
        if (meta['run_number'], meta['run_attempt']) > (ident['run_number'], ident['run_attempt']):
            return done('publication-stale', 'later-run-already-published', comment_id=target[0].get('id'))
    operation = 'update' if target is not None else 'create'
    record['operation'] = operation
    comment_id = target[0].get('id') if target is not None else None
    for attempt in (1, 2):
        try:
            response = api.update(comment_id, full) if operation == 'update' else api.create(pr_number, full)
            record['attempts'].append({'attempt': attempt, 'outcome': 'response'})
            comment_id = response.get('id', comment_id)
            match = body_match(response.get('body'), full, pub_meta(response.get('body')))
            record.update(comment_id=comment_id, url=response.get('html_url'), body_match=match,
                          content_verified=match == 'exact')
            state, reason = 'published', 'provider-confirmed-write'
            break
        except ProviderError as exc:
            record['attempts'].append({'attempt': attempt, 'outcome': 'provider-error', 'status': exc.status})
            return done('publication-rejected', f'provider-refused: {exc}', comment_id=comment_id)
        except LostResponse as exc:
            record['attempts'].append({'attempt': attempt, 'outcome': 'lost-response', 'detail': str(exc)})
            outcome = reconcile(key=ident['key'], operation=operation, target_comment_id=comment_id,
                                lookup=_lookup(api, pr_number, full),
                                order=(ident['workflow_sha256'], ident['run_number'], ident['run_attempt']))
            record['reconciliation'] = outcome.to_dict()
            if outcome.state == 'published':
                comment_id = outcome.comment_id
                record.update(comment_id=comment_id, duplicates=outcome.duplicates, body_match=outcome.body_match,
                              content_verified=outcome.body_match == 'exact')
                state, reason = 'published', 'lost-response-reconciled-by-key'
                break
            if not (outcome.retry_safe and attempt == 1):
                return done(outcome.state, outcome.reason, comment_id=outcome.comment_id or comment_id)
    try:
        after = api.pr_head(pr_number)
        record['head_after'] = after
        if after != ident['head_oid']:
            return done('publication-stale', 'head-changed-during-write', published=True)
    except (ProviderError, LostResponse):
        record['head_after'] = None
        reason += '; head-postcheck-unavailable'
    return done(state, reason, published=True)


def reconcile_record(api, *, pr_number, record):
    """Explicit follow-up for publication-unknown: look up by key, never re-post."""
    order = record.get('order')
    order = (order['workflow_sha256'], order['run_number'], order['run_attempt']) if isinstance(order, dict) else None
    outcome = reconcile(key=record['idempotency_key'], operation=record.get('operation') or 'create',
                        target_comment_id=record.get('comment_id'), lookup=_lookup(api, pr_number), order=order)
    return {**record, 'state': outcome.state, 'reason': outcome.reason, 'reconciliation': outcome.to_dict(),
            'body_match': outcome.body_match, 'content_verified': outcome.body_match == 'exact'}
