"""
Local git adapter.

This adapter is used by the CLI, so it treats the current working tree as the
review target. That makes local preflight useful before a commit is created.
"""
import subprocess
import os
from pathlib import PurePosixPath
from typing import List, Optional

from drift_gate.core.models.changed_file import ChangedFile


STATUS_MAP = {
    "A": "added",
    "M": "modified",
    "D": "deleted",
}

DEFAULT_MAX_PATCH_BYTES = 256_000
BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz",
    ".tar", ".tgz", ".mp4", ".mov", ".avi", ".woff", ".woff2", ".ttf", ".eot",
    ".pyc", ".exe", ".dll", ".so",
}


def _sanitize_path(raw: str) -> Optional[str]:
    """
    Validate and normalize a file path from git diff output.

    Rejects paths that:
    - Are absolute (start with '/' or contain a drive letter on Windows)
    - Contain path traversal sequences ('..') after normalization
    - Are empty or whitespace-only

    Returns the normalized relative path string, or None if the path is unsafe.
    """
    if not raw or not raw.strip():
        return None

    # Strip leading/trailing whitespace
    path = raw.strip()

    # Reject absolute paths (Unix-style or Windows-style)
    if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
        return None

    # Normalize using PurePosixPath to resolve any '..' components
    try:
        normalized = PurePosixPath(path)
    except (ValueError, TypeError):
        return None

    # Check all parts for '..' traversal
    parts = normalized.parts
    if ".." in parts:
        return None

    # Reconstruct as a clean forward-slash path
    clean = "/".join(parts)
    if not clean:
        return None

    return clean


class GitAdapter:
    def get_changed_files(self, base: str = "HEAD~1") -> List[ChangedFile]:
        """Return files changed between base and the current working tree."""
        diff_base = base
        output = _git_diff_name_status(diff_base)
        if output is None:
            diff_base = "HEAD~1"
            output = _git_diff_name_status(diff_base)
        if output is None:
            return []

        return [
            _with_patch(file, diff_base)
            for file in _parse_name_status(output)
        ]


def _git_diff_name_status(diff_base: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "diff", "--name-status", "--find-renames", diff_base],
            text=True,
            encoding="utf-8",
            errors="replace",
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return None


def _parse_name_status(output: str) -> List[ChangedFile]:
    files = []
    for line in output.splitlines():
        parts = line.split("\t")
        if not parts or not parts[0]:
            continue
        if parts[0].startswith("R") and len(parts) >= 3:
            new_path = _sanitize_path(parts[2])
            old_path = _sanitize_path(parts[1])
            if new_path is None:
                continue
            files.append(ChangedFile(
                path=new_path,
                status="renamed",
                previous_path=old_path,
            ))
        elif len(parts) >= 2:
            safe_path = _sanitize_path(parts[1])
            if safe_path is None:
                continue
            files.append(ChangedFile(
                path=safe_path,
                status=STATUS_MAP.get(parts[0], "modified"),
            ))
    return files


def _with_patch(file: ChangedFile, diff_base: str) -> ChangedFile:
    """Attach per-file unified diff when available."""
    if _is_binary_path(file.path):
        return ChangedFile(
            path=file.path,
            status=file.status,
            previous_path=file.previous_path,
            patch="[binary file skipped]",
        )
    try:
        patch = subprocess.check_output(
            ["git", "diff", "--find-renames", diff_base, "--", file.path],
            text=True,
            encoding="utf-8",
            errors="replace",
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        patch = ""
    if len(patch.encode("utf-8", errors="replace")) > _max_patch_bytes():
        patch = "[large file skipped]"

    return ChangedFile(
        path=file.path,
        status=file.status,
        previous_path=file.previous_path,
        patch=patch,
    )


def _is_binary_path(path: str) -> bool:
    lowered = path.lower()
    return any(lowered.endswith(suffix) for suffix in BINARY_SUFFIXES)


def _max_patch_bytes() -> int:
    raw = os.environ.get("DRIFT_GATE_MAX_PATCH_BYTES", "")
    if not raw:
        return DEFAULT_MAX_PATCH_BYTES
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_MAX_PATCH_BYTES
