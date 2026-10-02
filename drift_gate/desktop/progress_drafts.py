"""Local recovery copies, separate from confirmed baselines and history."""
import hashlib
import json
import math
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

from drift_gate.desktop.json_store import write_json
from drift_gate.desktop.store_lock import store_lock

MAX_DRAFT_BYTES = 2_000_000


def _draft_line(value):
    # null is the JSON representation of an unfinished/NaN numeric input.
    return value is None or type(value) is int or (type(value) is float and math.isfinite(value))


def draft_file(root: Path, data_dir: Path, owner: str = '') -> Path:
    # Worktrees with the same remote must not overwrite each other's drafts.
    key = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:24]
    if owner:
        if not re.fullmatch('[0-9a-f]{32}', owner):
            raise ValueError('초안 실행 식별자가 올바르지 않습니다.')
        key += '.' + owner
    return data_dir / "drafts" / f"{key}.json"


def _valid_draft(draft: object) -> bool:
    if not isinstance(draft, dict):
        return False
    base = draft.get('edit_base')
    if base is not None and (not isinstance(base, dict) or 'edit_base' in base or not _valid_draft(base)):
        return False
    docs, items = draft.get("documents"), draft.get("requirements")
    if not isinstance(docs, dict) or not 1 <= len(docs) <= 10 or not all(
        isinstance(path, str) and isinstance(digest, str) for path, digest in docs.items()
    ) or not isinstance(items, list) or len(items) > 120:
        return False
    ids = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] in ids:
            return False
        ids.add(item["id"])
        if not all(isinstance(item.get(field), str) for field in (
            "title", "criterion", "area", "implementation_status", "verification_status", "verification_note"
        )) or not isinstance(item.get("included"), bool):
            return False
        source = item.get("source")
        if not isinstance(source, dict) or not all(isinstance(source.get(field), str) for field in (
            "path", "excerpt", "sha256"
        )) or type(source.get("line")) is not int:
            return False
        evidence = item.get("evidence")
        if evidence is not None and (not isinstance(evidence, dict) or not all(
            isinstance(evidence.get(field), str) for field in ("path", "note")
        ) or "line" not in evidence or not _draft_line(evidence["line"])):
            return False
    return True


def cache_draft(root: Path, data_dir: Path, draft: dict, owner: str = '') -> None:
    if not _valid_draft(draft):
        raise ValueError("편집 초안의 형식이 올바르지 않습니다.")
    payload = {"schema": 1, "repository": str(root.resolve()),
               "updated_at": datetime.now(timezone.utc).isoformat(), "draft": draft}
    if len(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")) > MAX_DRAFT_BYTES:
        raise ValueError("편집 초안이 보관 상한(2MB)을 넘었습니다. 기준과 근거 저장을 사용해 주세요.")
    target = draft_file(root, data_dir, owner)
    with store_lock(target):
        write_json(target, payload)


def recovery_copy(root: Path, data_dir: Path, baseline: dict | None, selected: str = '') -> dict:
    legacy = draft_file(root, data_dir)
    copies = []
    for target in legacy.parent.glob(legacy.stem + '*.json'):
        if not _recovery_name(legacy, target.name):
            continue
        try:
            metadata = target.stat()
            if stat.S_ISREG(metadata.st_mode):
                copies.append((target, metadata))
        except OSError:
            continue
    if not copies:
        return {}
    copies.sort(key=lambda copy: (copy[1].st_mtime_ns, copy[0].name), reverse=True)
    target, metadata = next((copy for copy in copies if copy[0].name == selected), copies[0])
    options = [{'key': copy.name, 'updated_at': datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat()}
               for copy, info in copies]
    context = {'recovery_key': target.name, 'recovery_revision': _revision(metadata), 'recovery_options': options}
    try:
        if target.stat().st_size > MAX_DRAFT_BYTES:
            raise ValueError("초안 크기 상한 초과")
        payload = json.loads(target.read_text(encoding="utf-8"))
        draft = payload.get("draft")
        if payload.get("schema") != 1 or payload.get("repository") != str(root.resolve()) or not _valid_draft(draft):
            raise ValueError("초안 형식 불일치")
    except (ValueError, AttributeError, OSError):
        return {**context, "recovery_warning": "보관된 초안을 읽지 못했습니다. 확정된 기준은 유지했습니다. 초안을 삭제하고 다시 편집할 수 있습니다."}
    # Recover explicitly, including when another app has since updated the baseline.
    changed = draft.get("version", 0) != (baseline or {}).get("version", 0)
    return {**context, "recovery": {**draft, "repository": str(root.resolve())},
            "recovery_warning": "초안 보관 후 확정된 기준이 달라졌습니다. 복구한 내용을 검토한 뒤 저장해 주세요." if changed else ""}


def discard_draft(root: Path, data_dir: Path, owner: str = '') -> None:
    target = draft_file(root, data_dir, owner)
    with store_lock(target):
        target.unlink(missing_ok=True)


def _recovery_name(legacy: Path, name: str) -> bool:
    return name == legacy.name or bool(re.fullmatch(re.escape(legacy.stem) + r'\.[0-9a-f]{32}\.json', name))


def _revision(metadata) -> str:
    return f'{metadata.st_mtime_ns}:{metadata.st_size}'


def discard_recovery(root: Path, data_dir: Path, key: str, revision: str = '') -> None:
    legacy = draft_file(root, data_dir)
    if not _recovery_name(legacy, key):
        raise ValueError('선택한 초안이 이 프로젝트의 사본이 아닙니다.')
    target = legacy.parent / key
    with store_lock(target):
        if target.is_file() and revision and _revision(target.stat()) != revision:
            raise ValueError('선택한 초안에 새 편집이 보관됐습니다. 초안 목록을 새로고침하고 다시 확인해 주세요.')
        target.unlink(missing_ok=True)
