"""W11 dependency impact and service identity, W05 whole-scope no-delta certificates, W12 budget."""
from hashlib import sha256
import json
import subprocess

import pytest

from drift_gate.adapters.scope_analysis import analyze_scope
from drift_gate.core.budget import InspectionBudget, ResourceLimit
from drift_gate.core.contracts.dependency import build_graph, impact

POLICY = '''rules:
  - id: api
    when: {any_changed: ["services/**"]}
    require: {groups: [{name: docs, any_changed: ["docs/**"]}]}
    severity: major
services:
  - {id: billing, paths: ["services/billing/**"], entrypoints: ["services/billing/main.py"]}
  - {id: shipping, paths: ["services/shipping/**"], entrypoints: ["services/shipping/main.py"]}
'''


def route(path, method='get', extra=''):
    return f'from fastapi import FastAPI\nimport os\napp = FastAPI()\n@app.{method}("{path}")\ndef h():\n    return 1\n{extra}'


def git(root, *args):
    return subprocess.check_output(['git', '-c', 'core.autocrlf=false', *args], cwd=root, stderr=subprocess.PIPE)


def commit(root, files, message):
    for path, text in files.items():
        target = root / path
        if text is None:
            target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8', newline='\n')
    git(root, 'add', '-A')
    git(root, '-c', 'user.name=F', '-c', 'user.email=f@example.invalid', 'commit', '-q', '-m', message)
    return git(root, 'rev-parse', 'HEAD').decode().strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init', '-q')
    base = commit(tmp_path, {
        '.drift-gate.yml': POLICY,
        'services/billing/main.py': 'from services.billing import api\nfrom services.billing import config\n',
        'services/billing/api.py': route('/health'),
        'services/billing/config.py': 'import os\nLIMIT = os.getenv("BILLING_LIMIT")\n',
        'services/billing/consumer.py': 'from services.billing import config\n',
        'services/shipping/main.py': 'from services.shipping import api\n',
        'services/shipping/api.py': route('/ship'),
        'docs/api.md': 'GET /health\n'}, 'base')
    return tmp_path, base


def run(root, base, head, **kwargs):
    return analyze_scope(root=root, base=base, head=head, trusted_policy_ref=base,
                         trusted_policy_sha256=sha256(POLICY.encode()).hexdigest(), **kwargs)


def cert(data, service, family):
    return next(row for row in data['no_delta_certificates'] if row['service_id'] == service and row['family'] == family)


def test_same_route_in_two_services_is_two_facts_and_moves_are_not_merged(repo):
    root, base = repo
    head = commit(root, {'services/billing/api.py': route('/health', extra='@app.get("/ship")\ndef s():\n    return 2\n'),
                         'services/shipping/api.py': 'x = 1\n'}, 'move /ship to billing')
    data = run(root, base, head)
    services = data['services']
    assert ['billing', 'services/billing/main.py', 'GET', '/ship'] in services['added_routes']
    assert ['shipping', 'services/shipping/main.py', 'GET', '/ship'] in services['removed_routes']
    assert services['moved_between_services'] == [{'route': ['GET', '/ship'], 'from_service': 'shipping',
                                                   'to_service': 'billing'}]
    assert cert(data, 'shipping', 'api-route')['certified'] is False


def test_env_key_moved_within_a_service_is_not_a_new_service_key(repo):
    root, base = repo
    head = commit(root, {'services/billing/consumer.py': 'import os\nfrom services.billing import config\nX = os.getenv("BILLING_LIMIT")\n',
                         'services/shipping/api.py': route('/ship', extra='T = os.getenv("BILLING_LIMIT")\n')},
                  'consumer reads existing key; another service starts using the same key')
    services = run(root, base, head)['services']
    assert ['billing', 'services/billing/consumer.py', 'BILLING_LIMIT'] in services['consumer_env_additions']
    assert ['billing', 'BILLING_LIMIT'] in services['consumer_additions_of_existing_service_keys']
    assert services['service_new_env_keys'] == [['shipping', 'BILLING_LIMIT']]  # a separate obligation


def test_unchanged_consumer_and_deleted_edge_are_in_the_impact_scope(repo):
    root, base = repo
    head = commit(root, {'services/billing/config.py': 'import os\nLIMIT = os.getenv("BILLING_LIMIT")\nNEW = 1\n',
                         'services/billing/main.py': 'from services.billing import api\n'}, 'main stops importing config')
    dependency = run(root, base, head)['dependency']
    assert 'services/billing/consumer.py' in dependency['affected']  # unchanged consumer
    assert 'services/billing/main.py' in dependency['affected']      # consumer only via the deleted edge
    assert ['services/billing/main.py', 'services/billing/config.py'] in dependency['removed_edges']


def test_no_delta_certificate_requires_closure_and_unambiguous_services(repo):
    root, base = repo
    head = commit(root, {'services/billing/api.py': route('/health') + '# comment only\n'}, 'comment')
    data = run(root, base, head)
    assert cert(data, 'billing', 'api-route')['certified'] is True
    assert cert(data, 'billing', 'env-key')['certified'] is True
    dynamic = commit(root, {'services/billing/plugin.py': 'import importlib\nm = importlib.import_module(NAME)\n'},
                     'dynamic import')
    refused = cert(run(root, base, dynamic), 'billing', 'api-route')
    assert refused['certified'] is False and 'open_dependency_scope' in refused['reason_codes']
    stray = commit(root, {'tools/route.py': route('/stray')}, 'module outside every service')
    data = run(root, dynamic, stray)
    assert 'ambiguous_service_scope' in cert(data, 'billing', 'api-route')['reason_codes']
    assert ['tools/route.py', 'unassigned'] in data['services']['ambiguous_service_scope']


