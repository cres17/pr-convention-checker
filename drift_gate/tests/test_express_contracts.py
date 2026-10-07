"""Express registration controls and optional real HTTP oracle (fixed fixtures)."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from drift_gate.adapters.ast.express_routes import extract_express_routes
from drift_gate.adapters.inspection import inspect
from drift_gate.core.evaluation.static_routers import UnsupportedContract
from drift_gate.tests.test_logical_contracts import changed, document, policy


def fixture(path='/catalog', prefix='/v1', method='get', mounted=True):
    return ("import express from 'express';\nconst app = express();\nconst router = express.Router();\n"
            "function handler(req, res) { res.send('ok'); }\n"
            f"router.route('{path}').{method}(handler);\n" + (f"app.use('{prefix}', router);\n" if mounted else ''))


@pytest.mark.parametrize('language', ['javascript', 'typescript'])
@pytest.mark.parametrize('method', ['get', 'post', 'put', 'delete'])
def test_express_bound_chains_and_literal_mount(language, method):
    assert extract_express_routes(fixture(method=method), language) == {(method.upper(), '/v1/catalog')}


def test_express_multiple_methods_direct_call_and_parser_failure(monkeypatch):
    text = fixture().replace('.get(handler)', '.get(handler).post(handler)')
    assert extract_express_routes(text) == {('GET', '/v1/catalog'), ('POST', '/v1/catalog')}
    direct = fixture().replace("router.route('/catalog').get(handler)", "router.get('/catalog', handler)")
    assert extract_express_routes(direct) == {('GET', '/v1/catalog')}
    monkeypatch.setattr('drift_gate.adapters.ast.express_routes.get_parser', lambda language: (_ for _ in ()).throw(ValueError('offline')))
    with pytest.raises(UnsupportedContract, match='grammar unavailable'):
        extract_express_routes(text)


def test_typescript_type_only_import_cannot_prove_runtime_framework():
    with pytest.raises(UnsupportedContract, match='type-only'):
        extract_express_routes(fixture().replace('import express', 'import type express'), 'typescript')


@pytest.mark.parametrize('mutation', ['no-import', 'fake-import', 'alias', 'shadow', 'dynamic-prefix', 'dynamic-path',
                                     'path-pattern', 'conditional', 'escape', 'mutation', 'duplicate', 'cycle', 'forward-mount'])
def test_ambiguous_express_scope_cannot_be_verified(mutation):
    text = fixture()
    if mutation == 'no-import': text = text.replace("import express from 'express';", '')
    elif mutation == 'fake-import': text = text.replace("from 'express'", "from 'custom'")
    elif mutation == 'alias': text = text.replace('router.route', 'copy.route') + '\nconst copy = router;'
    elif mutation == 'shadow': text += '\nfunction other(router) { router.get("/fake", handler); }'
    elif mutation == 'dynamic-prefix': text = text.replace("app.use('/v1'", 'app.use(prefix')
    elif mutation == 'dynamic-path': text = text.replace("route('/catalog')", 'route(path)')
    elif mutation == 'path-pattern': text = text.replace('/catalog', '/:id')
    elif mutation == 'conditional': text = text.replace('router.route', 'if (flag) router.route')
    elif mutation == 'escape': text += '\nexport default app;'
    elif mutation == 'mutation': text += '\nrouter.get = custom;'
    elif mutation == 'duplicate': text += '\napp.use("/v1", router);'
    elif mutation == 'cycle': text += '\nrouter.use("/cycle", router);'
    elif mutation == 'forward-mount': text = text.replace('const router = express.Router();', '') + '\nconst router = express.Router();'
    with pytest.raises(UnsupportedContract):
        extract_express_routes(text)


@pytest.mark.parametrize('case', ['path', 'prefix', 'method', 'deleted', 'unmounted', 'unchanged'])
@pytest.mark.parametrize('current', [True, False])
def test_express_semantics_reach_strict_auto(case, current):
    before = fixture()
    after = fixture(path='/products') if case == 'path' else fixture(prefix='/v2') if case == 'prefix' else fixture(method='post') if case == 'method' else '' if case == 'deleted' else fixture(mounted=False) if case == 'unmounted' else before + '\n// no route change\n'
    doc_routes = extract_express_routes(after if current else before)
    paths = {}
    for method, path in doc_routes:
        paths.setdefault(path, {})[method.lower()] = {'responses': {}}
    file = changed(before=before, after=after, status='deleted' if case == 'deleted' else 'modified')
    file.path = 'src/api.js'
    p = policy(mode='auto-strict')
    p.rules[0].when.min_change_intensity = 'route-contract-change'
    result = inspect(changed_files=[file, document(json.dumps({'openapi': '3.0.3', 'paths': paths}))], policy=p)
    assert result.result == ('pass' if current or case == 'unchanged' else 'fail')
    assert result.verification == ('not-applicable' if case == 'unchanged' else 'verified')


@pytest.mark.parametrize('method', ['get', 'post', 'put', 'delete'])
def test_real_express_http_agrees_with_static_chained_paths(tmp_path, method):
    oracle = os.environ.get('DRIFT_GATE_EXPRESS_ORACLE_DIR')
    if not oracle or not shutil.which('node'):
        pytest.skip('set DRIFT_GATE_EXPRESS_ORACLE_DIR to a fixed Express 4.21.2 installation')
    package = Path(oracle) / 'node_modules/express/package.json'
    assert json.loads(package.read_text())['version'] == '4.21.2'
    # Only these authored strings enter the runtime oracle. User code is never
    # imported or run. Dynamic import uses an explicitly pinned test dependency.
    source = fixture(method=method)
    module = source.replace("import express from 'express';", f"import express from {json.dumps(str(package.parent / 'index.js'))};")
    script = tmp_path / 'oracle.mjs'
    script.write_text(module + f"""
const server = app.listen(0, '127.0.0.1');
await new Promise(resolve => server.on('listening', resolve));
try {{
  const base = `http://127.0.0.1:${{server.address().port}}`;
  const statuses = [];
  for (const path of ['/v1/catalog', '/catalog', '/v2/catalog']) {{
    const response = await fetch(base + path, {{method: '{method.upper()}'}});
    statuses.push(response.status);
  }}
  console.log(JSON.stringify(statuses));
}} finally {{ await new Promise(resolve => server.close(resolve)); }}
""")
    result = subprocess.run(['node', str(script)], check=True, capture_output=True, text=True, timeout=15)
    assert json.loads(result.stdout) == [200, 404, 404]
    assert extract_express_routes(source) == {(method.upper(), '/v1/catalog')}
