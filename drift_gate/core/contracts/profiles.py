"""Immutable descriptions of existing static subsets, not framework certification."""
from dataclasses import dataclass

from drift_gate.core.models.facts import ContractFamily


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be nonempty text')


def _strings(values, label):
    if not isinstance(values, (tuple, list)) or not values:
        raise ValueError(f'{label} must be nonempty text entries')
    for value in values:
        _text(value, label)
    return tuple(sorted(set(values)))


@dataclass(frozen=True)
class ContractProfile:
    id: str
    version: str
    family: ContractFamily
    languages: tuple[str, ...]
    content_mode: str
    analyzer_key: str
    analysis_boundary: str
    input_requirements: tuple[str, ...]

    def __post_init__(self):
        for name in ('id', 'version', 'analyzer_key', 'analysis_boundary'):
            _text(getattr(self, name), name)
        if not isinstance(self.family, ContractFamily):
            raise ValueError('family must be a ContractFamily')
        expected = {ContractFamily.API_ROUTE: 'api-routes',
                    ContractFamily.API_RESPONSE: 'api-schema', ContractFamily.ENV_KEY: 'env-keys'}
        if self.content_mode != expected[self.family]:
            raise ValueError('content mode does not match the contract family')
        object.__setattr__(self, 'languages', _strings(self.languages, 'languages'))
        object.__setattr__(self, 'input_requirements', _strings(self.input_requirements, 'input requirements'))

    @property
    def ref(self):
        return self.id, self.version


@dataclass(frozen=True)
class ProfileRegistry:
    profiles: tuple[ContractProfile, ...]

    def __post_init__(self):
        if not isinstance(self.profiles, (tuple, list)) or not self.profiles:
            raise ValueError('registry requires profiles')
        references, domains = set(), set()
        for profile in self.profiles:
            if not isinstance(profile, ContractProfile) or profile.ref in references:
                raise ValueError('registry requires unique profile references')
            references.add(profile.ref)
            for language in profile.languages:
                key = language, profile.family
                if key in domains:
                    raise ValueError('ambiguous language/family profile selection')
                domains.add(key)
        object.__setattr__(self, 'profiles', tuple(sorted(self.profiles, key=lambda item: item.ref)))

    def find(self, language, family):
        _text(language, 'language')
        if not isinstance(family, ContractFamily):
            raise ValueError('family must be a ContractFamily')
        return next((profile for profile in self.profiles
                     if language in profile.languages and family == profile.family), None)


DEFAULT_REGISTRY = ProfileRegistry((
    ContractProfile('python-env-literals', '1', ContractFamily.ENV_KEY, ('python',),
                    'env-keys', 'python-env-discovery-v1',
                    'Explicit os/getenv accesses in selected complete modules; no imported-consumer closure',
                    ('complete-before-after-source',)),
    ContractProfile('python-fastapi-routes', '1', ContractFamily.API_ROUTE, ('python',),
                    'api-routes', 'python-route-v1',
                    'Existing bounded same-module FastAPI registration and router composition',
                    ('complete-before-after-source',)),
    ContractProfile('python-response-primitives', '2', ContractFamily.API_RESPONSE, ('python',),
                    'api-schema', 'python-response-v2',
                    'Explicit response_model contracts; existing same-module primitive subset',
                    ('complete-before-after-source',)),
    ContractProfile('express-registered-routes', '1', ContractFamily.API_ROUTE,
                    ('javascript', 'typescript', 'tsx'), 'api-routes', 'express-registration-v1',
                    'Existing bounded same-module Express registrations; adapter-provided identities',
                    ('complete-before-after-adapter-route-facts',)),
))
