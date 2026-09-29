"""Read-only project-goal inventory with explicitly reviewed evidence.

Markdown and source text are data. Nothing found by a text search is treated as
proof of implementation or successful verification.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from drift_gate.desktop.doc_links import (
    MAX_ISSUES,
    fenced_lines as _fenced_lines,
    find_broken_references,
)

MAX_DOC_BYTES = 256_000
MAX_DOCS = 150
MAX_REQUIREMENTS = 120
MAX_DUPLICATES = 20
STATUSES = frozenset({"unknown", "partial", "implemented", "not_implemented"})
MAX_SOURCE_BYTES = 512_000
EXCLUDED_PARTS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "__pycache__",
}
SOURCE_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".java",
    ".kt",
    ".swift",
    ".rs",
    ".vue",
}
CHECKBOX = re.compile(r"^\s*[-*+]\s+\[([ xX])\]\s+(.+?)\s*$")
HEADING = re.compile(r"^#{2,3}\s+(.+?)\s*#*\s*$")
BACKTICK = re.compile(r"`([^`\n]+)`")
TABLE_DIVIDER = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$")


class FieldError(ValueError):
    """A validation problem tied to one input field of a requirement."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


class BaselineError(ValueError):
    """Every invalid requirement of a save attempt, so the UI can mark each one."""

    def __init__(self, errors: list[dict]):
        self.errors = errors
        first = errors[0]["message"]
        super().__init__(
            first
            if len(errors) == 1
            else f"{len(errors)}개 항목을 확인해 주세요. 첫 오류: {first}"
        )


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _table_requirements(lines: list[str]):
    """Yield rows only from tables with an explicit completion criterion column."""
    for index in range(len(lines) - 2):
        if not lines[index].lstrip().startswith("|") or not TABLE_DIVIDER.match(
            lines[index + 1]
        ):
            continue
        headers = [
            cell.replace("**", "").strip() for cell in _table_cells(lines[index])
        ]
        if "완료 조건" not in headers:
            continue
        criterion_index = headers.index("완료 조건")
        title_index = next(
            (
                headers.index(name)
                for name in ("기능", "단계", "요구사항", "항목")
                if name in headers
            ),
            0,
        )
        row = index + 2
        while row < len(lines) and lines[row].lstrip().startswith("|"):
            cells = _table_cells(lines[row])
            if len(cells) > max(criterion_index, title_index):
                title = cells[title_index].replace("**", "").strip()
                criterion = cells[criterion_index].replace("**", "").strip()
                if title and criterion:
                    yield row + 1, lines[row], title[:240], criterion[:500]
            row += 1


