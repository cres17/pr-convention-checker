"""NoDeltaCertificate for a whole service scope (design W05 4.3, W11).

A certificate is evidence, not an empty result string. For one service and one
contract family it requires:
  1. every module of the service read (or confirmed absent by tree enumeration)
     at both revisions;
  2. the same profile on both sides;
  3. closed discovery (facts established for every module) and no open
     dependency boundary among the service's modules;
  4. no added and no removed identity;
  5. no module whose service is ambiguous (its facts could belong here).
An empty change in a selected file set is a different, weaker statement and is
never promoted to this certificate.
"""
from dataclasses import dataclass
from hashlib import sha256
import json

REASONS = ('missing_source', 'unsupported_binding', 'open_dependency_scope', 'ambiguous_service_scope',
           'resource_limit', 'identity_delta', 'profile_mismatch')


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


@dataclass(frozen=True)
class NoDeltaCertificate:
    service_id: str
    family: str
    profile_ref: tuple
    before_tree: str
    after_tree: str
    modules: int
    facts_sha256: str

    def to_dict(self):
        return {'schema': 'no-delta-certificate-v1', 'certified': True, 'service_id': self.service_id,
                'family': self.family, 'profile_ref': list(self.profile_ref), 'before_tree': self.before_tree,
                'after_tree': self.after_tree, 'modules_enumerated': self.modules,
                'facts_sha256': self.facts_sha256,
                'conditions': ['artifacts-read-or-absent', 'same-profile', 'discovery-and-dependency-closed',
                               'empty-added-and-removed', 'no-ambiguous-service-module'],
                'assumptions': ['static-profile-semantics', 'external-packages-contribute-no-repository-contract-facts']}


@dataclass(frozen=True)
class NoDeltaRefusal:
    service_id: str
    family: str
    reasons: tuple

    def to_dict(self):
        return {'schema': 'no-delta-certificate-v1', 'certified': False, 'service_id': self.service_id,
                'family': self.family, 'reason_codes': list(self.reasons)}


def certify(*, service_id, family, profile_before, profile_after, before_facts, after_facts, modules,
            unread_modules, open_modules, dependency_open_modules, ambiguous_modules, limited,
            before_tree, after_tree):
    """Return a certificate or a refusal listing every unmet condition."""
    reasons = []
    if unread_modules:
        reasons.append('missing_source')
    if profile_before != profile_after:
        reasons.append('profile_mismatch')
    if open_modules:
        reasons.append('unsupported_binding')
    if dependency_open_modules:
        reasons.append('open_dependency_scope')
    if ambiguous_modules:
        reasons.append('ambiguous_service_scope')
    if limited:
        reasons.append('resource_limit')
    if before_facts is None or after_facts is None or before_facts != after_facts:
        reasons.append('identity_delta')
    if not modules:
        # Nothing enumerated is not a closed scope.
        reasons.append('missing_source')
    if reasons:
        return NoDeltaRefusal(service_id, family, tuple(sorted(set(reasons))))
    return NoDeltaCertificate(service_id, family, tuple(profile_before), before_tree, after_tree, modules,
                              _digest(sorted(map(list, before_facts))))
