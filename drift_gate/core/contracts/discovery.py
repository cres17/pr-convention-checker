"""Profile-scoped discovery and open domains; no policy action or source execution."""
import ast
from dataclasses import dataclass
from enum import Enum

from drift_gate.core.contracts.profiles import DEFAULT_REGISTRY, ProfileRegistry
from drift_gate.core.contracts.input_identity import source_identity
from drift_gate.core.evaluation.analysis_session import AnalysisSession
from drift_gate.core.evaluation.api_schema import _extract_contracts, extract_routes, UnknownResponse
from drift_gate.core.evaluation.environment import environment_facts
from drift_gate.core.evaluation.static_routers import UnsupportedContract
from drift_gate.core.models.facts import ContractFamily, ExactFacts, FactBasis, ReasonCode
from drift_gate.core.route_syntax import HTTP_METHODS


class DiscoveryState(str, Enum):
    CLOSED = 'closed'
    OPEN = 'open'


@dataclass(frozen=True)
class DiscoveryDomain:
    source_path: str
    family: ContractFamily
    profile_ref: tuple[str, str] | None
    state: DiscoveryState
    activated: bool
    evidence_refs: tuple[str, ...]
    reasons: tuple[ReasonCode, ...] = ()

    def __post_init__(self):
        if not isinstance(self.source_path, str) or not self.source_path:
            raise ValueError('domain requires a source path')
        if not isinstance(self.family, ContractFamily) or not isinstance(self.state, DiscoveryState):
            raise ValueError('domain requires typed family and state')
        if type(self.activated) is not bool:
            raise ValueError('activation must be a bool')
        if self.profile_ref is not None and (not isinstance(self.profile_ref, tuple)
                                            or len(self.profile_ref) != 2
                                            or any(not isinstance(item, str) or not item.strip() for item in self.profile_ref)):
            raise ValueError('invalid profile reference')
        if not isinstance(self.evidence_refs, (tuple, list)) or not self.evidence_refs:
            raise ValueError('domain requires evidence references')
        if any(not isinstance(item, str) or not item for item in self.evidence_refs):
            raise ValueError('invalid evidence reference')
        if not isinstance(self.reasons, (tuple, list)) or any(not isinstance(item, ReasonCode) for item in self.reasons):
            raise ValueError('domain requires typed reason codes')
        if self.state == DiscoveryState.CLOSED and (self.profile_ref is None or self.reasons):
            raise ValueError('closed domain requires a profile and no open reasons')
        if self.state == DiscoveryState.OPEN and not self.reasons:
            raise ValueError('open domain requires reasons')
        object.__setattr__(self, 'evidence_refs', tuple(sorted(set(self.evidence_refs))))
        object.__setattr__(self, 'reasons', tuple(sorted(set(self.reasons), key=lambda item: item.value)))

    @property
    def scope_id(self):
        return 'selected-module:' + self.source_path

    def to_dict(self):
        return {'scope_id': self.scope_id, 'source_path': self.source_path, 'family': self.family.value,
                'profile_ref': list(self.profile_ref) if self.profile_ref else None,
                'state': self.state.value, 'activated': self.activated,
                'evidence_refs': list(self.evidence_refs), 'reason_codes': [reason.value for reason in self.reasons]}


