"""Identity for immutable baseline-derived results; excludes checkout presentation."""

import hashlib
import json
import uuid


def baseline_id(baseline: dict) -> str:
    values = {key: baseline.get(key) for key in ('version', 'documents', 'document_kinds', 'requirements')}
    if baseline.get('archived_documents'):
        values['archived_documents'] = sorted(baseline['archived_documents'])
    content = json.dumps(values, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def inspection_context(baseline: dict) -> dict:
    return {
        'baseline_version': baseline['version'],
        'baseline_id': baseline_id(baseline),
        'inspection_id': uuid.uuid4().hex,
    }
