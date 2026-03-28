"""
.drift-gate.yml 정책 파일 로더.
I/O는 파일 읽기만. 외부 API 없음.
"""
from pathlib import Path
from typing import Union

from drift_gate.core.models.policy import Policy, Rule


class PolicyLoadError(Exception):
    """정책 파일 로드/검증 실패."""


def load_policy(path: Union[str, Path]) -> Policy:
    """
    YAML 파일에서 Policy 객체를 로드.
    require.groups 없는 규칙은 PolicyLoadError.
    """
    try:
        import yaml
    except ImportError:
        raise PolicyLoadError("pyyaml 필요: pip install pyyaml")

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"정책 파일 없음: {path}")

    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        raise PolicyLoadError(f"정책 파일 파싱 실패: {e}") from e

    policy = Policy.from_dict(data)
    _validate(policy)
    return policy


def _validate(policy: Policy) -> None:
    for rule in policy.rules:
        if not rule.require.groups:
            raise PolicyLoadError(
                f"rule '{rule.id}'에 require.groups 없음. "
                "require.groups는 최소 1개 이상의 묶음을 정의해야 합니다."
            )
