"""
.drift-gate.yml 정책 파일 로더.
I/O는 파일 읽기만. 외부 API 없음.
"""
import sys
from pathlib import Path
from typing import Union

from drift_gate.core.models.policy import Policy


class PolicyLoadError(Exception):
    """정책 파일 로드/검증 실패."""


def load_policy(path: Union[str, Path]) -> Policy:
    """
    YAML 파일에서 Policy 객체를 로드하고 유효성 검사 실행.
    - 오류(error)  → PolicyLoadError 발생
    - 경고(warning) → stderr 출력 후 계속
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

    # 유효성 검사 (validator는 별도 모듈 — 순환 임포트 방지를 위해 지연 임포트)
    from drift_gate.core.policy.validator import validate, PolicyValidationError
    vr = validate(policy)

    for w in vr.warnings:
        print(f"[drift-gate] WARNING: {w}", file=sys.stderr)

    try:
        vr.raise_if_errors()
    except PolicyValidationError as e:
        raise PolicyLoadError(str(e)) from e

    return policy
