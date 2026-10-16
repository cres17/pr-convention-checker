"""Org command execution; errors are handled by the common CLI boundary."""
import json
from pathlib import Path
import sys

from drift_gate.adapters.cli.output import write_stdout as _write_stdout


def run(args):
    from drift_gate.adapters.org_service import OrgService
    from drift_gate.core.org.policy import Quota
    service, op = OrgService(args.root), args.operation
    if op == 'create-tenant':
        service.create_tenant(args.tenant, admin_id=args.actor, retention_days=args.retention_days,
                              quota=Quota(args.max_runs_per_day, args.max_stored_bytes))
        data = {'tenant': args.tenant, 'admin': args.actor}
    elif op == 'add-principal':
        service.add_principal(args.actor, args.tenant, args.principal, roles=args.roles, scopes=args.scopes)
        data = {'principal': args.principal}
    elif op == 'store':
        result = json.loads(Path(args.result_json).read_text(encoding='utf-8'))
        data = {'result_id': service.store_result(args.actor, args.tenant, args.repository, result)}
    elif op == 'list':
        data = {'results': service.list_results(args.actor, args.tenant, args.repository)}
    elif op == 'delete':
        service.delete_result(args.actor, args.tenant, args.result_id)
        data = {'deleted': args.result_id}
    elif op == 'purge':
        data = {'removed': service.purge(args.actor, args.tenant)}
    elif op == 'audit':
        data = {'audit': service.audit_log(args.actor, args.tenant)}
    elif op == 'backup':
        data = {'archive_sha256': service.backup(args.actor, args.tenant, args.archive)}
    elif op == 'restore':
        service.restore(args.actor, args.tenant, args.archive, expected_sha256=args.archive_sha256)
        data = {'restored': args.tenant}
    else:
        service.set_retention(args.actor, args.tenant, args.retention_days)
        data = {'retention_days': args.retention_days}
    _write_stdout(json.dumps(data, ensure_ascii=False, indent=2))
    sys.exit(0)


