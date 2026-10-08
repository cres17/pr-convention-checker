"""Service and entrypoint identity for route and environment facts (design W11).

Route identity is ``(service_id, entrypoint_id, METHOD, path)`` and env identity
is ``(service_id, KEY)``. A module that matches no declared service, or more
than one, is ``ambiguous_service_scope``: its facts are never merged into a
service by path. The same method/path in two services are different facts, and
moving a route between services is a removal in one and an addition in the
other. For env keys a service-wide new key (absent from every module of that
service before) is separated from a consumer-level addition (a module started
reading a key the service already used), so a key moved between files of one
service is not a new obligation.
"""
from dataclasses import dataclass

from drift_gate.utils.glob_matcher import matches_any


@dataclass(frozen=True)
class Service:
    id: str
    paths: tuple
    entrypoints: tuple

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError('service requires an id')
        if not self.paths:
            raise ValueError(f'service {self.id} requires module globs')
        object.__setattr__(self, 'paths', tuple(self.paths))
        object.__setattr__(self, 'entrypoints', tuple(sorted(set(self.entrypoints))))


def services_from_policy(specs):
    services = tuple(Service(spec.id, tuple(spec.paths), tuple(spec.entrypoints)) for spec in specs)
    if len({service.id for service in services}) != len(services):
        raise ValueError('duplicate service id')
    return services


def assign(paths, services):
    """{path: service_id or None}; None means unassigned or ambiguous (with the reason)."""
    assignment, reasons = {}, {}
    for path in sorted(paths):
        owners = [service.id for service in services if matches_any(path, list(service.paths))]
        if len(owners) == 1:
            assignment[path] = owners[0]
        else:
            assignment[path] = None
            reasons[path] = 'unassigned' if not owners else 'multiple-services:' + ','.join(sorted(owners))
    return assignment, reasons


def _reachable(start, forward):
    seen, frontier = {start}, [start]
    while frontier:
        node = frontier.pop()
        for nxt in forward.get(node, ()):
            if nxt not in seen:
                seen.add(nxt); frontier.append(nxt)
    return seen


def entrypoint_membership(services, edges, modules):
    """{module: frozenset(entrypoint ids)} from static reachability per entrypoint."""
    forward = {}
    for source, target in edges:
        forward.setdefault(source, set()).add(target)
    membership = {module: set() for module in modules}
    for service in services:
        for entrypoint in service.entrypoints:
            if entrypoint in modules:
                for module in _reachable(entrypoint, forward):
                    if module in membership:
                        membership[module].add(entrypoint)
    return {module: frozenset(values) for module, values in membership.items()}


@dataclass(frozen=True)
class ServiceFacts:
    routes: frozenset           # (service, entrypoint, METHOD, path)
    env_keys: frozenset         # (service, KEY)
    consumer_env: frozenset     # (service, module, KEY)
    ambiguous: tuple            # ((module, reason), ...)
    open_modules: tuple         # modules whose facts could not be established


def service_facts(module_facts, services, assignment, reasons, membership):
    """``module_facts``: {module: {'routes': set or None, 'env': set or None}} (None = open)."""
    routes, env, consumer, ambiguous, open_modules = set(), set(), set(), [], []
    for module, facts in sorted(module_facts.items()):
        service = assignment.get(module)
        if service is None:
            if facts.get('routes') or facts.get('env') or facts.get('routes') is None or facts.get('env') is None:
                ambiguous.append((module, reasons.get(module, 'unassigned')))
            continue
        if facts.get('routes') is None or facts.get('env') is None:
            open_modules.append(module)
        entrypoints = membership.get(module) or frozenset()
        declared = next(s for s in services if s.id == service).entrypoints
        for method, path in facts.get('routes') or ():
            if not declared:
                routes.add((service, '*', method, path))
            elif not entrypoints:
                ambiguous.append((module, 'route-module-unreachable-from-declared-entrypoints'))
            else:
                routes.update((service, entrypoint, method, path) for entrypoint in sorted(entrypoints))
        for key in facts.get('env') or ():
            env.add((service, key))
            consumer.add((service, module, key))
    return ServiceFacts(frozenset(routes), frozenset(env), frozenset(consumer),
                        tuple(sorted(set(ambiguous))), tuple(sorted(open_modules)))


def compare(before, after):
    """Service-scoped changes; identities never merge across services."""
    def moved(removed, added):
        rows = []
        removed_by_route = {}
        for service, entrypoint, method, path in removed:
            removed_by_route.setdefault((method, path), set()).add(service)
        for service, entrypoint, method, path in added:
            for old in sorted(removed_by_route.get((method, path), set()) - {service}):
                rows.append({'route': [method, path], 'from_service': old, 'to_service': service})
        return rows
    added_routes, removed_routes = after.routes - before.routes, before.routes - after.routes
    service_new_keys = after.env_keys - before.env_keys
    consumer_added = after.consumer_env - before.consumer_env
    moved_within = sorted({(s, k) for s, m, k in consumer_added if (s, k) in before.env_keys})
    return {'schema': 'service-identity-compare-v1',
            'added_routes': sorted(map(list, added_routes)), 'removed_routes': sorted(map(list, removed_routes)),
            'moved_between_services': moved(removed_routes, added_routes),
            'service_new_env_keys': sorted(map(list, service_new_keys)),
            'removed_env_keys': sorted(map(list, before.env_keys - after.env_keys)),
            'consumer_env_additions': sorted(map(list, consumer_added)),
            'consumer_additions_of_existing_service_keys': [list(row) for row in moved_within],
            'ambiguous_service_scope': [list(row) for row in sorted(set(before.ambiguous + after.ambiguous))],
            'open_modules': sorted(set(before.open_modules + after.open_modules)),
            'complete': not (before.ambiguous or after.ambiguous or before.open_modules or after.open_modules)}
