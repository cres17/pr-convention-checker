"""Policy file loading adapter."""
from pathlib import Path
from typing import Union

from drift_gate.core.policy.loader import PolicyLoadError, load_policy_from_text
from drift_gate.core.models.policy import Policy


def load_policy(path: Union[str, Path]) -> Policy:
    """Read a policy file and delegate parsing/validation to core."""
    policy_path = Path(path)
    if not policy_path.exists():
        raise FileNotFoundError(f"policy file not found: {policy_path}")
    try:
        text = policy_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PolicyLoadError(f"failed to read policy file: {exc}") from exc
    return load_policy_from_text(text)
