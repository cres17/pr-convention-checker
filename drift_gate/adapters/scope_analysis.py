"""Whole-repository scope analysis for one base/head pair (design W05/W11/W12).

Reads every Python/JS/TS module of both trees through one ``git cat-file
--batch`` per revision under the inspection budget, then derives: before/after
dependency graphs and the impact scope (W11), service-scoped route/env facts and
their comparison (W11), and per-service no-delta certificates (W05 4.3).
Service declarations come from the pinned trusted policy, never the candidate.
"""
from hashlib import sha256
import os
import subprocess
import time

from drift_gate.adapters.git.client import GitInputError
from drift_gate.adapters.git.immutable import GitObjectReader, _git, _git_environment, _resolve, budget_scope
from drift_gate.core.budget import InspectionBudget, ResourceLimit
from drift_gate.core.contracts import certificates, services as service_model
from drift_gate.core.contracts.dependency import JS, PY, build_graph, impact
from drift_gate.core.evaluation.api_schema import UnsupportedContract, extract_routes
from drift_gate.core.evaluation.environment import environment_facts
from drift_gate.core.policy.loader import load_policy_from_text

MAX_MODULE_BYTES = 1_000_000
PROFILES = {'api-route': ('python-fastapi-routes', '1'), 'env-key': ('python-env-literals', '1')}


