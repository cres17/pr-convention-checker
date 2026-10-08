"""Pure authorization, quota and retention decisions for the organization service.

Tenants are explicit IDs from a registry, never derived from a repository name.
A principal holds roles inside exactly one tenant and a list of repository
scopes; every action needs both the role permission and a matching scope.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
import re

ROLES = {
    'viewer': {'results.read'},
    'runner': {'results.read', 'inspection.run'},
    'admin': {'results.read', 'inspection.run', 'results.delete', 'retention.configure', 'principals.manage',
              'backup.create', 'backup.restore', 'audit.read'},
    'auditor': {'audit.read', 'results.read'},
}
ACTIONS = sorted(set().union(*ROLES.values()))
_TENANT = re.compile('[a-z][a-z0-9-]{1,62}')
_PRINCIPAL = re.compile('[A-Za-z0-9._@-]{1,128}')


def valid_tenant(tenant_id):
    return isinstance(tenant_id, str) and bool(_TENANT.fullmatch(tenant_id))


def valid_principal(principal_id):
    return isinstance(principal_id, str) and bool(_PRINCIPAL.fullmatch(principal_id))


@dataclass(frozen=True)
class Principal:
    id: str
    tenant_id: str
    roles: tuple
    scopes: tuple           # repository identifiers or '*' for the whole tenant

    def __post_init__(self):
        if not valid_principal(self.id) or not valid_tenant(self.tenant_id):
            raise ValueError('invalid principal or tenant id')
        if not self.roles or any(role not in ROLES for role in self.roles):
            raise ValueError('unknown role')
        if not self.scopes or any(not isinstance(scope, str) or not scope for scope in self.scopes):
            raise ValueError('principal requires repository scopes')


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


def authorize(principal, *, tenant_id, action, repository=None):
    if principal is None:
        return Decision(False, 'unknown-principal')
    if principal.tenant_id != tenant_id:
        return Decision(False, 'cross-tenant-access')
    if action not in ACTIONS:
        return Decision(False, 'unknown-action')
    if not any(action in ROLES[role] for role in principal.roles):
        return Decision(False, 'role-lacks-permission')
    if repository is not None and '*' not in principal.scopes and repository not in principal.scopes:
        return Decision(False, 'repository-outside-principal-scope')
    return Decision(True, 'allowed')


@dataclass(frozen=True)
class Quota:
    max_runs_per_day: int = 500
    max_stored_bytes: int = 1_000_000_000

    def __post_init__(self):
        if any(type(v) is not int or v < 1 for v in (self.max_runs_per_day, self.max_stored_bytes)):
            raise ValueError('quota limits must be positive integers')


def quota_decision(quota, *, runs_today, stored_bytes, incoming_bytes):
    if runs_today >= quota.max_runs_per_day:
        return Decision(False, 'daily-run-quota-exhausted')
    if stored_bytes + incoming_bytes > quota.max_stored_bytes:
        return Decision(False, 'storage-quota-exhausted')
    return Decision(True, 'within-quota')


def expired(created_at, retention_days, now):
    """A result is purged once it is older than the tenant's retention period."""
    if type(retention_days) is not int or retention_days < 1:
        raise ValueError('retention_days must be a positive integer')
    return datetime.fromisoformat(created_at) + timedelta(days=retention_days) <= now


_SECRET = re.compile(r'(?i)(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9-]{20,}'
                     r'|(?:token|secret|password|api[_-]?key)\s*[=:]\s*\S+|Bearer\s+\S+)')


def redact(text):
    """Remove token-like material before anything enters the audit log."""
    return _SECRET.sub('[redacted]', str(text))[:2000]
