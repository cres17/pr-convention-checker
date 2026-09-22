"""Bounded contract checks. Pure functions; no arbitrary prose understanding."""
import re

from drift_gate.utils.glob_matcher import matches_any

METHODS = "get|post|put|patch|delete|head|options"
ROUTE = re.compile(rf"(?:@?\w+\.)({METHODS})\s*\(\s*(['\"])(/[^'\"\n]*)\2", re.I)
DOC_ROUTE = re.compile(rf"\b({METHODS})[ \t]+(/[^\s`'\"<>]+)", re.I)
ENV_ACCESS = re.compile(
    r"\bprocess\.env\.([A-Z][A-Z0-9_]*)\b|"
    r"\bprocess\.env\[\s*['\"]([A-Z][A-Z0-9_]*)['\"]\s*\]|"
    r"\bos\.environ\[\s*['\"]([A-Z][A-Z0-9_]*)['\"]\s*\]|"
    r"\bos\.(?:environ\.get|getenv)\(\s*['\"]([A-Z][A-Z0-9_]*)['\"]"
)
ENV_DEFINITION = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=", re.M)


def patch_lines(patch, marker):
    return [line[1:] for line in patch.splitlines()
            if line.startswith(marker) and not line.startswith(marker * 3)]


def env_keys_in_code(lines):
    keys = set()
    for line in lines:
        if line.lstrip().startswith(("#", "//", "*")):
            continue
        for match in ENV_ACCESS.finditer(line):
            keys.update(group for group in match.groups() if group)
    return keys


def env_keys_in_document(text):
    return set(ENV_DEFINITION.findall(text))


def added_env_keys(files):
    added, removed = set(), set()
    for file in files:
        added.update(env_keys_in_code(patch_lines(file.patch, "+")))
        removed.update(env_keys_in_code(patch_lines(file.patch, "-")))
    return added - removed


def _routes(lines, *, docs=False):
    pairs = set()
    for line in lines:
        if not docs and line.lstrip().startswith(("#", "//", "*")):
            continue
        pattern = DOC_ROUTE if docs else ROUTE
        for match in pattern.finditer(line):
            pairs.add((match.group(1).upper(), match.group(2 if docs else 3)))
    return pairs


def route_delta(files):
    added, removed = set(), set()
    for file in files:
        added.update(_routes(patch_lines(file.patch, "+")))
        removed.update(_routes(patch_lines(file.patch, "-")))
    return added - removed, removed - added


def content_requirement(group, triggers, changed_files):
    """Return None for path-only mode, else (satisfied, explanation).

    Automatic endpoint checking is limited to explicitly recognizable API
    document paths and literal route deltas. Other groups keep path semantics.
    """
    patterns = group.any_changed or group.all_changed
    docs = [f for f in changed_files if f.status != "deleted" and matches_any(f.path, patterns)]
    if group.content == "paths":
        return None
    if group.content == "env-keys":
        required = added_env_keys(triggers)
        if not required:
            return False, "No static new environment keys could be established from this change"
        # all_changed requires each named document to contain all keys;
        # any_changed permits any one complete document, not fragments combined.
        def complete(pattern):
            return any(f.documented_env_keys is not None and required <= set(f.documented_env_keys)
                       for f in docs if matches_any(f.path, [pattern]))
        matched = all(complete(p) for p in patterns) if group.all_changed else any(complete(p) for p in patterns)
        return matched, "Required environment keys: " + ", ".join(sorted(required))
    added, removed = route_delta(triggers)
    auto_api = any(p.startswith(("docs/api/", "docs/spec.", "openapi")) for p in patterns)
    if group.content == "auto" and (not auto_api or not (added or removed)):
        return None
    if not (added or removed):
        return False, "No supported literal HTTP route delta; manual contract verification required"
    def covered(pattern):
        candidates = [f for f in docs if matches_any(f.path, [pattern])]
        plus = set().union(*(_routes(patch_lines(f.patch, "+"), docs=True) for f in candidates))
        minus = set().union(*(_routes(patch_lines(f.patch, "-"), docs=True) for f in candidates))
        return added <= plus and removed <= minus
    ok = all(covered(p) for p in patterns) if group.all_changed else covered_patterns(docs, added, removed)
    labels = [f"add {m} {p}" for m, p in sorted(added)] + [f"remove {m} {p}" for m, p in sorted(removed)]
    return ok, "API documentation must reflect: " + "; ".join(labels)


def covered_patterns(docs, added, removed):
    plus = set().union(*(_routes(patch_lines(f.patch, "+"), docs=True) for f in docs))
    minus = set().union(*(_routes(patch_lines(f.patch, "-"), docs=True) for f in docs))
    return added <= plus and removed <= minus
