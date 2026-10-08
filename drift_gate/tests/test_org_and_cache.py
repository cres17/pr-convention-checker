"""W17 organization service and W15 persistent analysis cache."""
from datetime import datetime, timedelta, timezone
import json
import zipfile

import pytest

from drift_gate.adapters.analysis_cache import AnalysisCache, cache_key, key_inputs
from drift_gate.adapters.org_service import OrgError, OrgService
from drift_gate.core.org.policy import Quota, redact

A, B, C = 'a' * 64, 'b' * 64, 'c' * 64


# -- persistent cache ---------------------------------------------------------------
def inputs(**overrides):
    base = dict(artifact_sha256=A, op='python-routes', profile=('python-fastapi-routes', '1'),
                engine_sha256=B, parser_sha256=C)
    return key_inputs(**{**base, **overrides})


def test_every_key_input_invalidates(tmp_path):
    cache = AnalysisCache(tmp_path)
    assert cache.put(inputs(), status='complete', value=[['GET', '/a']])
    assert cache.get(inputs())['value'] == [['GET', '/a']]
    for change in (dict(engine_sha256='d' * 64), dict(parser_sha256='d' * 64), dict(artifact_sha256='d' * 64),
                   dict(profile=('python-fastapi-routes', '2')), dict(approvals_sha256='e' * 64),
                   dict(limits={'max_files': 1}), dict(op='python-env')):
        assert cache.get(inputs(**change)) is None, change


def test_transient_failures_are_never_cached_and_tampering_is_a_miss(tmp_path):
    cache = AnalysisCache(tmp_path)
    for status in ('timeout', 'crash', 'resource-limit', 'partial'):
        assert cache.put(inputs(), status=status, value=None) is False
    assert cache.get(inputs()) is None
    cache.put(inputs(), status='unsupported', value=None)  # deterministic refusal is reusable
    assert cache.get(inputs())['status'] == 'unsupported'
    path = next((tmp_path / 'entries').rglob('*.json'))
    data = json.loads(path.read_text())
    data['value'] = [['GET', '/forged']]
    path.write_text(json.dumps(data))
    assert cache.get(inputs()) is None and cache.rejected == 1
    cache.put(inputs(), status='complete', value=[['GET', '/a']])  # repaired atomically
    assert cache.get(inputs())['value'] == [['GET', '/a']]
    assert cache_key(inputs()) == path.stem


def test_scope_analysis_reuses_cached_facts_with_identical_results(tmp_path):
    from drift_gate.tests.test_scope_analysis import commit, repo as repo_fixture, route, run
    (tmp_path / 'r').mkdir()
    root, base = repo_fixture.__wrapped__(tmp_path / 'r')
    head = commit(root, {'services/billing/api.py': route('/v2')}, 'route change')
    cold = run(root, base, head, cache_dir=tmp_path / 'cache')
    warm = run(root, base, head, cache_dir=tmp_path / 'cache')
    plain = run(root, base, head)
    assert cold['cache']['stored'] > 0 and warm['cache']['hits'] > 0 and warm['cache']['stored'] == 0
    for key in ('services', 'no_delta_certificates', 'dependency'):
        assert cold[key] == warm[key] == plain[key]


# -- organization service ---------------------------------------------------------------
class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 8, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


@pytest.fixture
def service(tmp_path):
    clock = Clock()
    svc = OrgService(tmp_path / 'store', clock=clock)
    svc.create_tenant('acme', admin_id='alice', quota=Quota(max_runs_per_day=3, max_stored_bytes=10_000),
                      retention_days=30)
    svc.create_tenant('globex', admin_id='gina')
    svc.add_principal('alice', 'acme', 'rob', roles=['runner'], scopes=['acme/api'])
    svc.add_principal('alice', 'acme', 'vic', roles=['viewer'], scopes=['acme/web'])
    svc.add_principal('alice', 'acme', 'aud', roles=['auditor'], scopes=['*'])
    return svc, clock


def test_tenant_isolation_and_repository_scopes(service):
    svc, _ = service
    rid = svc.store_result('rob', 'acme', 'acme/api', {'result': 'fail', 'token': 'ghp_' + 'x' * 30})
    with pytest.raises(OrgError, match='repository-outside-principal-scope'):
        svc.store_result('rob', 'acme', 'acme/web', {'result': 'pass'})
    with pytest.raises(OrgError, match='unknown-principal'):
        svc.list_results('gina', 'acme')  # globex admin has no principal record in acme
    with pytest.raises(OrgError, match='role-lacks-permission'):
        svc.delete_result('rob', 'acme', rid)
    assert svc.list_results('vic', 'acme') == []  # scoped viewer sees nothing outside acme/web
    with pytest.raises(OrgError):
        svc.get_result('vic', 'acme', rid)
    assert svc.get_result('aud', 'acme', rid)['repository'] == 'acme/api'
    with pytest.raises(OrgError, match='invalid-tenant-id'):
        svc.list_results('alice', '../globex')


