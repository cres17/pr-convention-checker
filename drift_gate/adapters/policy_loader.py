"""Policy file loading adapter."""
from pathlib import Path
from typing import Union

from drift_gate.core.policy.loader import PolicyLoadError, load_policy_from_text
from drift_gate.core.models.policy import Policy


def load_policy(path: Union[str, Path]) -> Policy:
    """Read a policy file and delegate parsing/validation to core."""
    return read_policy(path)[1]


def read_policy(path: Union[str, Path]):
    """Return the exact source and parsed object from one bounded read."""
    policy_path = Path(path)
    if not policy_path.exists():
        raise FileNotFoundError(f"policy file not found: {policy_path}")
    try:
        if policy_path.stat().st_size > 1_000_000:
            raise PolicyLoadError('policy exceeds 1 MB size limit')
        text = policy_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PolicyLoadError(f"failed to read policy file: {exc}") from exc
    return text, load_policy_from_text(text)