def repository_root(path: str | Path) -> Path:
    """Top-level folder of the Git repository containing ``path``."""
    return _repository(path)


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _repository(path: str | Path) -> Path:
    selected = Path(path).expanduser().resolve()
    if not selected.is_dir():
        raise ValueError("저장소 폴더를 선택해 주세요.")
    result = subprocess.run(
        ["git", "-C", str(selected), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("Git 저장소를 찾지 못했습니다.")
    return Path(result.stdout.strip()).resolve()


def _safe_file(root: Path, relative: str, suffixes: set[str], limit: int) -> Path:
    if not isinstance(relative, str) or not relative or "\x00" in relative:
        raise ValueError("파일 경로가 올바르지 않습니다.")
    raw = Path(relative)
    if (
        raw.is_absolute()
        or ".." in raw.parts
        or any(part in EXCLUDED_PARTS for part in raw.parts)
    ):
        raise ValueError("저장소 안의 허용된 파일을 선택해 주세요.")
    target = root / raw
    if (
        not target.resolve().is_relative_to(root)
        or target.is_symlink()
        or not target.is_file()
    ):
        raise ValueError("선택한 파일을 저장소에서 읽을 수 없습니다.")
    if target.suffix.lower() not in suffixes or target.stat().st_size > limit:
        raise ValueError("파일 형식 또는 크기가 분석 범위를 벗어납니다.")
    return target


def _git_files(root: Path) -> tuple[set[str], set[str]]:
    def run(*args: str) -> set[str]:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", *args],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise ValueError("저장소 파일 목록을 읽지 못했습니다.")
        return {os.fsdecode(value) for value in result.stdout.split(b"\0") if value}

    return run("--cached"), run("--others", "--exclude-standard")


def list_documents(path: str | Path) -> dict:
    root = _repository(path)
    tracked, untracked = _git_files(root)
    docs = []
    omitted = 0
    for relative in sorted(tracked | untracked, key=str.casefold):
        if not relative.lower().endswith(".md"):
            continue
        try:
            target = _safe_file(root, relative, {".md"}, MAX_DOC_BYTES)
        except ValueError:
            omitted += 1
            continue
        if len(docs) >= MAX_DOCS:
            omitted += 1
            continue
        docs.append(
            {
                "path": relative,
                "tracked": relative in tracked,
                "bytes": target.stat().st_size,
            }
        )
    return {"repository": str(root), "documents": docs, "omitted": omitted}


def extract_requirements(path: str | Path, selected: list[str]) -> dict:
    root = _repository(path)
    available = {entry["path"] for entry in list_documents(root)["documents"]}
    if not isinstance(selected, list) or not selected or len(selected) > 10:
        raise ValueError("기준 Markdown을 1~10개 선택해 주세요.")
    if len(set(selected)) != len(selected) or not all(
        item in available for item in selected
    ):
        raise ValueError("선택한 Markdown 파일을 찾지 못했습니다.")
    requirements: list[dict] = []
    seen: dict[str, dict] = {}
    doc_hashes = {}

    def add(item: dict, original: str) -> None:
        """Keep repeated titles as locations of the first item, never drop them."""
        key = re.sub(r"\W+", "", item["title"]).casefold()
        if not key:
            return
        first = seen.get(key)
        if first is None:
            seen[key] = item
            requirements.append(item)
        elif len(first.setdefault("duplicates", [])) < MAX_DUPLICATES:
            first["duplicates"].append(
                {
                    "path": item["source"]["path"],
                    "line": item["source"]["line"],
                    "excerpt": original.strip(),
                    "criterion": item["criterion"],
                }
            )

    def contributed(relative: str) -> bool:
        return any(
            place["path"] == relative
            for item in requirements
            for place in [item["source"], *item.get("duplicates", [])]
        )

    for relative in selected:
        target = _safe_file(root, relative, {".md"}, MAX_DOC_BYTES)
        raw = target.read_bytes()
        doc_hashes[relative] = _hash(raw)
        if len(requirements) >= MAX_REQUIREMENTS:
            continue
        heading = ""
        fallback = []
        source_lines = raw.decode("utf-8-sig", errors="replace").splitlines()
        fenced = _fenced_lines(source_lines)
        # Code samples are not goals: blank them so no parser sees their lines.
        lines = ["" if i in fenced else line for i, line in enumerate(source_lines)]
        for line_no, line in enumerate(lines, 1):
            match = HEADING.match(line)
            if match:
                heading = match.group(1).strip()
                fallback.append((line_no, heading, line))
            match = CHECKBOX.match(line)
            if not match:
                continue
            title = match.group(2).strip()[:240]
            if title:
                candidate = _item(relative, line_no, line, title, heading, doc_hashes[relative])
                # The document's own claim; never evidence, only compared with evidence later.
                candidate["doc_marked_done"] = match.group(1) in "xX"
                add(candidate, line)
            if len(requirements) >= MAX_REQUIREMENTS:
                break
        found = contributed(relative)
        # Prefer rows whose table explicitly names completion conditions.
        # Headings are only a fallback for prose-only documents.
        if not found:
            for line_no, original, title, criterion in _table_requirements(lines):
                candidate = _item(
                    relative, line_no, original, title, "완료 조건 표", doc_hashes[relative]
                )
                candidate["criterion"] = criterion
                add(candidate, original)
                if len(requirements) >= MAX_REQUIREMENTS:
                    break
            found = contributed(relative)
        if not found:
            for line_no, title, original in fallback[:30]:
                add(_item(relative, line_no, original, title, "", doc_hashes[relative]), original)
                if len(requirements) >= MAX_REQUIREMENTS:
                    break
    return {
        "repository": str(root),
        "documents": doc_hashes,
        "requirements": requirements,
        "truncated": len(requirements) >= MAX_REQUIREMENTS,
    }


def _item(
    path: str, line: int, excerpt: str, title: str, area: str, digest: str
) -> dict:
    identity = hashlib.sha256(f"{path}\0{line}\0{title}".encode()).hexdigest()[:16]
    return {
        "id": identity,
        "title": title,
        "criterion": title,
        "area": area,
        "included": True,
        "source": {
            "path": path,
            "line": line,
            "excerpt": excerpt.strip(),
            "sha256": digest,
        },
        "implementation_status": "unknown",
        "evidence": None,
        "verification_status": "unverified",
        "verification_note": "",
    }


_SCP_REMOTE = re.compile(r"^(?:[^@/\s]+@)?([^:/\s]+):(?!//)(.+)$")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")


def normalize_remote(url: str) -> str | None:
    """Host and path of a remote URL, so https/ssh/scp clones of one repo match.

    Credentials, scheme, a trailing ``.git`` and the host's case are dropped.
    Local-path and ``file://`` remotes are not portable identities: None.
    """
    url = url.strip()
    if not url or url.startswith((".", "/", "~")) or _WINDOWS_DRIVE.match(url):
        return None
    if "://" in url:
        scheme, _, rest = url.partition("://")
        if scheme.lower() == "file":
            return None
        host, _, path = rest.partition("/")
    else:
        match = _SCP_REMOTE.match(url)
        if not match:
            return None
        host, path = match.groups()
    host = host.rpartition("@")[2].lower()
    path = re.sub(r"(\.git)?/*$", "", path.strip("/"))
    return f"{host}/{path}" if host and path else None


def _remote_identity(root: Path) -> str | None:
    """Normalized URL of ``origin`` (else the first remote), or None without one."""

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    names = git("remote").split()
    for name in ("origin", *sorted(names)):
        if name in names:
            identity = normalize_remote(git("remote", "get-url", name))
            if identity:
                return identity
    return None


def _legacy_store_file(root: Path, data_dir: Path) -> Path:
    """Baselines saved before remote-based keys were keyed by absolute path."""
    return data_dir / (_hash(str(root).encode())[:24] + ".json")


def _store_file(root: Path, data_dir: Path) -> Path:
    """Keyed by remote URL so moving or re-cloning a project keeps its baseline."""
    remote = _remote_identity(root)
    if remote is None:
        return _legacy_store_file(root, data_dir)
    return data_dir / (_hash(f"remote:{remote}".encode())[:24] + ".json")


def load_baseline(path: str | Path, data_dir: Path) -> dict | None:
    root = _repository(path)
    remote = _remote_identity(root)
    target = _store_file(root, data_dir)
    if not target.is_file():
        target = _legacy_store_file(root, data_dir)
        if remote is None or not target.is_file():
            return None
    data = json.loads(target.read_text(encoding="utf-8"))
    if data.get("schema") != 1:
        raise ValueError("저장된 기준의 형식이 현재 앱과 맞지 않습니다.")
    # Files keyed by remote carry it; path-keyed files must match this folder.
    owner = data.get("remote")
    if (owner != remote) if owner is not None else (data.get("repository") != str(root)):
        raise ValueError("저장된 기준의 형식이 현재 앱과 맞지 않습니다.")
    return data


def _item_errors(
    root: Path, item: dict, docs: dict, doc_lines: dict[str, list[str]]
) -> list[tuple[str, str]]:
    """Validate one requirement; return every (field, message) problem found."""
    errors: list[tuple[str, str]] = []
    for key, label in (("title", "기능 이름"), ("criterion", "완료 조건")):
        value = item.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 500:
            errors.append((key, f"{label}을 500자 이하로 입력해 주세요."))
    source = item.get("source")
    if not isinstance(source, dict) or source.get("path") not in docs:
        errors.append(("source", "기능의 문서 출처가 올바르지 않습니다."))
    elif (
        source.get("sha256") != docs[source["path"]]
        or type(source.get("line")) is not int
    ):
        errors.append(("source", "기능의 문서 출처가 변경됐습니다."))
    else:
        if source["path"] not in doc_lines:
            doc_lines[source["path"]] = (
                _safe_file(root, source["path"], {".md"}, MAX_DOC_BYTES)
                .read_text(encoding="utf-8-sig", errors="replace")
                .splitlines()
            )
        lines = doc_lines[source["path"]]
        if source["line"] == 0:
            if source.get("excerpt") != "사용자가 직접 추가":
                errors.append(("source", "직접 추가한 기능의 출처가 올바르지 않습니다."))
        elif not (1 <= source["line"] <= len(lines)) or lines[
            source["line"] - 1
        ].strip() != source.get("excerpt"):
            errors.append(("source", "기능의 문서 위치가 변경됐습니다."))
    if not isinstance(item.get("doc_marked_done", False), bool):
        errors.append(("source", "문서의 완료 표시 정보가 올바르지 않습니다."))
    duplicates = item.get("duplicates", [])
    if not isinstance(duplicates, list) or len(duplicates) > MAX_DUPLICATES or not all(
        isinstance(place, dict)
        and place.get("path") in docs
        and type(place.get("line")) is int
        for place in duplicates
    ):
        errors.append(("source", "다른 문서의 같은 항목 정보가 올바르지 않습니다."))
    status = item.get("implementation_status")
    if not isinstance(status, str) or status not in STATUSES:
        errors.append(("implementation_status", "구현 상태가 올바르지 않습니다."))
    verification = item.get("verification_status")
    if verification not in {"unverified", "verified"}:
        errors.append(("verification_status", "검증 상태가 올바르지 않습니다."))
    if not isinstance(item.get("included"), bool):
        errors.append(("included", "기능의 포함 여부가 올바르지 않습니다."))
    if status in {"partial", "implemented"}:
        try:
            item["evidence"] = _evidence(root, item.get("evidence"))
        except FieldError as exc:
            errors.append((exc.field, str(exc)))
        except ValueError as exc:
            errors.append(("evidence.path", str(exc)))
    else:
        item["evidence"] = None
    if status == "not_implemented" and not str(item.get("implementation_note", "")).strip():
        errors.append(("implementation_note", "미구현 확인에는 확인 이유가 필요합니다."))
    if verification == "verified":
        if not str(item.get("verification_note", "")).strip():
            errors.append(("verification_note", "수동 검증 확인에는 검증 기록이 필요합니다."))
        if status != "implemented":
            errors.append(("verification_status", "검증 완료는 구현 확인 후 기록해 주세요."))
    return errors


def save_baseline(path: str | Path, data_dir: Path, payload: dict) -> dict:
    root = _repository(path)
    if not isinstance(payload, dict):
        raise ValueError("기준 데이터를 읽지 못했습니다.")
    docs = payload.get("documents")
    items = payload.get("requirements")
    if not isinstance(docs, dict) or not docs or len(docs) > 10:
        raise ValueError("기준 문서를 선택해 주세요.")
    if not isinstance(items, list) or len(items) > MAX_REQUIREMENTS:
        raise ValueError("기능 목록을 확인해 주세요.")
    available = {entry["path"] for entry in list_documents(root)["documents"]}
    for relative, digest in docs.items():
        if (
            relative not in available
            or _hash(_safe_file(root, relative, {".md"}, MAX_DOC_BYTES).read_bytes())
            != digest
        ):
            raise ValueError("기준 문서가 변경됐습니다. 다시 불러와 주세요.")
    ids = set()
    for item in items:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or item["id"] in ids
        ):
            raise ValueError("기능 ID가 중복되거나 올바르지 않습니다.")
        ids.add(item["id"])
    doc_lines: dict[str, list[str]] = {}
    errors = []
    for item in items:
        for field, message in _item_errors(root, item, docs, doc_lines):
            errors.append({"id": item["id"], "field": field, "message": message})
    if errors:
        raise BaselineError(errors)
    previous = load_baseline(root, data_dir)
    remote = _remote_identity(root)
    target = _store_file(root, data_dir)
    # A baseline still stored under the old path key is rewritten under the remote key.
    if (
        previous
        and previous["documents"] == docs
        and previous["requirements"] == items
        and (remote is None or target.is_file())
    ):
        return previous
    unchanged = bool(
        previous
        and previous["documents"] == docs
        and previous["requirements"] == items
    )
    version = (previous["version"] + (0 if unchanged else 1)) if previous else 1
    saved = {
        "schema": 1,
        "repository": str(root),
        "version": version,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "documents": docs,
        "requirements": items,
    }
    if remote is not None:
        saved["remote"] = remote
    data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=data_dir, delete=False
    ) as stream:
        json.dump(saved, stream, ensure_ascii=False, indent=2)
        temporary = Path(stream.name)
    try:
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return saved


