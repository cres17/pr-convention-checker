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
    policy = Policy.from_dict(data or {})

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

    try:
        data = yaml.safe_load(text) or {}
    except Exception as exc:
        raise PolicyLoadError(f"failed to parse policy YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise PolicyLoadError("policy YAML root must be a mapping")
    return load_policy_from_dict(data)


def load_policy(data: dict[str, Any] | str) -> Policy:
    """Backward-compatible pure loader for dict or YAML text input."""
    if isinstance(data, dict):
        return load_policy_from_dict(data)
    return load_policy_from_text(data)
