"""Organization service operations on a local store (design W17).

Tenant data lives under ``tenants/<tenant_id>/`` and is reachable only through
this service, which checks the principal's tenant, role and repository scope on
every call except the operator's ``create_tenant`` bootstrap. Tenant-wide actions
(principals, retention, backup/restore, audit log) need the tenant scope ``*``;
purge and listing act only on results inside the principal's scopes; a grant may
not exceed the grantor's permissions or scopes. Results are stored as given
(keeping raw inputs out is the caller's job); the audit log is a hash-chained
append-only sequence whose details are redacted of token-like material.

Boundaries: this module authorizes a principal it is given. Authenticating that
principal (SSO, tokens) is the host's job; the CLI's ``--actor`` is self-asserted
and suitable only for a trusted operator shell. There is no network listener.
One writer per tenant is assumed; the store is a local filesystem, not a
replicated database.
"""
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid
import zipfile

from drift_gate.adapters.execution import atomic_bytes
from drift_gate.adapters.run_store import Sequence
from drift_gate.core.models.input_manifest import canonical_bytes
from drift_gate.core.org.policy import (
    Principal, Quota, authorize, delegation_decision, expired, in_scope, quota_decision, redact, valid_tenant,
)

BACKUP_SCHEMA = 'org-tenant-backup-v1'
MAX_BACKUP_BYTES = 2_000_000_000


