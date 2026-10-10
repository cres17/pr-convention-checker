"""Keyed signatures for approval envelopes so a stored waiver can be re-admitted.

HMAC-SHA256 over the canonical envelope with an organization key held outside
the repository (environment, CI secret). A valid MAC shows that a holder of the
key produced the envelope after the adapter's provider check. It is shared-key
authentication, not a public-key signature or a statement about the approver.
Without a configured key no envelope is signed and stored waivers stay refused.
"""
import base64
import hmac
import json
import os
import re
from hashlib import sha256

from drift_gate.core.models.input_manifest import canonical_bytes

SCHEMA = 'approval-signature-v1'
SIGNING_ENV = 'DRIFT_GATE_APPROVAL_SIGNING_KEY'   # "key_id:base64-key"
KEYRING_ENV = 'DRIFT_GATE_APPROVAL_KEYS'          # JSON {"key_id": "base64-key"}
_KEY_ID = re.compile('[A-Za-z0-9._-]{1,64}')


class ApprovalSignatureError(ValueError):
    """Missing, unknown or invalid approval key or signature."""


def _decode_key(value):
    try:
        key = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ApprovalSignatureError('approval key must be base64') from exc
    if len(key) < 32:
        raise ApprovalSignatureError('approval key must be at least 32 bytes')
    return key


def signing_key(environ=None):
    raw = (environ if environ is not None else os.environ).get(SIGNING_ENV)
    if not raw:
        return None
    key_id, _, encoded = raw.partition(':')
    if not _KEY_ID.fullmatch(key_id) or not encoded:
        raise ApprovalSignatureError(f'{SIGNING_ENV} must be key_id:base64-key')
    return key_id, _decode_key(encoded)


def keyring(environ=None):
    raw = (environ if environ is not None else os.environ).get(KEYRING_ENV)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ApprovalSignatureError(f'{KEYRING_ENV} must be a JSON object') from exc
    if not isinstance(data, dict) or any(not isinstance(k, str) or not _KEY_ID.fullmatch(k) for k in data):
        raise ApprovalSignatureError(f'{KEYRING_ENV} must map key IDs to keys')
    return {key_id: _decode_key(value) for key_id, value in data.items()}


def _mac(key, envelope):
    return hmac.new(key, canonical_bytes(envelope), sha256).hexdigest()


def sign(envelope, key_id, key):
    return {'schema': SCHEMA, 'algorithm': 'hmac-sha256', 'key_id': key_id, 'mac': _mac(key, envelope)}


def verify(envelope, signature, keys):
    if (not isinstance(signature, dict) or signature.get('schema') != SCHEMA
            or signature.get('algorithm') != 'hmac-sha256' or set(signature) != {'schema', 'algorithm', 'key_id', 'mac'}):
        raise ApprovalSignatureError('unsupported approval signature')
    key = keys.get(signature['key_id'])
    if key is None:
        raise ApprovalSignatureError('approval signature key is not in the keyring')
    if not isinstance(signature['mac'], str) or not hmac.compare_digest(signature['mac'], _mac(key, envelope)):
        raise ApprovalSignatureError('approval signature does not match the envelope')
    return True
