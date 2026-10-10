"""Complete static FastAPI routes and format-aware documentation checks."""
from dataclasses import dataclass
from hashlib import sha256
import json

from drift_gate.core.contracts.delta import compare_facts
from drift_gate.core.models.facts import (
    ContractFamily, ExactDelta, ExactFacts, FactBasis, FactOutcome, ReasonCode, UnknownFacts,
)
from drift_gate.core.evaluation.api_schema import extract_routes, UnsupportedContract
from drift_gate.core.evaluation.openapi_document import load_openapi
from drift_gate.core.evaluation.analysis_session import AnalysisSession
from drift_gate.core.evaluation.content_result import ContentCheck, checked, unknown, combine
from drift_gate.core.route_syntax import HTTP_METHODS
from drift_gate.utils.glob_matcher import matches_any


def _registered_route_sets(files, session=None):
    before, after = set(), set()
    session = session or AnalysisSession()
    for file in files:
        if file.path.endswith(('.js', '.jsx', '.ts', '.tsx')):
            if file.before_routes is None or file.after_routes is None or file.route_analysis_error:
                raise UnsupportedContract(file.route_analysis_error or 'complete adapter-analyzed Express routes unavailable')
            old, new = set(file.before_routes), set(file.after_routes)
            if before & old or after & new:
                raise UnsupportedContract('duplicate route identity across modules')
            before.update(old); after.update(new)
            continue
        if not file.path.endswith('.py'):
            raise UnsupportedContract('complete static route analysis currently supports Python FastAPI only')
        old = '' if file.status == 'added' else file.before_source
        new = '' if file.status == 'deleted' else file.after_source
        for text, routes in [(old, before), (new, after)]:
            found = session.resolve('python-route-v1', text, lambda text=text: extract_routes(text))
            if routes & found:
                raise UnsupportedContract('duplicate route identity across modules')
            routes.update(found)
    return before, after


@dataclass(frozen=True)
class RouteFactPair:
    before: FactOutcome
    after: FactOutcome
    diagnostic: str = ''


def analyze_route_facts(files, session=None):
    """Compatibility profile: exactly the selected legacy module scope.

    Exact facts do not assert service-wide discovery/dependency completeness.
    Adapter route facts remain adapter evidence, never raw-source evidence.
    Unsupported scope loses both exact sets, preserving legacy conservative behavior.
    """
    files = tuple(files)
    scope = 'selected-modules:' + sha256(json.dumps(sorted(file.path for file in files)).encode('utf-8', errors='surrogatepass')).hexdigest()

    def basis(side):
        references = []
        for file in files:
            absent = file.status == ('added' if side == 'before' else 'deleted')
            source = getattr(file, side + '_source')
            routes = getattr(file, side + '_routes')
            if absent:
                provenance = 'declared-absence'
            elif source is not None and file.path.endswith('.py'):
                provenance = 'source-sha256:' + sha256(source.encode('utf-8', errors='surrogatepass')).hexdigest()
            elif routes is not None:
                provenance = 'adapter-route-facts'  # An opaque adapter reference, not a source hash.
            else:
                provenance = 'unavailable'
            references.append(f'{side}:{file.path}:{provenance}')
        return FactBasis(scope, ContractFamily.API_ROUTE, 'legacy-complete-routes', '1',
                         tuple(references) or ('legacy:empty-module-selection',))

    old_basis, new_basis = basis('before'), basis('after')
    try:
        before, after = _registered_route_sets(files, session)
    except UnsupportedContract as exc:
        missing = any((file.status != 'added' and file.before_source is None
                       or file.status != 'deleted' and file.after_source is None)
                      and file.path.endswith('.py') for file in files)
        reason = ReasonCode.MISSING_SOURCE if missing else ReasonCode.UNSUPPORTED_BINDING
        return RouteFactPair(UnknownFacts(old_basis, frozenset(), (reason,)),
                             UnknownFacts(new_basis, frozenset(), (reason,)), str(exc))
    return RouteFactPair(ExactFacts(old_basis, before), ExactFacts(new_basis, after))


def complete_route_delta(files, session=None):
    """Legacy API projected from typed facts; unchanged sets/error contract."""
    pair = analyze_route_facts(files, session)
    delta = compare_facts(pair.before, pair.after)
    if not isinstance(delta, ExactDelta):
        raise UnsupportedContract(pair.diagnostic)
    return set(delta.added), set(delta.removed)


