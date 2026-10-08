"""W08 interval membership soundness and W07/W08 byte-range evidence."""
from hashlib import sha256
from itertools import chain, combinations, product
import json

import pytest

from drift_gate.core.contracts.planner import Truth
from drift_gate.core.evaluation.evidence_spans import (
    EvidenceSpan, document_route_spans, env_key_spans, python_route_spans, verify_span,
)
from drift_gate.core.evaluation.membership import Bounds, env_requirement, route_requirement

UNIVERSE = ('a', 'b', 'c')


def subsets(values):
    return [frozenset(c) for c in chain.from_iterable(combinations(values, n) for n in range(len(values) + 1))]


ALL = subsets(UNIVERSE)


def bounds_for(actual):
    """Every bound pair consistent with an actual set, including an open upper bound."""
    for lower in ALL:
        if lower <= actual:
            yield Bounds(lower, None)
            for upper in ALL:
                if actual <= upper and lower <= upper:
                    yield Bounds(lower, upper)


def worlds(bound):
    return [s for s in ALL if bound.lower <= s and (bound.upper is None or s <= bound.upper)]


def test_route_membership_is_sound_over_every_bound_and_world():
    """3-identity universe: whenever T/F is returned, every consistent world agrees."""
    checked = decided = 0
    bound_set = {b for actual in ALL for b in bounds_for(actual)}
    for added, removed, document in product(bound_set, repeat=3):
        verdict = route_requirement(added, removed, document)
        checked += 1
        if verdict == Truth.UNKNOWN:
            continue
        decided += 1
        expected = verdict == Truth.TRUE
        for a, r, d in product(worlds(added), worlds(removed), worlds(document)):
            assert (a <= d and not (r & d)) == expected, (added, removed, document, a, r, d)
    assert checked == len(bound_set) ** 3 and decided > 0


def test_env_membership_is_sound_and_ignores_removal():
    bound_set = {b for actual in ALL for b in bounds_for(actual)}
    for added, document in product(bound_set, repeat=2):
        verdict = env_requirement(added, document)
        if verdict == Truth.UNKNOWN:
            continue
        for a, d in product(worlds(added), worlds(document)):
            assert (a <= d) == (verdict == Truth.TRUE)


def test_exact_bounds_reproduce_the_previous_set_rule():
    for added, removed, documented in product(ALL, repeat=3):
        verdict = route_requirement(Bounds.exact(added), Bounds.exact(removed), Bounds.exact(documented))
        assert verdict == (Truth.TRUE if added <= documented and not removed & documented else Truth.FALSE)


def test_unknown_document_never_proves_absence():
    assert route_requirement(Bounds.exact({'a'}), Bounds.exact(()), Bounds.unknown()) == Truth.UNKNOWN
    assert route_requirement(Bounds.exact(()), Bounds.exact(()), Bounds.unknown()) == Truth.TRUE  # nothing required
    assert route_requirement(Bounds.exact(()), Bounds.exact({'a'}), Bounds.unknown({'a'})) == Truth.FALSE


SOURCE = b'''from fastapi import APIRouter, FastAPI
import os
app = FastAPI()
router = APIRouter(prefix="/v1")

@app.get("/health")
def health():
    return {"\xea\xb0\x92": os.getenv("SERVICE_TOKEN")}

@router.post("/items")
def create():
    return os.environ["ITEM_LIMIT"]

app.include_router(router)
'''


def artifact(raw, path='src/api.py'):
    return {'sha256': sha256(raw).hexdigest(), 'path': path, 'revision': '1' * 40}


def test_python_spans_are_utf8_byte_ranges_that_verify():
    spans, unresolved = python_route_spans(SOURCE, {('GET', '/health'), ('POST', '/v1/items')}, artifact=artifact(SOURCE))
    assert not unresolved and len(spans) == 2
    for span in spans:
        assert verify_span(SOURCE, span)
    post = next(s for s in spans if s.identity == ('POST', '/v1/items'))
    assert SOURCE[post.start:post.end] == b'router.post("/items")'
    keys, missing = env_key_spans(SOURCE, {'SERVICE_TOKEN', 'ITEM_LIMIT', 'NOT_USED'}, artifact=artifact(SOURCE))
    assert missing == ['NOT_USED'] and {s.identity[0] for s in keys} == {'SERVICE_TOKEN', 'ITEM_LIMIT'}
    token = next(s for s in keys if s.identity == ('SERVICE_TOKEN',))
    assert SOURCE[token.start:token.end] == b'"SERVICE_TOKEN"'  # after a multibyte character on the line


def test_span_verification_rejects_other_bytes_ranges_and_identities():
    spans, _ = python_route_spans(SOURCE, {('GET', '/health')}, artifact=artifact(SOURCE))
    span = spans[0]
    assert not verify_span(SOURCE.replace(b'/health', b'/healtx'), span)  # hash differs
    shifted = EvidenceSpan(span.artifact_sha256, span.artifact_path, span.artifact_revision, span.kind,
                           span.identity, span.start + 1, span.end)
    assert not verify_span(SOURCE, shifted)
    wrong = EvidenceSpan(span.artifact_sha256, span.artifact_path, span.artifact_revision, span.kind,
                         ('POST', '/health'), span.start, span.end)
    assert not verify_span(SOURCE, wrong)
    with pytest.raises(ValueError):
        EvidenceSpan(span.artifact_sha256, 'p', 'r', span.kind, span.identity, 5, 5)


def test_ambiguous_route_literal_is_left_unresolved():
    raw = b'@a.get("/x")\ndef f(): pass\n@b.get("/x")\ndef g(): pass\n'
    spans, unresolved = python_route_spans(raw, {('GET', '/x')}, artifact=artifact(raw))
    assert spans == [] and unresolved == [('GET', '/x')]


def test_document_spans_for_markdown_and_openapi():
    markdown = '| GET | /health |\nPOST /v1/items creates an item\n'.encode()
    spans, unresolved = document_route_spans(markdown, {('GET', '/health'), ('POST', '/v1/items'), ('GET', '/gone')},
                                             artifact=artifact(markdown, 'docs/api.md'))
    assert unresolved == [('GET', '/gone')] and all(verify_span(markdown, s) for s in spans)
    openapi = json.dumps({'paths': {'/health': {'get': {}}}}).encode()
    spans, _ = document_route_spans(openapi, {('GET', '/health')}, artifact=artifact(openapi, 'openapi.json'))
    assert spans[0].kind == 'openapi-path-key' and verify_span(openapi, spans[0])


def test_cli_bundle_spans_over_stored_git_objects(tmp_path, monkeypatch, capsys):
    from drift_gate.adapters.cli.runner import run_cli
    from drift_gate.adapters.evidence_bundle import save_bundle
    from drift_gate.adapters.inspection import inspect_snapshot
    from drift_gate.tests.test_git_immutable import capture, repo as repository_fixture
    repository = repository_fixture.__wrapped__(tmp_path)
    bundle = save_bundle(inspect_snapshot(capture(repository)), tmp_path / 'evidence')
    with pytest.raises(SystemExit) as exit:
        run_cli(['bundle', 'spans', str(bundle.path)])
    data = json.loads(capsys.readouterr().out)
    assert exit.value.code == 0 and data['total'] > 0 and data['verified'] == data['total']
    assert {tuple(row['identity']) for row in data['spans'] if row['kind'] == 'python-route-decorator'} >= {('GET', '/new')}
