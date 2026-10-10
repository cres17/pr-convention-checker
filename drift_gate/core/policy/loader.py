"""Pure policy parsing and validation helpers.

The core layer accepts policy content that adapters have already read. File
system access belongs in ``drift_gate.adapters``.
"""
from typing import Any

from drift_gate.core.models.policy import Policy


class PolicyLoadError(Exception):
    """Policy parsing or validation failed."""


def load_policy_from_dict(data: dict[str, Any] | None) -> Policy:
    """Build and validate a Policy from a decoded mapping."""
    from drift_gate.core.policy.schema import validate_schema
    try:
        validate_schema(data)
    except ValueError as exc:
        raise PolicyLoadError(str(exc)) from exc
    policy = Policy.from_dict(data)

    from drift_gate.core.policy.validator import PolicyValidationError, validate

    validation = validate(policy)
    policy.load_warnings = list(validation.warnings)
    try:
        validation.raise_if_errors()
    except PolicyValidationError as exc:
        raise PolicyLoadError(str(exc)) from exc
    return policy


def load_policy_from_text(text: str) -> Policy:
    """Parse YAML text and return a validated Policy."""
    try:
        import yaml
    except ImportError as exc:
        raise PolicyLoadError("pyyaml is required: pip install pyyaml") from exc

    if len(text.encode('utf-8')) > 1_000_000:
        raise PolicyLoadError('policy exceeds 1 MB size limit')

    class StrictLoader(yaml.SafeLoader):
        def construct_mapping(self, node, deep=False):
            seen = set()
            for key_node, _ in node.value:
                if key_node.tag == 'tag:yaml.org,2002:merge':
                    raise PolicyLoadError('YAML merge keys are unsupported; use explicit mappings')
                key = self.construct_object(key_node, deep=False)
                if not isinstance(key, str):
                    raise PolicyLoadError('policy keys must be strings')
                if key in seen:
                    raise PolicyLoadError(f'duplicate YAML key: {key}')
                seen.add(key)
            return super().construct_mapping(node, deep=deep)

    try:
        events = list(yaml.parse(text))
        depth = aliases = 0
        for event in events:
            if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
                depth += 1
            elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
                depth -= 1
            elif isinstance(event, yaml.AliasEvent):
                aliases += 1
            if depth > 20 or aliases > 100 or len(events) > 20_000:
                raise PolicyLoadError('policy nesting/alias/node limit exceeded')
        data = yaml.load(text, Loader=StrictLoader)
    except (yaml.YAMLError, RecursionError) as exc:
        raise PolicyLoadError(f"failed to parse policy YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise PolicyLoadError("policy YAML root must be a mapping")
    return load_policy_from_dict(data)


def load_policy(data: dict[str, Any] | str) -> Policy:
    """Backward-compatible pure loader for dict or YAML text input."""
    if isinstance(data, dict):
        return load_policy_from_dict(data)
    return load_policy_from_text(data)
