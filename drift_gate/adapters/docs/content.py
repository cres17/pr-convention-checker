"""Collect key-name evidence for configured environment sample documents."""
from dataclasses import replace
from pathlib import Path

from drift_gate.core.evaluation.contracts import env_keys_in_document
from drift_gate.core.models.changed_file import ChangedFile


def attach_env_documents(files, policy, read_text):
    paths = {path for rule in policy.rules for group in rule.require.groups
             if group.content == "env-keys" for path in (group.any_changed or group.all_changed)}
    by_path = {file.path: file for file in files}
    for path in sorted(paths):
        file = by_path.get(path, ChangedFile(path=path, status="unchanged"))
        try:
            text = None if file.status == "deleted" else read_text(path)
            keys = sorted(env_keys_in_document(text)) if text is not None else None
        except (OSError, ValueError, RuntimeError):
            keys = None
        by_path[path] = replace(file, documented_env_keys=keys)
    return list(by_path.values())


def local_document_reader(root):
    root = Path(root).resolve()

    def read(path):
        if (root / path).is_symlink():
            raise ValueError("symlink documents are not supported")
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            raise ValueError("document is outside the repository")
        if not target.exists():
            return None
        if target.stat().st_size > 1_000_000:
            raise ValueError("document is too large")
        return target.read_text(encoding="utf-8")
    return read
