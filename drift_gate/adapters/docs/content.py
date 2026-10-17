"""Collect key-name evidence for configured environment sample documents."""
from dataclasses import replace
from pathlib import Path

from drift_gate.core.evaluation.contracts import env_keys_in_document
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.adapters.docs.structured import normalize_openapi_yaml
from drift_gate.adapters.snapshot import read_bounded_text


# Bounds for the removed-key reference scan; exceeding one reports the scan as unavailable.
MAX_REFERENCE_KEYS = 50
MAX_REFERENCE_FILES_PER_KEY = 200
MAX_REFERENCE_BYTES = 20_000_000
NO_REPOSITORY_TREE = 'this input has no repository tree to search'


def attach_env_documents(files, policy, read_text, grep=None, *, unavailable_reason=NO_REPOSITORY_TREE):
    """Attach sample-document keys and, for removed keys still documented, where they still occur.

    ``grep(key)`` returns the repository paths (after the change) whose text contains ``key`` as a
    word; ``read_text(path)`` reads one of them. Without ``grep`` the scan is reported unavailable.
    """
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
    return attach_env_references(list(by_path.values()), policy, read_text, grep, unavailable_reason)


def attach_env_references(files, policy, read_text, grep, unavailable_reason=NO_REPOSITORY_TREE):
    from drift_gate.adapters.git.client import GitInputError
    from drift_gate.core.evaluation.env_references import KINDS, classify_reference
    from drift_gate.core.evaluation.environment import environment_delta
    groups = [group for rule in policy.rules for group in rule.require.groups
              if group.content in {'env-keys', 'auto-strict'} and group.check_removed_keys]
    documents = {path for group in groups for path in (group.any_changed or group.all_changed)}
    if not documents:
        return files
    removed = environment_delta([f for f in files if f.path not in documents]).removed
    targets = {f.path: removed & set(f.documented_env_keys) for f in files
               if f.path in documents and f.documented_env_keys and removed & set(f.documented_env_keys)}
    if not targets:
        return files
    keys = sorted(set().union(*targets.values()))
    references, state = {}, 'complete'
    if grep is None:
        state = 'unavailable: ' + unavailable_reason
    elif len(keys) > MAX_REFERENCE_KEYS:
        state = f'unavailable: more than {MAX_REFERENCE_KEYS} removed keys'
    else:
        texts, budget = {}, MAX_REFERENCE_BYTES
        try:
            for key in keys:
                paths = sorted(set(grep(key)) - documents)
                if len(paths) > MAX_REFERENCE_FILES_PER_KEY:
                    raise ValueError(f'{key} occurs in more than {MAX_REFERENCE_FILES_PER_KEY} files')
                found = {kind: [] for kind in KINDS}
                for path in paths:
                    if path not in texts:
                        try:
                            texts[path] = read_text(path)
                        except (OSError, ValueError, UnicodeError):
                            texts[path] = False  # unreadable: the name occurs, its use is unknown
                        budget -= len(texts[path] or '')
                        if budget < 0:
                            raise ValueError('reference scan exceeded its byte budget')
                    kind = 'mention' if texts[path] is False else classify_reference(path, texts[path], key)
                    if kind:
                        found[kind].append(path)
                references[key] = {kind: found[kind] for kind in KINDS if found[kind]}
        except (OSError, ValueError, GitInputError) as exc:
            references, state = {}, f'unavailable: {exc}'[:300]
    return [replace(f, env_key_references={key: references.get(key, {}) for key in sorted(targets[f.path])}
                    if state == 'complete' else None, env_reference_scan=state) if f.path in targets else f
            for f in files]


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
