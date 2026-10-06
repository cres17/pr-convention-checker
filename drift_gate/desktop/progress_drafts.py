"""Local recovery copies, separate from confirmed baselines and history."""
import hashlib
import json
import math
import re
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path

from drift_gate.desktop.json_store import write_json
from drift_gate.desktop.progress_documents import archived_documents
from drift_gate.desktop.progress_limits import MAX_BACKUP_BYTES, MAX_DRAFT_BYTES, MAX_RECOVERY_REQUIREMENTS, MAX_REQUIREMENTS
from drift_gate.desktop.store_lock import store_lock


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
    if base is not None and (not isinstance(base, dict) or 'edit_base' in base or not _valid_draft(base) or len(base.get('requirements', [])) > MAX_REQUIREMENTS):
        return False
    if base is not None and any(item.get('evidence') is not None and (
        type(item['evidence']['line']) is not int or item['evidence']['line'] < 0) for item in base['requirements']):
        return False
    if 'repository' in draft and not isinstance(draft['repository'], str):
        return False
    if 'version' in draft and (type(draft['version']) is not int or draft['version'] < 0):
        return False
    kinds = draft.get('document_kinds', {})
    if not isinstance(kinds, dict) or not all(isinstance(path, str) and kind in
        ('current', 'future', 'past', 'reference') for path, kind in kinds.items()):
        return False
    items = draft.get("requirements")
    try:
        archived_documents(draft)
    except ValueError:
        return False
    if not isinstance(items, list) or len(items) > MAX_RECOVERY_REQUIREMENTS:
        return False
    ids = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item['id'] or item["id"] in ids:
            return False
        ids.add(item["id"])
        if not all(isinstance(item.get(field), str) for field in (
            "title", "criterion", "area", "implementation_status", "verification_status", "verification_note"
        )) or not isinstance(item.get("included"), bool):
            return False
        if item['implementation_status'] not in ('unknown', 'partial', 'implemented', 'not_implemented') or item['verification_status'] not in ('unverified', 'verified'):
            return False
        source = item.get("source")
        if not isinstance(source, dict) or not all(isinstance(source.get(field), str) for field in (
            "path", "excerpt", "sha256"
        )) or type(source.get("line")) is not int or source['line'] < 0:
            return False
        evidence = item.get("evidence")
        if evidence is not None and (not isinstance(evidence, dict) or not all(
            isinstance(evidence.get(field), str) for field in ("path", "note")
        ) or "line" not in evidence or not _draft_line(evidence["line"])):
            return False
        if evidence is not None and any(key in evidence and not isinstance(evidence[key], str) for key in ('excerpt', 'sha256')):
            return False
        for key in ('implementation_note', 'source_key'):
            if key in item and not isinstance(item[key], str):
                return False
        for key in ('stale_evidence', 'stale_requirement', 'doc_marked_done'):
            if key in item and not isinstance(item[key], bool):
                return False
        reviewed = item.get('reviewed_documents', {})
        patterns = item.get('test_patterns', [])
        if not isinstance(reviewed, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in reviewed.items()):
            return False
        if not isinstance(patterns, list) or not all(isinstance(pattern, str) for pattern in patterns):
            return False
        if item.get('doc_claim') not in (None, 'unbacked') or ('effective_status' in item and item['effective_status'] not in
            ('unknown', 'partial', 'implemented', 'not_implemented', 'excluded')):
            return False
        duplicates = item.get('duplicates', [])
        if not isinstance(duplicates, list) or len(duplicates) > 20 or not all(isinstance(place, dict) and all(
            isinstance(place.get(key), str) for key in ('path', 'excerpt', 'criterion')) and
            type(place.get('line')) is int and place['line'] >= 0 for place in duplicates):
            return False
    return True


def _checkout_draft(root: Path, draft: dict) -> dict:
    """Bind optional legacy presentation paths to this recovery envelope."""
    repository = str(root.resolve())
    base = draft.get('edit_base')
    if draft.get('repository', repository) != repository or (base is not None and
            base.get('repository', repository) != repository):
        raise ValueError('초안과 원래 편집 기준의 프로젝트가 일치하지 않습니다.')
    result = {**draft, 'repository': repository}
    if base is not None:
        result['edit_base'] = {**base, 'repository': repository}
    return result


def _draft_payload(root: Path, draft: dict) -> dict:
    # Export and recovery use the same envelope and fixed-width timestamp. The
    # file that passes export's size limit must also fit when imported again.
    return {"schema": 1, "repository": str(root.resolve()),
            "updated_at": datetime.now(timezone.utc).isoformat(timespec='microseconds'), "draft": draft}


