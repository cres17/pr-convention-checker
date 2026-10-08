"""Live W15 PR-comment publication check against cres17/pr-convention-checker#1."""
import json, os, sys, time
from datetime import datetime, timezone
from drift_gate.adapters.github import publication as pub

REPO, PR = 'cres17/pr-convention-checker', 1
HEAD = 'b5c52ab281ed550b1e645bf000834f7c012f050f'
OTHER = 'ed9f9046cca46c79b379ccdbafaa08feaa8241d6'
out_dir = sys.argv[1]
report = open(os.path.join(out_dir, 'report.md'), encoding='utf-8').read()
result_sha = json.load(open(os.path.join(out_dir, 'report.json')))
from hashlib import sha256
from drift_gate.core.models.input_manifest import canonical_bytes
result_sha = sha256(canonical_bytes(result_sha)).hexdigest()
NOTE = ('\n\n---\n> W15 게시 경로 수동 검증: Claude 세션에서 `drift_gate.adapters.github.publication`을 직접 실행했다. '
        'GitHub Action 실행이 아니며, 본문은 W15 변경(`ed9f904..b5c52ab`)의 자체 정책 결과다.\n')

real = pub.CommentApi(os.environ['GH_TOKEN'], REPO)


class Lossy:
    """Real provider; ``mode`` = 'after-send' drops the response, 'before-send' drops the request."""
    def __init__(self, mode=None):
        self.mode, self.writes = mode, []
    def pr_head(self, pr): return real.pr_head(pr)
    def comments(self, pr): return real.comments(pr)
    def _write(self, kind, call):
        mode, self.mode = self.mode, None  # only the first write is affected
        if mode == 'before-send':
            self.writes.append(f'{kind}:dropped-before-send')
            raise pub.LostResponse('simulated: request never sent')
        response = call()
        self.writes.append(f'{kind}:sent')
        if mode == 'after-send':
            raise pub.LostResponse('simulated: response lost after provider applied it')
        return response
    def create(self, pr, body): return self._write('create', lambda: real.create(pr, body))
    def update(self, cid, body): return self._write('update', lambda: real.update(cid, body))


def ident(attempt, head=HEAD):
    return pub.identity(repo=REPO, pr_number=PR, head_oid=head, workflow_ref='manual/w15-live-check@b5c52ab',
                        run_id='manual-w15-3', run_number=3, run_attempt=attempt, result_sha256=result_sha)


def snapshot():
    found = []
    for c in real.comments(PR):
        meta = pub.parse(c.get('body'))
        if meta is not None:
            found.append({'id': c['id'], 'updated_at': c['updated_at'], 'key': meta.get('key'), 'ends_with': c['body'][-48:],
                          'order': [meta.get('run_number'), meta.get('run_attempt')], 'body_intact': meta.get('body_intact')})
    return found


steps = []
def step(name, expected, api, attempt, head=HEAD):
    before = snapshot()
    record = pub.publish(api, pr_number=PR, body=report + NOTE, ident=ident(attempt, head))
    time.sleep(2)
    after = snapshot()
    entry = {'body_match': record.get('body_match'), 'content_verified': record.get('content_verified'), 'step': name, 'expected': expected, 'state': record['state'], 'reason': record['reason'],
             'writes': getattr(api, 'writes', None), 'attempts': record['attempts'],
             'reconciliation': record.get('reconciliation'), 'comments_before': before, 'comments_after': after,
             'record': record, 'matched_expectation': [record['state'], record['reason']] == expected}
    steps.append(entry)
    print(name, record['state'], record['reason'], record.get('body_match'), entry['writes'], 'OK' if entry['matched_expectation'] else 'MISMATCH')
    return record

r1 = step('A-update-newer-run', ['published', 'provider-confirmed-write'], Lossy(), 1)
step('B-same-attempt-repeat', ['published', 'already-published-by-this-attempt'], Lossy(), 1)
r3 = step('C-update-response-lost-after-send', ['published', 'lost-response-reconciled-by-key'], Lossy('after-send'), 2)
r4 = step('D-update-dropped-before-send-retried', ['published', 'provider-confirmed-write'], Lossy('before-send'), 3)
step('E-older-attempt-after-newer', ['publication-stale', 'later-run-already-published'], Lossy(), 2)
step('F-evaluated-head-not-current', ['publication-stale', 'head-changed-before-write'], Lossy(), 4, head=OTHER)
json.dump({'record_from_D': r4}, open(os.path.join(out_dir, 'record-D.json'), 'w'), indent=2)
json.dump({'record_from_C': r3}, open(os.path.join(out_dir, 'record-C.json'), 'w'), indent=2)
json.dump({'schema': 'w15-live-publication-check-v1', 'repo': REPO, 'pr': PR, 'pr_head': HEAD,
           'executed_at': datetime.now(timezone.utc).isoformat(), 'code_commit': HEAD,
           'executor': 'claude-session-direct-call-not-github-action', 'steps': steps,
           'all_matched': all(s['matched_expectation'] for s in steps)},
          open(os.path.join(out_dir, 'live-publication-check.json'), 'w'), ensure_ascii=False, indent=2)
