"""Compute and verify fact spans over a persisted evidence bundle's original Git bytes.

Facts are re-derived by the current engine from the stored bytes; each span is
then re-checked against the raw object whose SHA-256 the receipt pins.
"""
from hashlib import sha256

from drift_gate.core.evaluation.api_schema import extract_routes, UnsupportedContract
from drift_gate.core.evaluation.environment import environment_facts
from drift_gate.core.evaluation.evidence_spans import (
    document_route_spans, env_key_spans, python_route_spans, verify_span,
)


def _routes(text):
    try:
        return extract_routes(text)
    except UnsupportedContract:
        return None


def _document_routes(path, text):
    from drift_gate.core.evaluation.contracts import _routes as text_routes
    if path.lower().endswith('.json'):
        import json
        try:
            data = json.loads(text)
            paths = data.get('paths') if isinstance(data, dict) else None
            return {(m.upper(), p) for p, item in (paths or {}).items() if isinstance(item, dict)
                    for m in item if m in {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'}}
        except ValueError:
            return None
    if path.lower().endswith(('.md', '.markdown', '.txt')):
        return text_routes(text.splitlines(), docs=True)
    return None


def bundle_spans(bundle):
    evidence = bundle.snapshot.git_evidence
    if evidence is None:
        return {'schema': 'fact-spans-v1', 'available': False, 'reason': 'bundle has no original Git objects'}
    rows, unresolved, unsupported = [], [], []
    for artifact in evidence.artifacts:
        if artifact.content is None or artifact.kind != 'blob':
            continue
        raw = artifact.content
        info = {'sha256': sha256(raw).hexdigest(), 'path': artifact.path, 'revision': artifact.revision}
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            unsupported.append({'path': artifact.path, 'revision': artifact.revision, 'reason': 'not-utf-8'})
            continue
        spans, missing = [], []
        if artifact.path.endswith('.py'):
            routes = _routes(text)
            if routes is None:
                unsupported.append({'path': artifact.path, 'revision': artifact.revision, 'reason': 'route-analysis-open'})
            elif routes:
                found, lost = python_route_spans(raw, routes, artifact=info)
                spans += found; missing += lost
            facts = environment_facts(text)
            if facts.keys:
                found, lost = env_key_spans(raw, facts.keys, artifact=info)
                spans += found; missing += lost
        else:
            documented = _document_routes(artifact.path, text)
            if documented:
                found, lost = document_route_spans(raw, documented, artifact=info)
                spans += found; missing += lost
        for span in spans:
            rows.append({**span.to_dict(), 'verified': verify_span(raw, span)})
        unresolved += [{'path': artifact.path, 'revision': artifact.revision, 'identity': list(item)
                        if isinstance(item, tuple) else [item]} for item in missing]
    return {'schema': 'fact-spans-v1', 'available': True, 'receipt_sha256': sha256(bundle.receipt_bytes).hexdigest(),
            'spans': rows, 'verified': sum(row['verified'] for row in rows), 'total': len(rows),
            'unresolved': unresolved, 'unsupported': unsupported,
            'claim': 'location-of-evidence-in-original-bytes, not analyzer correctness'}