class DraftSession:
    """Hold a lease until the app closes. All lease operations use the repository gate."""

    def __init__(self, root: Path, data_dir: Path, owner: str):
        self.target = draft_file(root, data_dir, owner)
        if not owner:
            raise ValueError('실행 식별자가 필요합니다.')
        self.gate = draft_file(root, data_dir)
        self.lease = self.target.with_suffix('.live')
        self._held = None

    def start_locked(self):
        if self._held is None:
            held = store_lock(self.lease, timeout=0)
            held.__enter__()
            self._held = held

    def close(self):
        if self._held is None:
            return True
        try:
            with store_lock(self.gate, timeout=0):
                self._release()
                self.lease.with_suffix('.live.lock').unlink(missing_ok=True)
            return True
        except OSError:
            # Closing must not wait for another writer. Release the lease but
            # leave its inode for the next gated recovery lookup to clean up.
            self._release()
            return False

    def _release(self):
        held, self._held = self._held, None
        if held is not None:
            held.__exit__(None, None, None)


def _active_locked(target: Path) -> bool:
    lease = target.with_suffix('.live')
    lock = lease.with_suffix('.live.lock')
    if not lock.exists():
        return False
    try:
        with store_lock(lease, timeout=0):
            pass
    except TimeoutError:
        return True
    # Lease acquisition/probing/removal share the repository gate; no waiters
    # can retain this inode. Persistent transaction gates are never removed.
    lock.unlink(missing_ok=True)
    return False


