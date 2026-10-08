"""Bounded contract checks. Pure functions; no arbitrary prose understanding."""
import re

from drift_gate.utils.glob_matcher import matches_any
from drift_gate.core.route_syntax import METHOD_PATTERN, literal_route
from drift_gate.core.python_syntax import environment_keys
from drift_gate.core.patch_lines import changed_lines
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.evaluation.content_result import ContentCheck, checked, unknown, combine
from drift_gate.core.evaluation.api_schema import api_schema_requirement
from drift_gate.core.evaluation.environment import environment_delta

DOC_ROUTE = re.compile(rf"\b({METHOD_PATTERN})[ \t]+(/[^\s`'\"<>]+)", re.I)
DOC_TABLE_ROUTE = re.compile(rf"^\s*\|\s*({METHOD_PATTERN})\s*\|\s*(/[^\s|`'\"<>]+)\s*\|", re.I)
ENV_ACCESS = re.compile(
    r"\bprocess\.env\.([A-Z][A-Z0-9_]*)\b|"
    r"\bprocess\.env\[\s*['\"]([A-Z][A-Z0-9_]*)['\"]\s*\]|"
    r"\bos\.environ\[\s*['\"]([A-Z][A-Z0-9_]*)['\"]\s*\]|"
    r"\bos\.(?:environ\.get|getenv)\(\s*['\"]([A-Z][A-Z0-9_]*)['\"]"
)
ENV_DEFINITION = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=", re.M)


def patch_lines(patch, marker):
    return [line for kind, line in changed_lines(ChangedFile(path="", status="modified", patch=patch)) if kind == marker]


def env_keys_in_code(lines, path=''):
    if path.endswith('.py'):
        parsed = environment_keys(lines)
        if parsed is not None:
            return parsed
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
    return environment_delta(files).keys


def _routes(lines, *, docs=False):
    pairs = set()
    for line in lines:
        if docs:
            table = DOC_TABLE_ROUTE.match(line)
            if table:
                pairs.add((table.group(1).upper(), table.group(2)))
            else:
                pairs.update((match.group(1).upper(), match.group(2))
                             for match in DOC_ROUTE.finditer(line))
        elif not line.lstrip().startswith(("#", "//", "*")):
            route = literal_route(line)
            if route:
                pairs.add(route)
    return pairs


def route_delta(files):
    added, removed = set(), set()
    for file in files:
        added.update(_routes(patch_lines(file.patch, "+")))
        removed.update(_routes(patch_lines(file.patch, "-")))
    return added - removed, removed - added


