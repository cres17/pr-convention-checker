"""Local recovery copies, separate from confirmed baselines and history."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from drift_gate.desktop.progress_service import _write_json

MAX_DRAFT_BYTES = 2_000_000


def draft_file(root: Path, data_dir: Path) -> Path:
    # Worktrees with the same remote must not overwrite each other's drafts.
    key = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:24]
    return data_dir / "drafts" / f"{key}.json"


def _valid_draft(draft: object) -> bool:
    if not isinstance(draft, dict):
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
        ) or type(evidence.get("line")) is not int):
            return False
    return True


def cache_draft(root: Path, data_dir: Path, draft: dict) -> None:
    if not _valid_draft(draft):
        raise ValueError("편집 초안의 형식이 올바르지 않습니다.")
    payload = {"schema": 1, "repository": str(root.resolve()),
               "updated_at": datetime.now(timezone.utc).isoformat(), "draft": draft}
    if len(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")) > MAX_DRAFT_BYTES:
        raise ValueError("편집 초안이 보관 상한(2MB)을 넘었습니다. 기준과 근거 저장을 사용해 주세요.")
    _write_json(draft_file(root, data_dir), payload)


def recovery_copy(root: Path, data_dir: Path, baseline: dict | None) -> dict:
    target = draft_file(root, data_dir)
    if not target.is_file():
        return {}
    try:
        if target.stat().st_size > MAX_DRAFT_BYTES:
            raise ValueError("초안 크기 상한 초과")
        payload = json.loads(target.read_text(encoding="utf-8"))
        draft = payload.get("draft")
        if payload.get("schema") != 1 or payload.get("repository") != str(root.resolve()) or not _valid_draft(draft):
            raise ValueError("초안 형식 불일치")
    except (ValueError, AttributeError, OSError):
        return {"recovery_warning": "보관된 초안을 읽지 못했습니다. 확정된 기준은 유지했습니다. 초안을 삭제하고 다시 편집할 수 있습니다."}
    # Recover explicitly, including when another app has since updated the baseline.
    changed = draft.get("version", 0) != (baseline or {}).get("version", 0)
    return {"recovery": {**draft, "repository": str(root.resolve())},
            "recovery_warning": "초안 보관 후 확정된 기준이 달라졌습니다. 복구한 내용을 검토한 뒤 저장해 주세요." if changed else ""}


def discard_draft(root: Path, data_dir: Path) -> None:
    draft_file(root, data_dir).unlink(missing_ok=True)