def test_cycles_are_terminated_and_reported():
    graph = build_graph({'a.py': 'import b\n', 'b.py': 'import c\n', 'c.py': 'import a\n', 'd.py': 'import a\n'})
    scope = impact(graph, graph, ['c.py'])
    assert ['a.py', 'b.py', 'c.py'] in scope.to_dict()['cycles']
    assert set(scope.affected) == {'a.py', 'b.py', 'c.py', 'd.py'}


def test_js_relative_require_and_dynamic_require_boundaries():
    graph = build_graph({'web/app.js': "const r = require('./routes');\nconst m = require(name);\nimport x from 'express';\n",
                         'web/routes/index.js': 'module.exports = 1\n'})
    assert ('web/app.js', 'web/routes/index.js') in graph.edges
    kinds = {(b.kind, b.detail) for b in graph.boundaries}
    assert ('dynamic-import', 'non-literal require/import') in kinds and ('external', 'express') in kinds


def test_budget_limits_whole_collection_and_reports_usage(repo):
    root, base = repo
    head = commit(root, {'services/billing/api.py': route('/health') + '#x\n'}, 'x')
    tight = InspectionBudget.from_policy(None)
    tight.limits['max_git_calls'] = 3
    with pytest.raises(ResourceLimit) as limit:
        run(root, base, head, budget=tight)
    assert limit.value.to_dict()['unit'] == 'git_calls'
    data = run(root, base, head)
    assert data['budget']['usage']['git_calls'] > 0 and data['budget']['usage']['bytes'] > 0


def test_cli_check_reports_budget_and_rejects_over_limit(repo, monkeypatch, capsys):
    from drift_gate.adapters.cli.runner import run_cli
    root, base = repo
    head = commit(root, {'services/billing/api.py': route('/v2')}, 'route')
    policy = POLICY + 'budget: {max_files: 1}\n'
    tightened = commit(root, {'.drift-gate.yml': policy}, 'tighten budget')
    monkeypatch.chdir(root)
    with pytest.raises(SystemExit) as exit:
        run_cli(['check', '--base', base, '--head', head, '--trusted-policy-ref', base, '--trusted-policy-sha256',
                 sha256(POLICY.encode()).hexdigest(), '--json'])
    data = json.loads(capsys.readouterr().out)
    assert data['execution']['budget']['usage']['git_calls'] > 0
    over = commit(root, {'services/billing/api.py': route('/v3'), 'services/shipping/api.py': route('/s2')}, 'two files')
    with pytest.raises(SystemExit) as exit:
        run_cli(['check', '--base', tightened, '--head', over, '--trusted-policy-ref', tightened,
                 '--trusted-policy-sha256', sha256(policy.encode()).hexdigest(), '--json'])
    error = json.loads(capsys.readouterr().out)['error']
    assert exit.value.code == 2 and error['code'] == 'resource_limit' and error['resource']['unit'] == 'files'


def test_isolated_workers_produce_the_same_scope_facts(repo):
    root, base = repo
    head = commit(root, {'services/billing/api.py': route('/health', extra='@app.post("/pay")\ndef p():\n    return 1\n')},
                  'add route')
    inline, isolated = run(root, base, head), run(root, base, head, isolated=True)
    assert isolated['analysis_boundary'] == 'isolated-worker-processes' and not isolated['worker_failures']
    assert inline['services'] == isolated['services']
    assert inline['no_delta_certificates'] == isolated['no_delta_certificates']



def test_policy_memory_budget_reaches_isolated_workers(tmp_path, monkeypatch):
    from drift_gate.adapters import analyzer_worker
    seen = []
    real = analyzer_worker.WorkerPool

    class Recording(real):
        def __init__(self, **kwargs):
            seen.append(kwargs['limits'])
            super().__init__(**kwargs)

    monkeypatch.setattr(analyzer_worker, 'WorkerPool', Recording)
    policy = POLICY + 'budget: {max_memory_bytes: 900000000}\n'
    git(tmp_path, 'init', '-q')
    base = commit(tmp_path, {'.drift-gate.yml': policy, 'services/billing/main.py': 'import os\n',
                             'services/billing/api.py': route('/health')}, 'base')
    head = commit(tmp_path, {'services/billing/api.py': route('/v2')}, 'route change')
    report = analyze_scope(root=tmp_path, base=base, head=head, trusted_policy_ref=base,
                           trusted_policy_sha256=sha256(policy.encode()).hexdigest(), isolated=True)
    assert seen and all(limits['max_memory_bytes'] == 900_000_000 for limits in seen)
    platform = __import__('sys').platform
    # Reported by the worker itself: Linux sets every limit, macOS cannot bound memory, Windows has no rlimits.
    expected = ([] if platform.startswith('linux') else ['memory'] if platform == 'darwin'
                else ['cpu', 'file-size', 'memory', 'open-files'])
    assert report['worker_limits_unapplied'] == expected and not report['worker_failures']