@dataclass(frozen=True)
class DiscoveryResult:
    domains: tuple[DiscoveryDomain, ...]
    source_paths: tuple[str, ...]
    requested_families: tuple[ContractFamily, ...]
    legacy_modes: tuple[str, ...] = ()
    legacy_python_error: str = ''
    source_digest: str = ''

    def __post_init__(self):
        if (not isinstance(self.source_digest, str) or self.source_digest and
            (len(self.source_digest) != 64 or any(c not in '0123456789abcdef' for c in self.source_digest))):
            raise ValueError('invalid source identity')
        if not isinstance(self.requested_families, (tuple, list)) or not self.requested_families:
            raise ValueError('discovery requires declared contract families')
        if any(not isinstance(family, ContractFamily) for family in self.requested_families):
            raise ValueError('requested families must be typed')
        if (not isinstance(self.source_paths, (tuple, list))
            or any(not isinstance(path, str) or not path for path in self.source_paths)
            or len(self.source_paths) != len(set(self.source_paths))):
            raise ValueError('source selection must contain unique paths')
        if not isinstance(self.domains, (tuple, list)) or any(not isinstance(domain, DiscoveryDomain) for domain in self.domains):
            raise ValueError('invalid discovery domains')
        keys = [(domain.source_path, domain.family) for domain in self.domains]
        if len(keys) != len(set(keys)) or any(domain.family not in self.requested_families for domain in self.domains):
            raise ValueError('duplicate or undeclared discovery domain')
        if set(keys) != {(path, family) for path in self.source_paths for family in self.requested_families}:
            raise ValueError('a requested domain was omitted')
        if (not isinstance(self.legacy_modes, (tuple, list))
            or any(not isinstance(mode, str) or mode not in {'env-keys', 'api-routes', 'api-schema'} for mode in self.legacy_modes)
            or not isinstance(self.legacy_python_error, str)):
            raise ValueError('invalid compatibility hints')
        object.__setattr__(self, 'domains', tuple(sorted(self.domains, key=lambda domain: (domain.source_path, domain.family.value))))
        object.__setattr__(self, 'source_paths', tuple(sorted(self.source_paths)))
        object.__setattr__(self, 'requested_families', tuple(sorted(set(self.requested_families), key=lambda family: family.value)))
        object.__setattr__(self, 'legacy_modes', tuple(sorted(set(self.legacy_modes))))

    @property
    def candidates(self):
        return tuple(domain for domain in self.domains if domain.activated)

    @property
    def open_domains(self):
        return tuple(domain for domain in self.domains if domain.state == DiscoveryState.OPEN)

    @property
    def closed_domains(self):
        return tuple(domain for domain in self.domains if domain.state == DiscoveryState.CLOSED)

    @property
    def complete_within_selection(self):
        # Per-module profile domains only, not service-wide grouping/closure.
        # Empty input is not a discovery completeness certificate.
        return bool(self.domains) and not self.open_domains

    def to_dict(self):
        return {'schema': 'contract-discovery-v1', 'analysis_boundary': 'selected-modules/profile-subsets',
                'requested_families': [family.value for family in self.requested_families],
                'source_digest': self.source_digest,
                'source_paths': list(self.source_paths), 'service_scope_certified': False,
                'complete_within_selection': self.complete_within_selection,
                'domains': [domain.to_dict() for domain in self.domains],
                'legacy_modes': list(self.legacy_modes), 'legacy_python_error': self.legacy_python_error}


def _language(path):
    suffix = path.rsplit('.', 1)[-1]
    return {'py': 'python', 'js': 'javascript', 'jsx': 'javascript',
            'ts': 'typescript', 'tsx': 'tsx'}.get(suffix, 'unsupported')


def _python_phase(text, session):
    """Return existing candidate hints separately from actual completeness."""
    if text is None:
        return None, 'auto-strict requires complete before/after source'
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None, 'auto-strict source could not be parsed'
    nodes = tuple(ast.walk(tree))
    env = session.resolve('python-env-discovery-v1', text, lambda: environment_facts(text))
    framework = any((isinstance(node, ast.ImportFrom) and node.module
                     and node.module.split('.')[0] == 'fastapi')
                    or (isinstance(node, ast.Import) and any(alias.name.split('.')[0] == 'fastapi' for alias in node.names))
                    for node in nodes)
    decorator = any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and any(isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute)
                            and item.func.attr in HTTP_METHODS for item in node.decorator_list)
                    for node in nodes)
    response = any(isinstance(node, ast.Call) and any(keyword.arg == 'response_model' for keyword in node.keywords)
                   for node in nodes)
    return (env, framework or decorator, response), ''