def _evidence(root: Path, evidence: object) -> dict:
    if not isinstance(evidence, dict):
        raise FieldError("evidence.path", "구현 확인에는 코드 근거가 필요합니다.")
    relative = evidence.get("path")
    try:
        target = _safe_file(root, relative, SOURCE_SUFFIXES, MAX_SOURCE_BYTES)
    except ValueError as exc:
        raise FieldError("evidence.path", str(exc)) from exc
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    line = evidence.get("line")
    if type(line) is not int or line < 1 or line > len(lines):
        raise FieldError("evidence.line", "코드 근거의 줄 번호를 확인해 주세요.")
    if not lines[line - 1].strip():
        raise FieldError("evidence.line", "내용이 있는 코드 줄을 근거로 선택해 주세요.")
    if not isinstance(evidence.get("note"), str) or not evidence["note"].strip():
        raise FieldError("evidence.note", "이 코드가 완료 조건과 어떻게 연결되는지 적어 주세요.")
    return {
        "path": relative,
        "line": line,
        "excerpt": lines[line - 1].strip()[:240],
        "sha256": _hash(target.read_bytes()),
        "note": evidence["note"].strip()[:1000],
    }


def inspect_progress(path: str | Path, data_dir: Path) -> dict:
    root = _repository(path)
    baseline = load_baseline(root, data_dir)
    if baseline is None:
        raise ValueError("기준 문서를 선택하고 기능 목록을 확정해 주세요.")
    stale_docs = []
    for relative, digest in baseline["documents"].items():
        try:
            current = _hash(
                _safe_file(root, relative, {".md"}, MAX_DOC_BYTES).read_bytes()
            )
        except ValueError:
            current = None
        if current != digest:
            stale_docs.append(relative)
    items = []
    counts = {
        "implemented": 0,
        "partial": 0,
        "not_implemented": 0,
        "unknown": 0,
        "complete": 0,
        "excluded": 0,
    }
    for source in baseline["requirements"]:
        item = dict(source)
        stale_evidence = False
        if item.get("evidence"):
            try:
                stale_evidence = (
                    _evidence(root, item["evidence"])["sha256"]
                    != item["evidence"]["sha256"]
                )
            except ValueError:
                stale_evidence = True
        item["stale_evidence"] = stale_evidence
        if not item["included"]:
            item["effective_status"] = "excluded"
            counts["excluded"] += 1
        else:
            effective = (
                "unknown"
                if stale_evidence or stale_docs
                else item["implementation_status"]
            )
            item["effective_status"] = effective
            counts[effective] += 1
            if item.get("doc_marked_done") and effective != "implemented" and not stale_docs:
                item["doc_claim"] = "unbacked"
            if (
                effective == "implemented"
                and item["verification_status"] == "verified"
                and not stale_docs
            ):
                counts["complete"] += 1
        items.append(item)
    unbacked = sum(1 for entry in items if entry.get("doc_claim") == "unbacked")
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    total = len(items) - counts["excluded"]
    return {
        "repository": str(root),
        "version": baseline["version"],
        "at": datetime.now(timezone.utc).isoformat(),
        "head": head.stdout.strip() if head.returncode == 0 else "커밋 없음",
        "documents": baseline["documents"],
        "stale_documents": stale_docs,
        "counts": counts,
        "total": total,
        "items": items,
        "doc_claims_unbacked": unbacked,
        "limitations": "상태는 사용자가 확정한 코드 근거와 수동 검증 기록 기준입니다. 자동 의미 판정이나 테스트 실행은 아직 제공하지 않습니다.",
    }