def document_routes(file, session=None):
    if file.document_error:
        raise UnsupportedContract(file.document_error)
    if file.after_source is None:
        raise UnsupportedContract('complete API documentation is unavailable')
    if file.path.lower().endswith(('.json', '.yaml', '.yml')):
        text = file.document_json if file.document_json is not None else file.after_source
        if file.path.lower().endswith(('.yaml', '.yml')) and file.document_json is None:
            raise UnsupportedContract('OpenAPI YAML requires safe adapter decoding')
        document = load_openapi(text, session)
        routes = set()
        for path, item in document['paths'].items():
            if not isinstance(path, str) or not path.startswith('/') or not isinstance(item, dict) or '$ref' in item:
                raise UnsupportedContract('invalid or referenced OpenAPI path item')
            for method, operation in item.items():
                if method in {*HTTP_METHODS, 'trace'}:
                    if not isinstance(operation, dict) or '$ref' in operation:
                        raise UnsupportedContract('invalid or referenced OpenAPI operation')
                    routes.add((method.upper(), path))
        return routes
    if not file.path.lower().endswith(('.md', '.markdown', '.txt')):
        raise UnsupportedContract('unsupported API documentation format')
    from drift_gate.core.evaluation.contracts import _routes
    return _routes(file.after_source.splitlines(), docs=True)


def route_document_requirement(group, files, added, removed, session=None):
    mode = group.content
    if not (added or removed):
        return ContentCheck('satisfied', 'not-applicable', 'Complete source establishes no route delta', mode)
    results = []
    for pattern in group.any_changed or group.all_changed:
        checks = []
        for file in files:
            if file.status == 'deleted' or not matches_any(file.path, [pattern]):
                continue
            try:
                if file.document_input_state == 'missing':
                    checks.append(checked(False, 'API documentation is missing', mode))
                else:
                    routes = document_routes(file, session)
                    checks.append(checked(added <= routes and not (removed & routes), 'Complete document route coverage', mode))
            except UnsupportedContract as exc:
                checks.append(unknown(str(exc), mode))
        if not checks:
            checks.append(checked(False, 'API documentation is missing', mode))
        results.append(combine(checks, require_all=False, mode=mode))
    result = combine(results, require_all=bool(group.all_changed), mode=mode)
    labels = [f'add {m} {p}' for m, p in sorted(added)] + [f'remove {m} {p}' for m, p in sorted(removed)]
    return ContentCheck(result.decision, result.verification, result.reason + '; ' + '; '.join(labels), mode)


def strict_auto_requirement(group, triggers, files, session=None):
    from dataclasses import replace
    from drift_gate.core.evaluation.obligations import shadow_legacy_plan
    from drift_gate.core.evaluation.contracts import content_requirement

    triggers = tuple(triggers)
    session = session or AnalysisSession()
    if not triggers:
        # Preserve the legacy direct-call behavior. The new planner rejects an
        # empty request rather than manufacturing a new completeness certificate.
        return route_document_requirement(group, files, set(), set(), session)
    plan = shadow_legacy_plan(group, triggers, files, session)
    discovery = plan.discovery
    # S1-c executes the new planner in shadow. Legacy YAML has no explicit
    # profile/document binding; its diagnostic plan stays visibly unmapped.
    # Only existing compatibility hints affect the current gate.
    if any(not file.path.endswith('.py') for file in triggers):
        if any(file.path.endswith('.py') for file in triggers):
            return unknown('Mixed Python/JS contract scopes require explicit groups', 'auto-strict')
        try:
            added, removed = complete_route_delta(triggers, session)
        except UnsupportedContract as exc:
            return unknown(str(exc), 'auto-strict')
        return route_document_requirement(group, files, added, removed, session)
    if discovery.legacy_python_error:
        return unknown(discovery.legacy_python_error, 'auto-strict')
    kinds = set(discovery.legacy_modes)
    if 'env-keys' in kinds and len(kinds) > 1:
        return unknown('Mixed environment/API contracts require explicit content groups', 'auto-strict')
    if kinds:
        if kinds == {'env-keys'}:
            from drift_gate.core.evaluation.environment import environment_delta
            delta = environment_delta(triggers)
            if not delta.keys and not delta.uncertain:
                return ContentCheck('satisfied', 'not-applicable', 'Complete source establishes no new environment key', 'auto-strict')
        # Schema checking includes route identity; route-only checking does not
        # establish response shape consistency. Do not select alphabetically.
        selected = 'api-schema' if 'api-schema' in kinds else 'env-keys' if 'env-keys' in kinds else 'api-routes'
        result = content_requirement(replace(group, content=selected), triggers, files, session)
        return ContentCheck(result.decision, result.verification, 'auto-strict selected ' + selected + '; ' + result.reason, 'auto-strict')
    try:
        added, removed = complete_route_delta(triggers, session)
    except UnsupportedContract as exc:
        return unknown(str(exc), 'auto-strict')
    return route_document_requirement(group, files, added, removed, session)