def discover_contracts(files, *, registry=DEFAULT_REGISTRY, families=tuple(ContractFamily), session=None):
    """Discover all requested domains; unsupported is open, never absent.

    Compatibility hints deliberately preserve current auto selection and do
    not certify new-domain coverage. Document obligations are a later stage.
    """
    if not isinstance(registry, ProfileRegistry):
        raise ValueError('registry must be a ProfileRegistry')
    if not isinstance(families, (tuple, list)) or not families or any(not isinstance(family, ContractFamily) for family in families):
        raise ValueError('requested families must be nonempty typed values')
    families = tuple(sorted(set(families), key=lambda family: family.value))
    files = tuple(files)
    if len({file.path for file in files}) != len(files):
        raise ValueError('duplicate source paths in discovery scope')
    session = session or AnalysisSession()
    domains, legacy, python_error = [], set(), ''
    for file in files:
        language = _language(file.path)
        texts = ('' if file.status == 'added' else file.before_source,
                 '' if file.status == 'deleted' else file.after_source)
        phases = [_python_phase(text, session) for text in texts] if language == 'python' else []
        if phases and not python_error:
            python_error = next((error for _, error in phases if error), '')
        for family in families:
            profile = registry.find(language, family)
            reasons, active = set(), False
            refs = tuple(f'{side}:{file.path}:legacy-selected-input' for side in ('before', 'after'))
            if profile is None or profile != DEFAULT_REGISTRY.find(language, family):
                # Metadata registration does not install an analyzer implementation.
                reasons.add(ReasonCode.UNSUPPORTED_PROFILE)
            elif language != 'python':
                if file.before_routes is None or file.after_routes is None or file.route_analysis_error:
                    reasons.add(ReasonCode.UNSUPPORTED_BINDING)
                else:
                    try:
                        for rows in (file.before_routes, file.after_routes):
                            facts = ExactFacts(FactBasis('selected-module:' + file.path, family,
                                                        profile.id, profile.version, refs), rows)
                            if len(facts.facts) != len(rows):
                                raise ValueError('duplicate adapter identities')
                        active = bool(file.before_routes or file.after_routes)
                    except ValueError:
                        reasons.add(ReasonCode.UNSUPPORTED_BINDING)
            else:
                for text, (phase, error) in zip(texts, phases):
                    if error:
                        reasons.add(ReasonCode.MISSING_SOURCE if text is None else ReasonCode.UNSUPPORTED_BINDING)
                        continue
                    env, routing_hint, response_hint = phase
                    if family == ContractFamily.ENV_KEY:
                        active |= bool(env.keys or env.uncertain)
                        if active:
                            legacy.add(profile.content_mode)
                        if env.uncertain:
                            reasons.add(ReasonCode.UNSUPPORTED_BINDING)
                    else:
                        try:
                            routes = session.resolve('python-route-v1', text, lambda text=text: extract_routes(text))
                        except UnsupportedContract:
                            routes = None
                        if family == ContractFamily.API_ROUTE:
                            active |= bool(routes) or routing_hint and routes is None
                            if routing_hint and (routes is None or routes):
                                legacy.add(profile.content_mode)
                            if routes is None:
                                reasons.add(ReasonCode.UNSUPPORTED_BINDING)
                        else:
                            active |= response_hint
                            if response_hint:
                                legacy.add(profile.content_mode)
                            if routes is None:
                                reasons.add(ReasonCode.UNSUPPORTED_BINDING)
                            elif response_hint:
                                try:
                                    shapes = session.resolve(profile.analyzer_key, text,
                                                             lambda text=text: _extract_contracts(text))
                                    if any(isinstance(shape, UnknownResponse) for shape in shapes.values()):
                                        reasons.add(ReasonCode.UNSUPPORTED_BINDING)
                                except UnsupportedContract:
                                    reasons.add(ReasonCode.UNSUPPORTED_BINDING)
            domains.append(DiscoveryDomain(file.path, family, profile.ref if profile else None,
                                           DiscoveryState.OPEN if reasons else DiscoveryState.CLOSED,
                                           bool(active), refs, tuple(reasons)))
    return DiscoveryResult(tuple(domains), tuple(file.path for file in files), families, tuple(legacy), python_error,
                           source_identity(files))