def evidence_candidates(path: str | Path, item: dict) -> list[dict]:
    """Suggest only explicitly named source paths; suggestions never change status."""
    root = _repository(path)
    tracked, untracked = _git_files(root)
    available = tracked | untracked
    candidates = []
    for token in BACKTICK.findall(
        f"{item.get('title', '')} {item.get('criterion', '')}"
    ):
        if token not in available or token in {entry["path"] for entry in candidates}:
            continue
        try:
            target = _safe_file(root, token, SOURCE_SUFFIXES, MAX_SOURCE_BYTES)
        except ValueError:
            continue
        first = next(
            (
                (i, line.strip()[:240])
                for i, line in enumerate(
                    target.read_text(encoding="utf-8", errors="replace").splitlines(), 1
                )
                if line.strip()
            ),
            None,
        )
        if first:
            candidates.append({"path": token, "line": first[0], "excerpt": first[1]})
    return candidates[:10]


def check_references(path: str | Path, data_dir: Path) -> dict:
    """Broken links and file paths in the baseline's documents (read-only)."""
    root = _repository(path)
    baseline = load_baseline(root, data_dir)
    if baseline is None:
        raise ValueError("기준 문서를 선택하고 기능 목록을 확정해 주세요.")
    tracked, untracked = _git_files(root)
    files = tracked | untracked
    checked = 0
    issues: list[dict] = []
    for relative in baseline["documents"]:
        try:
            target = _safe_file(root, relative, {".md"}, MAX_DOC_BYTES)
        except ValueError:
            issues.append({"path": relative, "line": 0, "target": relative, "kind": "document",
                           "message": "기준 문서를 읽을 수 없습니다"})
            continue
        lines = target.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        count, found = find_broken_references(relative, lines, root, files)
        checked += count
        issues.extend(found)
    return {
        "documents": list(baseline["documents"]),
        "checked": checked,
        "issues": issues[:MAX_ISSUES],
        "truncated": len(issues) > MAX_ISSUES,
        "limitations": "링크 대상의 존재만 확인합니다. #제목 앵커와 웹 주소는 검사하지 않습니다. 백틱 경로는 `폴더/파일.확장자` 형태만 대상입니다.",
    }