class OrgError(PermissionError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _now():
    return datetime.now(timezone.utc)


class OrgService:
    def __init__(self, root, *, clock=_now):
        self.root = Path(root).absolute()
        self.clock = clock

    # -- layout ------------------------------------------------------------------
    def _tenant(self, tenant_id):
        if not valid_tenant(tenant_id):
            raise OrgError('invalid-tenant-id')
        return self.root / 'tenants' / tenant_id

    def _read(self, path, default=None):
        try:
            return json.loads(Path(path).read_text(encoding='utf-8'))
        except FileNotFoundError:
            return default

    def _write(self, path, data):
        atomic_bytes(path, canonical_bytes(data))

    def _audit(self, tenant_id, actor, action, outcome, **details):
        sequence = Sequence(self._tenant(tenant_id) / 'audit')
        for _ in range(5):
            length = len(sequence.read())
            try:
                sequence.append({'at': self.clock().isoformat(), 'actor': actor, 'action': action, 'outcome': outcome,
                                 'details': {k: redact(v) for k, v in details.items()}}, expected_length=length)
                return
            except Exception:  # Conflict: retry against the new tail
                continue
        raise OrgError('audit-log-contended')

    def _principal(self, tenant_id, principal_id):
        rows = self._read(self._tenant(tenant_id) / 'principals.json', {})
        row = rows.get(principal_id)
        return Principal(row['id'], row['tenant_id'], tuple(row['roles']), tuple(row['scopes'])) if row else None

    def _require(self, actor, tenant_id, action, repository=None):
        decision = authorize(self._principal(tenant_id, actor), tenant_id=tenant_id, action=action,
                             repository=repository)
        if not decision.allowed:
            if self._tenant(tenant_id).exists():
                self._audit(tenant_id, actor, action, 'denied', reason=decision.reason, repository=repository or '')
            raise OrgError(decision.reason)

    # -- tenants and principals ------------------------------------------------------
    def create_tenant(self, tenant_id, *, admin_id, quota=None, retention_days=90):
        directory = self._tenant(tenant_id)
        if directory.exists():
            raise OrgError('tenant-exists')
        quota = quota or Quota()
        directory.mkdir(parents=True, mode=0o700)
        self._write(directory / 'config.json', {'tenant_id': tenant_id, 'retention_days': retention_days,
                                                'quota': {'max_runs_per_day': quota.max_runs_per_day,
                                                          'max_stored_bytes': quota.max_stored_bytes},
                                                'created_at': self.clock().isoformat()})
        Principal(admin_id, tenant_id, ('admin',), ('*',))  # validates the id
        self._write(directory / 'principals.json', {admin_id: {'id': admin_id, 'tenant_id': tenant_id,
                                                               'roles': ['admin'], 'scopes': ['*']}})
        self._audit(tenant_id, admin_id, 'tenant.create', 'ok', retention_days=retention_days)

    def add_principal(self, actor, tenant_id, principal_id, *, roles, scopes):
        self._require(actor, tenant_id, 'principals.manage')
        principal = Principal(principal_id, tenant_id, tuple(roles), tuple(scopes))
        decision = delegation_decision(self._principal(tenant_id, actor), principal.roles, principal.scopes)
        if not decision.allowed:
            self._audit(tenant_id, actor, 'principals.manage', 'denied', reason=decision.reason, principal=principal_id)
            raise OrgError(decision.reason)
        rows = self._read(self._tenant(tenant_id) / 'principals.json', {})
        rows[principal_id] = {'id': principal.id, 'tenant_id': tenant_id, 'roles': list(principal.roles),
                              'scopes': list(principal.scopes)}
        self._write(self._tenant(tenant_id) / 'principals.json', rows)
        self._audit(tenant_id, actor, 'principals.manage', 'ok', principal=principal_id, roles=','.join(roles))

    # -- results ---------------------------------------------------------------------
    def _results(self, tenant_id):
        return self._tenant(tenant_id) / 'results'

    def _usage(self, tenant_id):
        directory = self._results(tenant_id)
        rows = [self._read(path) for path in sorted(directory.glob('*.json'))] if directory.exists() else []
        return rows, None, sum(row['bytes'] for row in rows)

    def store_result(self, actor, tenant_id, repository, result):
        """Store one inspection result (no raw inputs) after authorization and quota checks."""
        self._require(actor, tenant_id, 'inspection.run', repository)
        config = self._read(self._tenant(tenant_id) / 'config.json')
        quota = Quota(**config['quota'])
        payload = canonical_bytes(result)
        _, _, stored = self._usage(tenant_id)
        today = self.clock().date().isoformat()
        usage_path = self._tenant(tenant_id) / 'usage.json'
        usage = self._read(usage_path, {})
        decision = quota_decision(quota, runs_today=usage.get(today, 0), stored_bytes=stored,
                                  incoming_bytes=len(payload))
        if not decision.allowed:
            self._audit(tenant_id, actor, 'inspection.run', 'denied', reason=decision.reason, repository=repository)
            raise OrgError(decision.reason)
        created = self.clock().isoformat()
        result_id = uuid.uuid4().hex  # never derived from content: identical runs stay separate records
        usage[today] = usage.get(today, 0) + 1
        self._write(usage_path, usage)  # runs count even if the result is later deleted
        self._write(self._results(tenant_id) / f'{result_id}.json',
                    {'id': result_id, 'tenant_id': tenant_id, 'repository': repository, 'created_at': created,
                     'result_sha256': sha256(payload).hexdigest(), 'bytes': len(payload), 'result': result})
        self._audit(tenant_id, actor, 'inspection.run', 'ok', repository=repository, result_id=result_id,
                    result_sha256=sha256(payload).hexdigest())
        return result_id

    def list_results(self, actor, tenant_id, repository=None):
        self._require(actor, tenant_id, 'results.read', repository)
        principal = self._principal(tenant_id, actor)
        rows, _, _ = self._usage(tenant_id)
        visible = [row for row in rows if in_scope(principal, row['repository'])]
        if repository is not None:
            visible = [row for row in visible if row['repository'] == repository]
        return [{k: row[k] for k in ('id', 'repository', 'created_at', 'result_sha256', 'bytes')} for row in visible]

    def get_result(self, actor, tenant_id, result_id):
        row = self._read(self._results(tenant_id) / f'{result_id}.json') if result_id.isalnum() else None
        if row is None:
            self._require(actor, tenant_id, 'results.read')
            raise OrgError('result-not-found')
        self._require(actor, tenant_id, 'results.read', row['repository'])
        return row

    def delete_result(self, actor, tenant_id, result_id):
        path = self._results(tenant_id) / f'{result_id}.json'
        row = self._read(path) if result_id.isalnum() else None
        if row is None:
            raise OrgError('result-not-found')
        self._require(actor, tenant_id, 'results.delete', row['repository'])
        path.unlink()
        self._audit(tenant_id, actor, 'results.delete', 'ok', result_id=result_id, result_sha256=row['result_sha256'])

    def set_retention(self, actor, tenant_id, retention_days):
        self._require(actor, tenant_id, 'retention.configure')
        config = self._read(self._tenant(tenant_id) / 'config.json')
        expired('2000-01-01T00:00:00+00:00', retention_days, self.clock())  # validates the value
        config['retention_days'] = retention_days
        self._write(self._tenant(tenant_id) / 'config.json', config)
        self._audit(tenant_id, actor, 'retention.configure', 'ok', retention_days=retention_days)

    def purge(self, actor, tenant_id):
        """Delete expired results within the actor's repository scope; returns the removed IDs."""
        self._require(actor, tenant_id, 'results.delete')
        principal = self._principal(tenant_id, actor)
        config = self._read(self._tenant(tenant_id) / 'config.json')
        rows, _, _ = self._usage(tenant_id)
        removed = []
        for row in rows:
            if in_scope(principal, row['repository']) and expired(row['created_at'], config['retention_days'],
                                                                  self.clock()):
                (self._results(tenant_id) / f"{row['id']}.json").unlink()
                removed.append(row['id'])
        self._audit(tenant_id, actor, 'retention.purge', 'ok', removed=len(removed),
                    scope='tenant' if '*' in principal.scopes else ','.join(principal.scopes))
        return removed

    def audit_log(self, actor, tenant_id):
        self._require(actor, tenant_id, 'audit.read')
        return Sequence(self._tenant(tenant_id) / 'audit').read()  # read() verifies the hash chain

    # -- backup and restore ---------------------------------------------------------------
    def backup(self, actor, tenant_id, archive_path):
        self._require(actor, tenant_id, 'backup.create')
        target = Path(archive_path)
        if target.exists():
            raise OrgError('backup-target-exists')
        directory = self._tenant(tenant_id)
        files = {path.relative_to(directory).as_posix(): path.read_bytes()
                 for path in sorted(directory.rglob('*')) if path.is_file() and not path.name.startswith('.')}
        manifest = {'schema': BACKUP_SCHEMA, 'tenant_id': tenant_id, 'created_at': self.clock().isoformat(),
                    'files': {name: sha256(raw).hexdigest() for name, raw in files.items()}}
        with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json', canonical_bytes(manifest))
            for name, raw in files.items():
                archive.writestr('data/' + name, raw)
        self._audit(tenant_id, actor, 'backup.create', 'ok', files=len(files),
                    manifest_sha256=sha256(canonical_bytes(manifest)).hexdigest())
        return sha256(target.read_bytes()).hexdigest()

    def restore(self, actor, tenant_id, archive_path, *, expected_sha256):
        """Restore into a tenant whose results are empty; verifies the archive pin and every file."""
        self._require(actor, tenant_id, 'backup.restore')
        raw = Path(archive_path).read_bytes()
        if len(raw) > MAX_BACKUP_BYTES or sha256(raw).hexdigest() != expected_sha256:
            raise OrgError('backup-pin-mismatch')
        with zipfile.ZipFile(archive_path) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            if manifest.get('schema') != BACKUP_SCHEMA:
                raise OrgError('unsupported-backup')
            if manifest.get('tenant_id') != tenant_id:
                self._audit(tenant_id, actor, 'backup.restore', 'denied', reason='cross-tenant-restore')
                raise OrgError('cross-tenant-restore')
            names = {info.filename for info in archive.infolist()} - {'manifest.json'}
            if names != {'data/' + name for name in manifest['files']}:
                raise OrgError('backup-inventory-mismatch')
            for name, digest in manifest['files'].items():
                if '..' in Path(name).parts or Path(name).is_absolute():
                    raise OrgError('backup-path-escape')
                if sha256(archive.read('data/' + name)).hexdigest() != digest:
                    raise OrgError('backup-file-corrupt')
            if any(self._results(tenant_id).glob('*.json')):
                raise OrgError('restore-target-not-empty')
            directory = self._tenant(tenant_id)
            staging = Path(tempfile.mkdtemp(prefix='.restore-', dir=directory))
            try:
                for name in manifest['files']:
                    if name.startswith('audit/'):
                        continue  # the live audit log is never replaced; restore is appended to it
                    destination = staging / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(archive.read('data/' + name))
                for path in sorted(staging.rglob('*')):
                    if path.is_file():
                        final = directory / path.relative_to(staging)
                        final.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(path, final)
            finally:
                shutil.rmtree(staging, ignore_errors=True)
        self._audit(tenant_id, actor, 'backup.restore', 'ok', files=len(manifest['files']),
                    backup_created_at=manifest['created_at'])
