"""Collect key-name evidence for configured environment sample documents."""
from dataclasses import replace
from pathlib import Path

from drift_gate.core.evaluation.contracts import env_keys_in_document
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.adapters.docs.structured import normalize_openapi_yaml
from drift_gate.adapters.snapshot import read_bounded_text


def attach_env_documents(files, policy, read_text):
    paths = {path for rule in policy.rules for group in rule.require.groups
             if group.content in {"env-keys", "api-schema", "auto-strict", "api-routes", "auto"}
             for path in (group.any_changed or group.all_changed) if not any(c in path for c in '*?[]')}
    schema_paths = {path for rule in policy.rules for group in rule.require.groups
                    if group.content in {"api-schema", "api-routes", "auto-strict", "auto"}
                    for path in (group.any_changed or group.all_changed)}
    # Glob groups inspect only already collected changed documents. No
    # unbounded repository traversal or remote listing is implied.
    from drift_gate.utils.glob_matcher import matches_any
    for file in files:
        if matches_any(file.path, list(schema_paths)):
            paths.add(file.path)
    by_path = {file.path: file for file in files}
    for path in sorted(paths):
        file = by_path.get(path, ChangedFile(path=path, status="unchanged"))
        text, normalized, error = None, None, ''
        try:
            text = None if file.status == "deleted" else read_text(path)
            state = "available" if text is not None else "missing"
            keys = sorted(env_keys_in_document(text)) if text is not None else []
            if text is not None and matches_any(path, list(schema_paths)) and path.lower().endswith(('.yaml', '.yml')):
                normalized = normalize_openapi_yaml(text)
        except (OSError, ValueError, RuntimeError):
            keys = None
            state = "unavailable"
            error = 'Document could not be read or safely decoded'
        by_path[path] = replace(file, documented_env_keys=keys,
                                document_input_state=state,
                                after_source=text,
                                document_json=normalized, document_error=error)
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
        return read_bounded_text(target)
    return read
