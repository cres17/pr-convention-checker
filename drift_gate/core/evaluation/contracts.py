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


def removed_keys_check(group, file, keys, *, dynamic=False):
    """A key no changed file reads any more must not stay in the sample unless something still uses it.

    Only a confirmed absence anywhere else in the repository is a violation. A use in configuration,
    a bare mention, an unchecked repository or dynamic access in the change is a warning.
    """
    from drift_gate.core.evaluation.env_references import reference_outcome
    scan = file.env_reference_scan
    references = file.env_key_references or {}
    stale, advisories = [], []
    for key in sorted(keys):
        stop = (f"Stop checking {key}? Add exclude_removed_keys: [{key}] to group '{group.name}' "
                f"(or check_removed_keys: false to stop the check)")
        prefix = f'{file.path}: {key} is no longer read by the changed code but is still documented'
        outcome = reference_outcome(references.get(key)) if scan == 'complete' else None
        if outcome is None:
            advisories.append(f"{prefix}; other uses could not be checked ({scan or 'repository references not collected'}). {stop}")
        elif outcome == 'code':
            continue
        elif outcome in ('config', 'mention'):
            paths = ', '.join(references[key][outcome][:5])
            what = 'used in configuration' if outcome == 'config' else 'named without a recognised use'
            advisories.append(f'{prefix}; {what}: {paths}. Remove it from the sample if that use is gone. {stop}')
        elif dynamic:
            advisories.append(f'{prefix}; dynamic environment access in the change prevents a definite result. {stop}')
        else:
            stale.append(key)
    if stale:
        names = ', '.join(stale)
        return ContentCheck('violated', 'verified',
            f"{file.path}: removed environment keys still documented: {names} (no other use in the repository). "
            f"Remove them from the sample, or add exclude_removed_keys: [{names}] to group '{group.name}' "
            f"if they are used outside this repository", 'env-keys', tuple(advisories))
    return ContentCheck('satisfied', 'verified', f'{file.path}: no removed environment key is documented without a use',
                        'env-keys', tuple(advisories))


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
        removed = facts.removed - set(group.exclude_removed_keys) if group.check_removed_keys else set()
        stale = {f.path: removed & set(f.documented_env_keys) for f in docs if f.documented_env_keys}
        if not required and not any(stale.values()):
            if not facts.uncertain and all((f.status == 'added' or f.before_source is not None)
                                          and (f.status == 'deleted' or f.after_source is not None) for f in triggers):
                return ContentCheck('satisfied', 'not-applicable', 'Complete source establishes no new environment key', 'env-keys')
            return unknown("No static new environment keys could be established from this change", "env-keys")
        # all_changed requires each named document to contain all keys;
        # any_changed permits any one complete document, not fragments combined.
        reason = ("Required environment keys: " + ", ".join(sorted(required)) if required
                  else "Removed environment keys: " + ", ".join(sorted(removed)))
        def check_required(file):
            if file.document_input_state == 'missing':
                return checked(False, f'{file.path} is missing; required keys: ' + ', '.join(sorted(required)), 'env-keys')
            if file.documented_env_keys is None:
                return unknown(f'{file.path}: document input unavailable', 'env-keys')
            missing = required - set(file.documented_env_keys)
            detail = (f'{file.path}: missing environment keys: ' + ', '.join(sorted(missing)) if missing
                      else f'{file.path}: all required environment keys are documented')
            return checked(not missing, detail, 'env-keys')
        def check_document(file):
            parts = [check_required(file)] if required else []
            if stale.get(file.path):
                parts.append(removed_keys_check(group, file, stale[file.path], dynamic=facts.uncertain))
            return combine(parts, require_all=True, mode="env-keys") if parts else checked(
                True, f'{file.path}: no removed environment key remains documented', 'env-keys')
        results = []
        for pattern in patterns:
            checks = [check_document(f) for f in docs if matches_any(f.path, [pattern])]
            results.append(combine(checks, require_all=False, mode="env-keys"))
        result = combine(results, require_all=bool(group.all_changed), mode="env-keys")
        if facts.uncertain and required:
            result = combine([result, unknown('Environment access scope/key is unresolved', 'env-keys')],
                             require_all=True, mode='env-keys')
        return ContentCheck(result.decision, result.verification, reason + "; " + result.reason, "env-keys",
                            result.advisories)
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
