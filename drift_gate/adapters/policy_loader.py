"""Policy file loading adapter."""
from pathlib import Path
from typing import Union

from drift_gate.core.policy.loader import PolicyLoadError, load_policy_from_text
from drift_gate.core.models.policy import Policy
from drift_gate.adapters.snapshot import read_bounded_text


def load_policy(path: Union[str, Path]) -> Policy:
    """Read a policy file and delegate parsing/validation to core."""
    return read_policy(path)[1]


def require_check_policy(policy: Policy) -> Policy:
    """Reject empty inspection policies without restricting configuration tools."""
    if not policy.rules:
        raise PolicyLoadError(
            'check requires at least one configured rule; use init/doctor to configure a policy'
        )
    return policy


def read_policy(path: Union[str, Path]):
    """Return the exact source and parsed object from one bounded read."""
    policy_path = Path(path)
    if not policy_path.exists():
        raise FileNotFoundError(f"policy file not found: {policy_path}")
    try:
        text = read_bounded_text(policy_path)
    except (OSError, ValueError, UnicodeError) as exc:
        raise PolicyLoadError(f"failed to read policy file: {exc}") from exc
    return text, load_policy_from_text(text)