def _batch_read(root, oids, budget):
    """{oid: bytes} via one cat-file process; each object is size-checked before use."""
    if not oids:
        return {}
    budget.consume('git_calls', 1, stage='scope-batch-read')
    request = ''.join(oid + '\n' for oid in oids).encode('ascii')
    try:
        completed = subprocess.run(['git', '--no-replace-objects', 'cat-file', '--batch'], cwd=root, input=request,
                                   env=_git_environment(), capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitInputError('Could not batch-read Git objects') from exc
    data, position, objects = completed.stdout, 0, {}
    for oid in oids:
        end = data.index(b'\n', position)
        header = data[position:end].decode('ascii').split()
        if len(header) != 3 or header[0] != oid or header[1] != 'blob':
            raise GitInputError('Unexpected batch object')
        size = int(header[2])
        start = end + 1
        objects[oid] = data[start:start + size]
        position = start + size + 1
        budget.consume('bytes', size, stage='scope-batch-read')
    return objects


def _modules(reader, revision):
    catalog = reader.catalog(revision)
    return {path: entry for path, entry in catalog.items()
            if path.endswith(PY + JS) and entry[1] == 'blob' and entry[0] in {'100644', '100755'}
            and '/node_modules/' not in '/' + path and '/.venv/' not in '/' + path}


def _sources(root, reader, revision, budget):
    modules = _modules(reader, revision)
    budget.consume('files', len(modules), stage=f'scope-enumerate-{revision[:12]}')
    oids = sorted({entry[2] for entry in modules.values()})
    objects = _batch_read(root, oids, budget)
    sources, unread = {}, []
    for path, (mode, kind, oid) in sorted(modules.items()):
        raw = objects.get(oid)
        if raw is None or len(raw) > MAX_MODULE_BYTES:
            sources[path] = None
            unread.append(path)
            continue
        try:
            sources[path] = raw.decode('utf-8')
        except UnicodeDecodeError:
            sources[path] = None
            unread.append(path)
    return sources, unread


def _isolated_facts(sources, budget):
    """Per-module Python facts from isolated worker processes (design W12 worker boundary)."""
    from drift_gate.adapters.analyzer_worker import WorkerPool
    pool = WorkerPool(max_workers=min(4, os.cpu_count() or 1), max_queue=10_000,
                      limits={'timeout_seconds': 60, 'max_memory_bytes': budget.limits['max_memory_bytes']})
    facts, failures, unapplied = {}, {}, set()
    for path, text in sources.items():
        if not path.endswith(PY) or text is None:
            facts[path] = {'routes': None, 'env': None}
            continue
        routes = pool.run('python-routes', text)
        env = pool.run('python-env', text)
        budget.check_time('scope-worker')
        unapplied.update(routes.limits_unapplied, env.limits_unapplied)
        if routes.status != 'ok' or env.status != 'ok':
            failures[path] = routes.status if routes.status != 'ok' else env.status
        facts[path] = {'routes': {tuple(row) for row in routes.value} if routes.status == 'ok' and routes.value is not None
                       else None,
                       'env': set(env.value) if env.status == 'ok' and env.value is not None else None}
    return facts, failures, unapplied


def _cached(cache, text, op, compute, engine, parser):
    from drift_gate.adapters.analysis_cache import key_inputs
    if cache is None:
        return compute()
    inputs = key_inputs(artifact_sha256=sha256(text.encode('utf-8')).hexdigest(), op=op,
                        profile=PROFILES['api-route' if op == 'python-routes' else 'env-key'],
                        engine_sha256=engine, parser_sha256=parser)
    entry = cache.get(inputs)
    if entry is not None:
        value = entry['value']
        return None if value is None else set(map(tuple, value)) if op == 'python-routes' else set(value)
    value = compute()
    cache.put(inputs, status='complete' if value is not None else 'unsupported',
              value=None if value is None else sorted(map(list, value)) if op == 'python-routes' else sorted(value))
    return value


def _module_facts(sources, cache=None):
    if cache is not None:
        from drift_gate.adapters.analysis_cache import engine_digest, parser_pins_digest
        engine, parser = engine_digest(), parser_pins_digest()
    else:
        engine = parser = None
    facts = {}
    for path, text in sources.items():
        if not path.endswith(PY):
            # JS/TS facts need the adapter Express/process.env analyzers; keep them open here.
            facts[path] = {'routes': None, 'env': None}
            continue
        if text is None:
            facts[path] = {'routes': None, 'env': None}
            continue
        def routes(text=text):
            try:
                return extract_routes(text)
            except (UnsupportedContract, RecursionError, ValueError):
                return None

        def env(text=text):
            facts = environment_facts(text)
            return None if facts.uncertain else set(facts.keys)

        facts[path] = {'routes': _cached(cache, text, 'python-routes', routes, engine, parser),
                       'env': _cached(cache, text, 'python-env', env, engine, parser)}
    return facts


def analyze_scope(*, root, base, head, trusted_policy_ref, trusted_policy_sha256, policy_path='.drift-gate.yml',
                  budget=None, isolated=False, cache_dir=None):
    budget = budget or InspectionBudget.from_policy(None, clock=time.monotonic)
    with budget_scope(budget):
        reader = GitObjectReader(root)
        base_oid, head_oid, trusted_oid = (_resolve(reader.root, ref) for ref in (base, head, trusted_policy_ref))
        source = reader.text(trusted_oid, policy_path)
        if source is None or sha256(source.encode('utf-8')).hexdigest() != trusted_policy_sha256:
            raise GitInputError('Trusted policy SHA-256 does not match explicit caller pin')
        policy = load_policy_from_text(source)
        if policy.budget is not None:
            budget.limits.update(InspectionBudget.from_policy(policy.budget).limits)
        declared = service_model.services_from_policy(policy.services)
        implicit = not declared
        if implicit:
            declared = (service_model.Service('repository', ('**',), ()),)
        limited = None
        try:
            before_src, before_unread = _sources(reader.root, reader, base_oid, budget)
            after_src, after_unread = _sources(reader.root, reader, head_oid, budget)
            g_before = build_graph(before_src, max_edges=budget.limits['max_graph_edges'])
            g_after = build_graph(after_src, max_edges=budget.limits['max_graph_edges'])
            budget.consume('graph_edges', len(g_before.edges) + len(g_after.edges), stage='scope-graph')
        except ResourceLimit as exc:
            limited = exc
        if limited is not None:
            return {'schema': 'scope-analysis-v1', 'complete': False, 'resource_limit': limited.to_dict(),
                    'budget': budget.to_dict()}
        changed = _git(reader.root, ['diff', '--name-only', '-z', '--no-renames', base_oid, head_oid, '--'])
        seeds = sorted(path for path in changed.decode('utf-8').split('\0') if path)
        scope = impact(g_before, g_after, [seed for seed in seeds if seed in g_before.modules | g_after.modules])
        sides = {}
        cache = None
        if cache_dir is not None:
            from drift_gate.adapters.analysis_cache import AnalysisCache
            cache = AnalysisCache(cache_dir)
        worker_failures, limits_unapplied = {}, set()
        for side, sources, graph in (('before', before_src, g_before), ('after', after_src, g_after)):
            if isolated:
                facts, failed, unapplied = _isolated_facts(sources, budget)
                limits_unapplied |= unapplied
                worker_failures.update({f'{side}:{path}': status for path, status in failed.items()})
            else:
                facts = _module_facts(sources, cache)
            assignment, reasons = service_model.assign(sources, declared)
            membership = service_model.entrypoint_membership(declared, graph.edges, graph.modules)
            sides[side] = (service_model.service_facts(facts, declared, assignment, reasons, membership),
                           assignment, facts)
        comparison = service_model.compare(sides['before'][0], sides['after'][0])
        all_open = {b.module for b in g_before.open_boundaries + g_after.open_boundaries}
        ambiguous = {row[0] for row in comparison['ambiguous_service_scope']}
        unread = set(before_unread) | set(after_unread)
        rows = []
        for service in declared:
            members = {m for side in ('before', 'after') for m, owner in sides[side][1].items() if owner == service.id}
            for family in ('api-route', 'env-key'):
                key = 'routes' if family == 'api-route' else 'env'
                open_members = sorted(m for m in members for side in ('before', 'after')
                                      if m in sides[side][2] and sides[side][2][m][key] is None)
                facts = []
                for side in ('before', 'after'):
                    service_facts = sides[side][0]
                    values = (service_facts.routes if family == 'api-route' else service_facts.env_keys)
                    facts.append(frozenset(v for v in values if v[0] == service.id))
                rows.append(certificates.certify(
                    service_id=service.id, family=family, profile_before=PROFILES[family],
                    profile_after=PROFILES[family], before_facts=facts[0], after_facts=facts[1],
                    modules=len(members), unread_modules=sorted(members & unread), open_modules=sorted(set(open_members)),
                    dependency_open_modules=sorted(members & all_open), ambiguous_modules=sorted(ambiguous),
                    limited=False, before_tree=reader.tree_ids[base_oid], after_tree=reader.tree_ids[head_oid]
                ).to_dict())
        budget.check_time('scope-complete')
        return {'schema': 'scope-analysis-v1', 'complete': True,
                'subject': {'base_oid': base_oid, 'head_oid': head_oid, 'trusted_policy_oid': trusted_oid},
                'service_basis': 'implicit-single-repository-service' if implicit else 'trusted-policy-services',
                'modules': {'before': len(before_src), 'after': len(after_src)},
                'unread_modules': sorted(unread), 'dependency': scope.to_dict(),
                'analysis_boundary': 'isolated-worker-processes' if isolated else 'in-process',
                'worker_failures': worker_failures,
                'worker_limits_unapplied': sorted(limits_unapplied) if isolated else None,
                'cache': cache.stats() if cache is not None else None,
                'services': comparison, 'no_delta_certificates': rows,
                'selection_vs_scope': 'certificates cover every enumerated module of a service, '
                                      'not only the changed selection',
                'budget': budget.to_dict()}
