"""Approval envelopes for waivers (design W09).

An envelope binds one waiver to a rule, the trigger paths it covers, the exact
head commit, the policy digest, a UTC validity window, the approver and the
authority evidence an adapter checked. Free text such as ``approved-by:`` or a
``verified: true`` field in user JSON is never an envelope. This module only
checks the binding; whether the authority evidence is genuine is the adapter's
verification (provider API or a keyed signature), recorded in ``authority``.
"""
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
import re

AUTHORITY_KINDS = ('github-codeowners-review',)
_OID = re.compile('[0-9a-f]{40}([0-9a-f]{24})?')
_SHA = re.compile('[0-9a-f]{64}')


def _iso(value, label):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f'{label} must be an ISO date') from None


@dataclass(frozen=True)
class ApprovalEnvelope:
    rule_id: str
    scope_paths: tuple[str, ...]
    subject_head_oid: str
    policy_sha256: str
    reason: str
    valid_from: str
    expires: str | None
    approvers: tuple[str, ...]
    authority: dict
    schema: str = 'approval-envelope-v1'

    def __post_init__(self):
        if self.schema != 'approval-envelope-v1':
            raise ValueError('unsupported approval envelope schema')
        if not isinstance(self.rule_id, str) or not self.rule_id:
            raise ValueError('envelope requires a rule')
        if (not isinstance(self.scope_paths, (tuple, list)) or not self.scope_paths
                or any(not isinstance(path, str) or not path for path in self.scope_paths)):
            raise ValueError('envelope requires covered trigger paths')
        object.__setattr__(self, 'scope_paths', tuple(sorted(set(self.scope_paths))))
        if not isinstance(self.subject_head_oid, str) or not _OID.fullmatch(self.subject_head_oid):
            raise ValueError('envelope requires the exact head commit')
        if not isinstance(self.policy_sha256, str) or not _SHA.fullmatch(self.policy_sha256):
            raise ValueError('envelope requires the policy digest')
        if not isinstance(self.reason, str):
            raise ValueError('envelope reason must be text (empty when none was given)')
        start = _iso(self.valid_from, 'valid_from')
        if self.expires is not None and _iso(self.expires, 'expires') < start:
            raise ValueError('envelope expires before it starts')
        if (not isinstance(self.approvers, (tuple, list)) or not self.approvers
                or any(not isinstance(item, str) or not item for item in self.approvers)):
            raise ValueError('envelope requires approvers')
        object.__setattr__(self, 'approvers', tuple(sorted(set(self.approvers))))
        if not isinstance(self.authority, dict) or self.authority.get('kind') not in AUTHORITY_KINDS:
            raise ValueError('envelope requires typed authority evidence')
        if self.authority.get('kind') == 'github-codeowners-review':
            evidence = self.authority
            if (not isinstance(evidence.get('reviews'), list) or not evidence['reviews']
                    or not isinstance(evidence.get('codeowners_sha256'), str)
                    or not _SHA.fullmatch(evidence['codeowners_sha256'])
                    or any(not isinstance(row, dict) or row.get('commit_id') != self.subject_head_oid
                           or row.get('state') != 'APPROVED' for row in evidence['reviews'])):
                raise ValueError('CODEOWNERS authority requires approved reviews on the head commit')

    def to_dict(self):
        return {'schema': self.schema, 'rule_id': self.rule_id, 'scope_paths': list(self.scope_paths),
                'subject_head_oid': self.subject_head_oid, 'policy_sha256': self.policy_sha256,
                'reason': self.reason, 'valid_from': self.valid_from, 'expires': self.expires,
                'approvers': list(self.approvers), 'authority': self.authority}

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError('envelope must be an object')
        keys = {'schema', 'rule_id', 'scope_paths', 'subject_head_oid', 'policy_sha256', 'reason',
                'valid_from', 'expires', 'approvers', 'authority'}
        if set(data) != keys:
            raise ValueError('envelope fields are incomplete or unexpected')
        return cls(data['rule_id'], tuple(data['scope_paths']), data['subject_head_oid'], data['policy_sha256'],
                   data['reason'], data['valid_from'], data['expires'], tuple(data['approvers']),
                   data['authority'], data['schema'])

    @property
    def digest(self):
        return sha256(json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=True,
                                 separators=(',', ':')).encode()).hexdigest()


def binding_errors(envelope, *, rule_id, trigger_paths, head_oid, policy_sha256, evaluated_on, reason):
    """Reasons the envelope does not authorize this waiver now (empty = authorized)."""
    if not isinstance(envelope, ApprovalEnvelope):
        return ['approval envelope required; text approvals are not authority']
    errors = []
    if envelope.rule_id != rule_id:
        errors.append('envelope approves a different rule')
    if head_oid is None:
        errors.append('evaluation has no subject head to bind the approval to')
    elif envelope.subject_head_oid != head_oid:
        errors.append('envelope approves a different head commit')
    if policy_sha256 is None:
        errors.append('evaluation has no policy digest to bind the approval to')
    elif envelope.policy_sha256 != policy_sha256:
        errors.append('envelope approves a different policy')
    uncovered = sorted(set(trigger_paths) - set(envelope.scope_paths))
    if not trigger_paths or uncovered:
        errors.append('envelope does not cover every trigger path')
    if (reason or '').strip() != envelope.reason.strip():
        errors.append('waiver reason differs from the approved reason')
    if evaluated_on is None:
        errors.append('explicit evaluation date required')
    else:
        if evaluated_on < date.fromisoformat(envelope.valid_from):
            errors.append('approval is not yet valid')
        if envelope.expires is not None and evaluated_on > date.fromisoformat(envelope.expires):
            errors.append('approval expired')
    return errors
