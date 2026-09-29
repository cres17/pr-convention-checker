"""First-run help: preview and create a starter .drift-gate.yml for a repository."""

from __future__ import annotations

from pathlib import Path

from drift_gate.adapters.cli.runner import POLICY_PRESETS, recommend_preset
from drift_gate.adapters.policy_loader import load_policy
from drift_gate.desktop.progress_service import repository_root

POLICY_FILE = ".drift-gate.yml"


def _preset(requested: str) -> str:
    if requested != "auto" and requested not in POLICY_PRESETS:
        raise ValueError("알 수 없는 정책 프리셋입니다.")
    return requested


def preview_policy(path: str | Path, requested: str = "auto") -> dict:
    """What ``drift-gate init`` would write for this repository. Read-only."""
    root = repository_root(path)
    choice = recommend_preset(root, _preset(requested))
    return {
        "repository": str(root),
        "exists": (root / POLICY_FILE).exists(),
        "preset": choice["preset"],
        "presets": ["auto", *sorted(POLICY_PRESETS)],
        "recommendations": choice["recommendations"],
        "policy": POLICY_PRESETS[choice["preset"]],
    }


def create_policy(path: str | Path, requested: str = "auto") -> dict:
    """Write the starter policy at the repository root. Never overwrites a file."""
    root = repository_root(path)
    preset = recommend_preset(root, _preset(requested))["preset"]
    target = root / POLICY_FILE
    try:
        with open(target, "x", encoding="utf-8", newline="\n") as stream:
            stream.write(POLICY_PRESETS[preset])
    except FileExistsError as exc:
        raise ValueError(f"{POLICY_FILE}가 이미 있어 덮어쓰지 않았습니다.") from exc
    try:
        load_policy(target)
    except Exception:
        target.unlink(missing_ok=True)
        raise ValueError("만든 정책 파일을 읽지 못해 삭제했습니다. 프리셋을 바꿔 다시 시도해 주세요.")
    return {"repository": str(root), "path": str(target), "preset": preset}
