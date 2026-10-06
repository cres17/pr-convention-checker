"""
Local git adapter.

This adapter is used by the CLI, so it treats the current working tree as the
review target. That makes local preflight useful before a commit is created.
"""
import subprocess
import os
import hashlib
from pathlib import Path, PurePosixPath
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
    - Are empty or contain a NUL

    Returns the normalized relative path string, or None if the path is unsafe.
    """
    if not raw or "\x00" in raw:
        return None

    # Preserve exact spelling, including leading/trailing whitespace.
    path = raw

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


class GitInputError(ValueError):
    """Git input could not be collected; this is never an empty successful diff."""


class GitAdapter:
    def __init__(self, repo_root: str | Path | None = None):
        self.repo_root = Path(repo_root) if repo_root is not None else None

    def get_changed_files(self, base: str = "HEAD~1", *, comparison_mode: str = 'commit') -> List[ChangedFile]:
        self.repo_root = repository_root(self.repo_root)
        if not base or base.startswith("-"):
            raise GitInputError("비교 기준이 올바르지 않습니다.")
        commit = _git(["rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}"], self.repo_root).decode('ascii').strip()
        if comparison_mode == 'merge-base':
            commit = _git(['merge-base', commit, 'HEAD'], self.repo_root).decode('ascii').strip()
        elif comparison_mode != 'commit':
            raise GitInputError('Unknown comparison mode')
        self.provenance = {'requested_base': base, 'resolved_base': commit,
            'comparison_mode': comparison_mode,
            'head': _git(['rev-parse', 'HEAD'], self.repo_root).decode('ascii').strip(),
            'dirty': bool(_git(['status', '--porcelain'], self.repo_root)),
            'untracked_skipped': _git(['ls-files', '--others', '--exclude-standard', '-z'], self.repo_root).decode('utf-8', errors='replace').strip('\0').split('\0')}
        if self.provenance['untracked_skipped'] == ['']:
            self.provenance['untracked_skipped'] = []
        output = _git(["diff", "--no-ext-diff", "--no-textconv", "--name-status", "-z", "--find-renames", commit, "--"], self.repo_root)
        snapshot_args = ['diff', '--no-ext-diff', '--no-textconv', '--find-renames', commit, '--']
        snapshot = _git(snapshot_args, self.repo_root)
        files = [_with_patch(file, commit, self.repo_root) for file in _parse_name_status(output)]
        if _git(snapshot_args, self.repo_root) != snapshot:
            raise GitInputError('Repository changed during collection; rerun the inspection')
        self.provenance['snapshot_sha256'] = hashlib.sha256(snapshot).hexdigest()
        return files


def repository_root(cwd=None):
    return Path(_git(['rev-parse', '--show-toplevel'], cwd).decode('utf-8').strip())


def _git(args: list[str], cwd: Path | None) -> bytes:
    try:
        return subprocess.check_output(["git", "--literal-pathspecs", *args], cwd=cwd,
                                       stderr=subprocess.PIPE, timeout=30)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        raise GitInputError("Git 변경을 읽지 못했습니다. 저장소와 비교 기준을 확인하고 다시 검사해 주세요.") from exc


def _parse_name_status(output: bytes) -> List[ChangedFile]:
    fields = output.split(b"\0")
    if fields[-1] != b"":
        raise GitInputError("Git 파일 목록이 완전하지 않습니다.")
    fields.pop()
    files = []
    index = 0
    while index < len(fields):
        try:
            status = fields[index].decode('ascii')
            count = 2 if status.startswith(('R', 'C')) else 1
            paths = fields[index + 1:index + 1 + count]
            if len(paths) != count:
                raise ValueError('missing path')
            decoded = [entry.decode('utf-8', errors='strict') for entry in paths]
            if any(_sanitize_path(path) != path for path in decoded):
                raise ValueError('unsafe path')
        except (ValueError, UnicodeError) as exc:
            raise GitInputError("Git 파일 경로를 읽지 못했습니다. UTF-8의 저장소 상대 경로가 필요합니다.") from exc
        files.append(ChangedFile(path=decoded[-1],
            status='renamed' if status.startswith('R') else STATUS_MAP.get(status, 'modified'),
            previous_path=decoded[0] if status.startswith('R') else None))
        index += count + 1
    return files


def _with_patch(file: ChangedFile, diff_base: str, cwd: Path | None = None) -> ChangedFile:
    if _is_binary_path(file.path):
        patch = "[binary file skipped]"
    else:
        paths = [file.previous_path, file.path] if file.previous_path else [file.path]
        patch = _git(["diff", "--no-ext-diff", "--no-textconv", "--find-renames", diff_base, "--", *paths], cwd).decode('utf-8', errors='replace')
        if len(patch.encode('utf-8')) > _max_patch_bytes():
            patch = "[large file skipped]"
    before = after = None
    if file.path.endswith('.py') and not patch.startswith('['):
        old_path = file.previous_path or file.path
        if file.status != 'added':
            size = _git(['cat-file', '-s', f'{diff_base}:{old_path}'], cwd)
            if int(size) <= 1_000_000:
                before = _git(['show', f'{diff_base}:{old_path}'], cwd).decode('utf-8', errors='replace')
        target = cwd / file.path
        if (file.status != 'deleted' and not target.is_symlink()
            and target.resolve().is_relative_to(cwd) and target.stat().st_size <= 1_000_000):
            after = target.read_text(encoding='utf-8', errors='replace')
    return ChangedFile(path=file.path, status=file.status, previous_path=file.previous_path,
                       patch=patch, before_source=before, after_source=after)


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
