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


def update_removed_key_policy(path: str | Path, action: str, key: str, expected_source: str) -> dict:
    """Apply a confirmed exception; preserve unrelated YAML and reject stale scans."""
    import os
    import re
    import stat
    import tempfile

    import yaml

    from drift_gate.adapters.snapshot import read_bounded_text
    from drift_gate.core.policy.loader import load_policy_from_text
    root = repository_root(path)
    target = root / POLICY_FILE
    source = read_bounded_text(target)
    if source != expected_source:
        raise ValueError('검사 후 정책 파일이 바뀌었습니다. 다시 검사한 뒤 설정해 주세요.')
    policy = load_policy_from_text(source)
    if action not in {'exclude', 'disable'} or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
        raise ValueError('알 수 없는 삭제 키 설정입니다.')
    option = 'exclude_removed_keys' if action == 'exclude' else 'check_removed_keys'
    value = sorted(set(policy.exclude_removed_keys) | {key}) if action == 'exclude' else False
    text = yaml.safe_dump(value, default_flow_style=True).split('\n...')[0].strip()
    node = yaml.compose(source)
    entry = next((v for k, v in node.value if k.value == option), None)
    if entry is None:
        updated = source.rstrip('\n') + f'\n{option}: {text}\n'
    else:
        start, end = entry.start_mark.index, entry.end_mark.index
        # Block lists consume their trailing newline; retain the following key.
        newline = '\n' if source[start:end].endswith('\n') else ''
        updated = source[:start] + text + newline + source[end:]
    load_policy_from_text(updated)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n', dir=root,
                                         prefix='.drift-gate-policy-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(updated)
        os.chmod(temporary, stat.S_IMODE(target.stat().st_mode))
        if read_bounded_text(target) != source:
            raise ValueError('정책 파일이 바뀌었습니다. 다시 검사해 주세요.')
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {'repository': str(root), 'path': str(target), 'action': action, 'key': key}