def test_quota_retention_deletion_and_redacted_audit(service):
    svc, clock = service
    for _ in range(3):
        svc.store_result('rob', 'acme', 'acme/api', {'result': 'pass'})
    with pytest.raises(OrgError, match='daily-run-quota'):
        svc.store_result('rob', 'acme', 'acme/api', {'result': 'pass'})
    clock.now += timedelta(days=1)
    with pytest.raises(OrgError, match='storage-quota'):
        svc.store_result('rob', 'acme', 'acme/api', {'blob': 'x' * 20_000})
    clock.now += timedelta(days=31)
    removed = svc.purge('alice', 'acme')
    assert len(removed) == 3 and svc.list_results('alice', 'acme') == []
    log = svc.audit_log('aud', 'acme')
    actions = [(e['action'], e['outcome']) for e in log]
    assert ('inspection.run', 'denied') in actions and ('retention.purge', 'ok') in actions
    assert 'ghp_' not in json.dumps(log)
    assert redact('Authorization: Bearer abc.def') == 'Authorization: [redacted]'
    with pytest.raises(OrgError, match='role-lacks-permission'):
        svc.audit_log('rob', 'acme')


def test_backup_restore_verifies_pins_inventory_and_tenant(service, tmp_path):
    svc, _ = service
    rid = svc.store_result('rob', 'acme', 'acme/api', {'result': 'fail'})
    digest = svc.backup('alice', 'acme', tmp_path / 'acme.zip')
    with pytest.raises(OrgError, match='backup-target-exists'):
        svc.backup('alice', 'acme', tmp_path / 'acme.zip')
    with pytest.raises(OrgError, match='not-empty'):
        svc.restore('alice', 'acme', tmp_path / 'acme.zip', expected_sha256=digest)
    svc.delete_result('alice', 'acme', rid)
    with pytest.raises(OrgError, match='pin-mismatch'):
        svc.restore('alice', 'acme', tmp_path / 'acme.zip', expected_sha256='0' * 64)
    svc.restore('alice', 'acme', tmp_path / 'acme.zip', expected_sha256=digest)
    assert svc.get_result('alice', 'acme', rid)['result'] == {'result': 'fail'}
    import hashlib
    with pytest.raises(OrgError, match='cross-tenant'):
        svc.restore('gina', 'globex', tmp_path / 'acme.zip', expected_sha256=digest)
    tampered = tmp_path / 'tampered.zip'
    with zipfile.ZipFile(tmp_path / 'acme.zip') as source, zipfile.ZipFile(tampered, 'w') as target:
        for info in source.infolist():
            data = source.read(info.filename)
            target.writestr(info.filename, data.replace(b'"fail"', b'"pass"') if info.filename.startswith('data/results') else data)
    svc.delete_result('alice', 'acme', rid)
    with pytest.raises(OrgError, match='corrupt'):
        svc.restore('alice', 'acme', tampered, expected_sha256=hashlib.sha256(tampered.read_bytes()).hexdigest())
    restored = [e['action'] for e in svc.audit_log('alice', 'acme')]
    assert restored.count('backup.restore') >= 1  # the live audit log was appended, not replaced


def test_cli_org_flow(tmp_path, capsys):
    from drift_gate.adapters.cli.runner import run_cli

    def cli(*args):
        with pytest.raises(SystemExit) as exit:
            run_cli(['org', *args, '--root', str(tmp_path / 's')])
        return exit.value.code, json.loads(capsys.readouterr().out)

    assert cli('create-tenant', '--tenant', 'acme', '--actor', 'alice')[0] == 0
    (tmp_path / 'r.json').write_text('{"result": "pass"}')
    code, stored = cli('store', '--tenant', 'acme', '--actor', 'alice', '--repository', 'acme/api',
                       '--result-json', str(tmp_path / 'r.json'))
    assert code == 0 and stored['result_id']
    code, denied = cli('list', '--tenant', 'acme', '--actor', 'mallory')
    assert code == 2 and 'unknown-principal' in denied['error']['message']