def cache_draft(root: Path, data_dir: Path, draft: dict, owner: str = '', session: DraftSession | None = None, *, backup: bool = False) -> None:
    if not _valid_draft(draft):
        raise ValueError("편집 초안의 형식이 올바르지 않습니다.")
    draft = _checkout_draft(root, draft)
    payload = _draft_payload(root, draft)
    if len(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")) > (MAX_BACKUP_BYTES if backup else MAX_DRAFT_BYTES):
        raise ValueError("편집 초안이 보관 상한을 넘었습니다. 자동 보관은 2MB, 복구 파일은 16MB까지 지원합니다. 초안 파일로 내보내기를 사용해 주세요.")
    target = draft_file(root, data_dir, owner)
    with store_lock(draft_file(root, data_dir)):
        if session is not None:
            if session.target != target:
                raise ValueError('초안 실행과 프로젝트가 일치하지 않습니다.')
            session.start_locked()
        write_json(target, payload)


def recovery_copy(root: Path, data_dir: Path, baseline: dict | None, selected: str = '') -> dict:
    with store_lock(draft_file(root, data_dir)):
        return _recovery_copy_locked(root, data_dir, baseline, selected)


def _recovery_copy_locked(root: Path, data_dir: Path, baseline: dict | None, selected: str) -> dict:
    legacy = draft_file(root, data_dir)
    active = {}
    for lock in legacy.parent.glob(legacy.stem + '.*.live.lock'):
        name = lock.name.removesuffix('.live.lock') + '.json'
        if _recovery_name(legacy, name):
            active[name] = _active_locked(legacy.parent / name)
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
    options = [{'key': copy.name, 'updated_at': datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
                'revision': _revision(info), 'bytes': info.st_size, 'active': active.get(copy.name, False)}
               for copy, info in copies]
    context = {'recovery_key': target.name, 'recovery_revision': _revision(metadata), 'recovery_options': options}
    try:
        if target.stat().st_size > MAX_BACKUP_BYTES:
            raise ValueError("초안 크기 상한 초과")
        payload = json.loads(target.read_text(encoding="utf-8"))
        draft = payload.get("draft")
        if payload.get("schema") != 1 or payload.get("repository") != str(root.resolve()) or not _valid_draft(draft):
            raise ValueError("초안 형식 불일치")
        draft = _checkout_draft(root, draft)
    except (ValueError, AttributeError, OSError, RecursionError):
        return {**context, "recovery_warning": "보관된 초안을 읽지 못했습니다. 확정된 기준은 유지했습니다. 초안을 삭제하고 다시 편집할 수 있습니다."}
    # Recover explicitly, including when another app has since updated the baseline.
    changed = draft.get("version", 0) != (baseline or {}).get("version", 0)
    return {**context, "recovery": {**draft, "repository": str(root.resolve())},
            "recovery_warning": "초안 보관 후 확정된 기준이 달라졌습니다. 복구한 내용을 검토한 뒤 저장해 주세요." if changed else ""}


def discard_draft(root: Path, data_dir: Path, owner: str = '') -> None:
    target = draft_file(root, data_dir, owner)
    with store_lock(draft_file(root, data_dir)):
        target.unlink(missing_ok=True)


def _recovery_name(legacy: Path, name: str) -> bool:
    return name == legacy.name or bool(re.fullmatch(re.escape(legacy.stem) + r'\.[0-9a-f]{32}\.json', name))


def _revision(metadata) -> str:
    return f'{metadata.st_mtime_ns}:{metadata.st_size}'


def discard_recovery(root: Path, data_dir: Path, key: str, revision: str = '') -> None:
    discard_recoveries(root, data_dir, [{'key': key, 'revision': revision}])


def discard_recoveries(root: Path, data_dir: Path, selections: list) -> None:
    """Validate every selected revision and lease before removing any copy."""
    if not isinstance(selections, list) or not selections:
        raise ValueError('삭제할 초안을 선택해 주세요.')
    legacy = draft_file(root, data_dir)
    with store_lock(legacy):
        targets = set()
        for selection in selections:
            if not isinstance(selection, dict):
                raise ValueError('초안 선택 형식이 올바르지 않습니다.')
            key, revision = selection.get('key'), selection.get('revision')
            if not isinstance(key, str) or not _recovery_name(legacy, key):
                raise ValueError('선택한 초안이 이 프로젝트의 사본이 아닙니다.')
            if not isinstance(revision, str) or not revision:
                raise ValueError('초안 수정 버전이 필요합니다. 목록을 새로고침해 주세요.')
            target = legacy.parent / key
            if _active_locked(target):
                raise ValueError('다른 실행에서 편집 중인 초안은 삭제할 수 없습니다. 해당 앱을 닫고 목록을 새로고침해 주세요.')
            if target.is_file() and _revision(target.stat()) != revision:
                raise ValueError('선택한 초안에 새 편집이 보관됐습니다. 초안 목록을 새로고침하고 다시 확인해 주세요.')
            targets.add(target)
        for target in targets:
            target.unlink(missing_ok=True)


def export_draft(root: Path, draft: dict, target: Path) -> None:
    if not _valid_draft(draft):
        raise ValueError('편집 초안의 형식이 올바르지 않습니다.')
    draft = _checkout_draft(root, draft)
    payload = _draft_payload(root, draft)
    if len(json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')) > MAX_BACKUP_BYTES:
        raise ValueError('초안 파일이 백업 상한(16MB)을 넘었습니다. 내용을 정리한 뒤 다시 내보내 주세요.')
    write_json(target, payload)
    if json.loads(target.read_text(encoding='utf-8')) != payload:
        raise OSError('내보낸 초안 파일을 확인하지 못했습니다.')


def import_draft(root: Path, data_dir: Path, source: Path) -> str:
    """Read a bounded backup and add a new recovery copy, never a baseline."""
    with source.open('rb') as stream:
        content = stream.read(MAX_BACKUP_BYTES + 1)
    if len(content) > MAX_BACKUP_BYTES:
        raise ValueError('초안 파일이 불러오기 상한(16MB)을 넘었습니다.')
    def reject_constant(value):
        raise ValueError(f'유효하지 않은 JSON 숫자입니다: {value}')
    try:
        payload = json.loads(content.decode('utf-8-sig'), parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError('초안 파일의 JSON 형식이 올바르지 않습니다.') from exc
    if not isinstance(payload, dict) or type(payload.get('schema')) is not int or payload['schema'] != 1:
        raise ValueError('지원하지 않는 초안 파일 형식입니다.')
    repository = str(root.resolve())
    if payload.get('repository') != repository:
        raise ValueError('다른 프로젝트의 초안입니다. 원래 프로젝트를 연결한 뒤 불러와 주세요.')
    draft = payload.get('draft')
    if not _valid_draft(draft):
        raise ValueError('편집 초안의 형식이 올바르지 않습니다.')
    draft = _checkout_draft(root, draft)
    # External recovery metadata must never authorize deletion of another copy.
    draft = {key: value for key, value in draft.items() if key not in ('recovery_key', 'recovery_revision')}
    owner = uuid.uuid4().hex
    cache_draft(root, data_dir, draft, owner, backup=True)
    return draft_file(root, data_dir, owner).name
