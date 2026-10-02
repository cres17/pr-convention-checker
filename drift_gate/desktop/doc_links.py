"""Broken relative links and repository file paths written in Markdown.

A relative link or image whose target does not exist is a definite problem
(confidence "high"). A backticked ``dir/file.ext`` path is only a hint (confidence
"low"): documents often name example paths from other projects. It is reported
only if it resolves from neither the repository root, the document's folder, nor
the tail of any repository file. Anchors (``#heading``) and web URLs are not
checked, and code blocks are ignored so examples do not count.
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path
from urllib.parse import unquote

MAX_ISSUES = 200

_INLINE = re.compile(r"!?\[[^\]\n]*\]\(\s*<?([^)\s>]+)>?(?:\s+[\"'][^)]*[\"'])?\s*\)")
_REFERENCE = re.compile(r"^\s{0,3}\[[^\]\n]+\]:\s*<?(\S+?)>?(?:\s+[\"'(].*)?$")
_BACKTICK = re.compile(r"`([^`\n]+)`")
_PATH = re.compile(r"^(?:\./)?[\w.@][\w.\-@]*(?:/[\w.@][\w.\-@]*)+\.[A-Za-z0-9]{1,8}$")
_DOMAIN = re.compile(r"^[\w\-]+\.(?:com|org|net|io|dev|app|kr|co|ai)$", re.IGNORECASE)
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def fenced_lines(lines: list[str]) -> set[int]:
    """Indexes of lines inside (or delimiting) fenced code blocks."""
    fenced: set[int] = set()
    marker = ""
    for index, line in enumerate(lines):
        match = _FENCE.match(line)
        if not marker:
            if match:
                marker = match.group(1)
                fenced.add(index)
        else:
            fenced.add(index)
            if (
                match
                and match.group(1)[0] == marker[0]
                and len(match.group(1)) >= len(marker)
                and not match.group(2).strip()
            ):
                marker = ""
    return fenced


def _normalize(document: str, target: str) -> str | None:
    """Repository-relative path of a link target, or None when it leaves the repository."""
    if target.startswith("/"):
        joined = target.lstrip("/")
    else:
        joined = posixpath.join(posixpath.dirname(document), target)
    normalized = posixpath.normpath(joined)
    if normalized == ".":
        return ""
    return None if normalized == ".." or normalized.startswith("../") else normalized


def _is_external(target: str) -> bool:
    lowered = target.lower()
    return (
        "://" in target
        or target.startswith(("#", "//"))
        or lowered.startswith(("mailto:", "tel:", "data:", "javascript:"))
    )


def _problem(root: Path, files: set[str], lowered: dict[str, str], path: str) -> str | None:
    """Why ``path`` (repository-relative) does not resolve, or None when it does."""
    if not path or path in files or any(f.startswith(path + "/") for f in files):
        return None
    if path.lower() in lowered:
        return f"대소문자가 다릅니다: {lowered[path.lower()]}"
    try:
        # Git-ignored or generated files exist on disk but are not listed by Git.
        if (root / path).resolve().is_relative_to(root.resolve()) and (root / path).exists():
            return None
    except OSError:
        pass
    return "대상을 찾을 수 없습니다"


def find_broken_references(
    document: str, lines: list[str], root: Path, files: set[str]
) -> tuple[int, list[dict]]:
    """Return (checked reference count, issues) for one Markdown document."""
    lowered: dict[str, str] = {}
    for name in files:
        lowered.setdefault(name.lower(), name)
    fenced = fenced_lines(lines)
    checked = 0
    issues: list[dict] = []

    suffixes: set[str] | None = None

    def report(line_no: int, target: str, kind: str, message: str) -> None:
        issues.append(
            {
                "path": document,
                "line": line_no,
                "target": target,
                "kind": kind,
                "confidence": "high" if kind == "link" else "low",
                "message": message,
            }
        )

    for index, line in enumerate(lines):
        if index in fenced:
            continue
        line_no = index + 1
        targets = [m.group(1) for m in _INLINE.finditer(line)]
        reference = _REFERENCE.match(line)
        if reference:
            targets.append(reference.group(1))
        for raw in targets:
            if _is_external(raw):
                continue
            target = unquote(re.split(r"[#?]", raw, maxsplit=1)[0])
            if not target:
                continue
            checked += 1
            normalized = _normalize(document, target)
            problem = (
                "저장소 밖을 가리킵니다"
                if normalized is None
                else _problem(root, files, lowered, normalized)
            )
            if problem:
                report(line_no, raw, "link", problem)
        # Paths in backticks are written as prose, so allow either base directory.
        for match in _BACKTICK.finditer(re.sub(r"\]\([^)]*\)", "", line)):
            token = match.group(1).strip()
            if not _PATH.match(token) or _DOMAIN.match(token.split("/", 1)[0]):
                continue
            checked += 1
            token = token.removeprefix("./")
            candidates = [token, _normalize(document, token)]
            problems = [_problem(root, files, lowered, c) for c in candidates if c]
            if not all(problems):
                continue
            if suffixes is None:
                suffixes = {
                    name.split("/", i)[-1] if i else name
                    for name in files
                    for i in range(name.count("/") + 1)
                }
            if token not in suffixes:
                report(line_no, token, "path", problems[0])
    return checked, issues[:MAX_ISSUES]