def content_requirement(group, triggers, changed_files, session=None):
    """Return explicit evidence; legacy auto fallback is labelled, never verified."""
    patterns = group.any_changed or group.all_changed
    docs = [f for f in changed_files if f.status != "deleted" and matches_any(f.path, patterns)]
    if group.content == "paths":
        return ContentCheck("paths", "verified", "Explicit file-change requirement; content was not requested", "paths")
    if group.content == "api-schema":
        return api_schema_requirement(group, triggers, changed_files, session)
    if group.content == 'auto-strict':
        from drift_gate.core.evaluation.routes import strict_auto_requirement
        return strict_auto_requirement(group, triggers, changed_files, session)
    if group.content == 'contract-proof':
        from drift_gate.core.evaluation.proof_gate import contract_proof_requirement
        return contract_proof_requirement(group, triggers, changed_files, session)
    if group.content == 'api-compatibility':
        from drift_gate.core.evaluation.compatibility import compatibility_requirement
        return compatibility_requirement(group, triggers, changed_files, session)
    if group.content == 'api-routes' and all(
        (f.status == 'added' or f.before_source is not None) and (f.status == 'deleted' or f.after_source is not None) for f in triggers):
        from drift_gate.core.evaluation.routes import complete_route_delta, route_document_requirement
        from drift_gate.core.evaluation.static_routers import UnsupportedContract
        try:
            added, removed = complete_route_delta(triggers, session)
        except UnsupportedContract as exc:
            return unknown(str(exc), 'api-routes')
        return route_document_requirement(group, changed_files, added, removed, session)
    if group.content == "env-keys":
        facts = environment_delta(triggers)
        required = facts.keys
        if not required:
            if not facts.uncertain and all((f.status == 'added' or f.before_source is not None)
                                          and (f.status == 'deleted' or f.after_source is not None) for f in triggers):
                return ContentCheck('satisfied', 'not-applicable', 'Complete source establishes no new environment key', 'env-keys')
            return unknown("No static new environment keys could be established from this change", "env-keys")
        # all_changed requires each named document to contain all keys;
        # any_changed permits any one complete document, not fragments combined.
        reason = "Required environment keys: " + ", ".join(sorted(required))
        results = []
        for pattern in patterns:
            checks = [unknown("Document input unavailable", "env-keys") if f.documented_env_keys is None
                      else checked(required <= set(f.documented_env_keys), reason, "env-keys")
                      for f in docs if matches_any(f.path, [pattern])]
            results.append(combine(checks, require_all=False, mode="env-keys"))
        result = combine(results, require_all=bool(group.all_changed), mode="env-keys")
        if facts.uncertain:
            result = combine([result, unknown('Environment access scope/key is unresolved', 'env-keys')],
                             require_all=True, mode='env-keys')
        return ContentCheck(result.decision, result.verification, reason + "; " + result.reason, "env-keys")
    added, removed = route_delta(triggers)
    auto_api = any(p.startswith(("docs/api/", "docs/spec.", "openapi")) for p in patterns)
    if group.content == "auto" and (not auto_api or not (added or removed)):
        return ContentCheck("paths", "unverified", "Legacy auto fallback: only file changes checked; contract content was not verified", "auto")
    if not (added or removed):
        return unknown("No supported literal HTTP route delta; manual contract verification required", group.content)
    # Structured documents need their full decoded contents. A YAML/JSON
    # patch is not Markdown and cannot prove an operation is absent.
    if any(f.path.lower().endswith(('.json', '.yaml', '.yml')) for f in docs):
        from drift_gate.core.evaluation.routes import route_document_requirement
        return route_document_requirement(group, changed_files, added, removed, session)
    def covered(pattern):
        candidates = [f for f in docs if matches_any(f.path, [pattern])]
        plus = set().union(*(_routes(patch_lines(f.patch, "+"), docs=True) for f in candidates))
        minus = set().union(*(_routes(patch_lines(f.patch, "-"), docs=True) for f in candidates))
        return added <= plus and removed <= (minus - plus)
    ok = all(covered(p) for p in patterns) if group.all_changed else covered_patterns(docs, added, removed)
    labels = [f"add {m} {p}" for m, p in sorted(added)] + [f"remove {m} {p}" for m, p in sorted(removed)]
    return checked(ok, "API documentation must reflect: " + "; ".join(labels), group.content)


def possible_route_change(files):
    """A candidate witness keeps incomplete registrations out of unmatched.

    This is deliberately not a verified route extractor. Strings/comments
    never establish this witness. JS registration remains unverified.
    """
    from drift_gate.core.python_syntax import without_literals
    for file in files:
        lines = [text for marker in ('+', '-') for text in patch_lines(file.patch, marker)]
        for line in without_literals(lines):
            if line.lstrip().startswith(('#', '//', '*')):
                continue
            if re.search(r'\bAPIRouter\s*\(|\bresponse_model\s*=|\.route\s*\(', line):
                return True
            if re.match(rf'\s*@?\w+\.({METHOD_PATTERN})\s*\(', line, re.I):
                return True
    return False


def covered_patterns(docs, added, removed):
    plus = set().union(*(_routes(patch_lines(f.patch, "+"), docs=True) for f in docs))
    minus = set().union(*(_routes(patch_lines(f.patch, "-"), docs=True) for f in docs))
    return added <= plus and removed <= (minus - plus)
