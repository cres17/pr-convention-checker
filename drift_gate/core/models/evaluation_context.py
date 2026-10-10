"""Explicit date input for deterministic expiry decisions; no clock reads.

``subject_head_oid`` and ``policy_sha256`` are optional bindings for approval
envelopes. They are serialized only when present, so captures without
approvals keep their previous identity.
"""
from dataclasses import dataclass
from datetime import date
import re


@dataclass(frozen=True)
class EvaluationContext:
    evaluated_on: date
    subject_head_oid: str | None = None
    policy_sha256: str | None = None

    def __post_init__(self):
        if type(self.evaluated_on) is not date:
            raise ValueError('evaluated_on must be a date')
        if self.subject_head_oid is not None and not re.fullmatch('[0-9a-f]{40}([0-9a-f]{24})?', self.subject_head_oid):
            raise ValueError('subject_head_oid must be a full commit OID')
        if self.policy_sha256 is not None and not re.fullmatch('[0-9a-f]{64}', self.policy_sha256):
            raise ValueError('policy_sha256 must be a SHA-256 digest')

    def to_dict(self):
        data = {'evaluated_on': self.evaluated_on.isoformat(), 'date_basis': 'UTC'}
        if self.subject_head_oid is not None:
            data['subject_head_oid'] = self.subject_head_oid
        if self.policy_sha256 is not None:
            data['policy_sha256'] = self.policy_sha256
        return data

    @classmethod
    def from_dict(cls, data):
        return cls(date.fromisoformat(data['evaluated_on']), data.get('subject_head_oid'), data.get('policy_sha256'))
