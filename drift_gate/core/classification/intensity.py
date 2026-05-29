"""
Patch-based change intensity classifier.

This is intentionally heuristic. It reduces obvious false positives now while
leaving room for Tree-sitter based semantic analysis later.
"""
import re
from typing import Iterable, List

from drift_gate.core.models.changed_file import ChangedFile

INTENSITY_ORDER = {
    "any": -1,
    "comment-only": 0,
    "impl-only": 1,
    "config-key-added": 2,
    "signature-change": 2,
    "auth-policy-change": 3,
    "ci-secret-change": 3,
    "db-schema-change": 3,
    "public-cli-change": 3,
    "route-contract-change": 3,
    "export-added": 3,
}

VALID_INTENSITIES = set(INTENSITY_ORDER)

SEMANTIC_SIGNAL_INTENSITY = {
    "env-key-added": "config-key-added",
    "db-schema-change": "db-schema-change",
    "auth-policy-change": "auth-policy-change",
    "ci-secret-change": "ci-secret-change",
    "route-contract-change": "route-contract-change",
    "public-cli-change": "public-cli-change",
    "cli-flag-added": "public-cli-change",
    "cli-command-added": "public-cli-change",
    "function-signature-changed": "signature-change",
    "class-interface-type-changed": "signature-change",
    "openapi-operation-changed": "route-contract-change",
    "db-model-schema-changed": "db-schema-change",
    "public-export-added": "export-added",
}

SIGNATURE_PATTERNS = [
    re.compile(r"^\s*(export\s+)?(async\s+)?function\s+\w+\s*\("),
    re.compile(r"^\s*(export\s+)?(class|interface|type|enum)\s+\w+"),
    re.compile(r"^\s*(public|private|protected)\s+.*\("),
    re.compile(r"^\s*def\s+\w+\s*\("),
    re.compile(r"^\s*class\s+\w+"),
    re.compile(r"^\s*(func|fn)\s+\w+\s*\("),
]

EXPORT_PATTERNS = [
    re.compile(r"^\s*export\s+(default\s+)?(async\s+)?(function|class|const|let|var|type|interface|enum)\b"),
    re.compile(r"^\s*export\s*\{"),
    re.compile(r"^\s*public\s+"),
]

ENV_KEY_PATTERNS = [
    re.compile(r"^\s*[A-Z][A-Z0-9_]*\s*="),
    re.compile(r"process\.env\.([A-Z][A-Z0-9_]*)"),
    re.compile(r"os\.environ(?:\.get)?\(\s*['\"]([A-Z][A-Z0-9_]*)['\"]"),
    re.compile(r"getenv\(\s*['\"]([A-Z][A-Z0-9_]*)['\"]"),
]

ROUTE_PATTERNS = [
    re.compile(r"\b(router|app)\.(get|post|put|patch|delete)\s*\("),
    re.compile(r"@\w+\.(get|post|put|patch|delete)\s*\("),
    re.compile(r"@(Get|Post|Put|Patch|Delete)\s*\("),
    re.compile(r"\b(response_model|Body|Query|Path)\s*="),
    re.compile(r"\b(z\.object|schema|requestSchema|responseSchema)\s*\("),
    re.compile(r"^\s*(export\s+)?(interface|type)\s+\w*(Request|Response|Payload|Dto)\b"),
    re.compile(r"^\s*(requestBody|responses|parameters|operationId)\s*:", re.IGNORECASE),
    re.compile(r"^\s*/[^:\s]+:\s*$"),
]

DB_SCHEMA_PATTERNS = [
    re.compile(r"\b(create|alter|drop)\s+table\b", re.IGNORECASE),
    re.compile(r"\b(add|drop|rename)\s+column\b", re.IGNORECASE),
    re.compile(r"\b(rename)\s+table\b", re.IGNORECASE),
    re.compile(r"\b(not\s+null|null|nullable|default|unique|index|constraint|foreign\s+key)\b", re.IGNORECASE),
    re.compile(r"\b(create|drop)\s+(unique\s+)?index\b", re.IGNORECASE),
    re.compile(r"^\s*(model|table)\s+\w+", re.IGNORECASE),
    re.compile(r"^\s+\w+\s+(String|Int|Boolean|DateTime|Float|Decimal|Json)\b"),
    re.compile(r"^\s+\w+\s+.*(@default|@unique|@index|@db\.|@relation)\b"),
]

AUTH_POLICY_PATTERNS = [
    re.compile(r"\b(role|roles|permission|permissions|rbac|policy)\b", re.IGNORECASE),
    re.compile(r"\b(requireRole|hasPermission|canAccess|authorize)\s*\("),
    re.compile(r"\b(authenticate|isAuthenticated|requireAuth|authMiddleware|middleware)\s*\("),
    re.compile(r"\b(allow|deny|can|cannot)\s*\("),
    re.compile(r"^\s*(allow|deny|policy|permission|role)[\w-]*\s*:", re.IGNORECASE),
]

CI_SECRET_PATTERNS = [
    re.compile(r"\bsecrets\.[A-Z][A-Z0-9_]*\b"),
    re.compile(r"\b[A-Z][A-Z0-9_]*_TOKEN\b"),
    re.compile(r"\b[A-Z][A-Z0-9_]*_SECRET\b"),
    re.compile(r"\b(deploy|deployment|release|publish|kubectl|helm|terraform|docker\s+build|docker\s+push)\b", re.IGNORECASE),
    re.compile(r"^\s*(FROM|RUN|CMD|ENTRYPOINT|ENV|ARG|EXPOSE|COPY|ADD)\b"),
    re.compile(r"^\s*(resource|module|provider|variable|output)\s+\""),
    re.compile(r"^\s*(apiVersion|kind|metadata|spec):\s*$"),
]

CLI_PUBLIC_PATTERNS = [
    re.compile(r"\b(add_argument|add_option|option|argument)\s*\("),
    re.compile(r"\b(subparsers\.add_parser|add_parser|command)\s*\("),
    re.compile(r"\b(program|commander)\.(command|option)\s*\("),
    re.compile(r"\byargs\([^)]*\)\.(command|option)\s*\("),
    re.compile(r"\b@click\.(command|option|argument)\s*\("),
    re.compile(r"\b(cobra\.Command|Flags\(\)\.(String|Bool|Int|StringVar|BoolVar|IntVar))\b"),
    re.compile(r"\b(required=True|required:\s*true|deprecated=True|hidden=True)\b"),
    re.compile(r"^\s*-\s{2,}[A-Za-z0-9][A-Za-z0-9_-]+\s", re.MULTILINE),
]

CONFIG_SCHEMA_PATTERNS = [
    re.compile(r"\b(BaseSettings|SettingsConfigDict|env_prefix|env_file)\b"),
    re.compile(r"\b(z\.object|Joi\.object|envSchema|configSchema)\s*\("),
    re.compile(r"^\s*(required|default|type|format|enum)\s*:", re.IGNORECASE),
]


def classify_file_intensity(file: ChangedFile) -> str:
    """
    Return one of: comment-only, impl-only, config-key-added,
    signature-change, auth-policy-change, ci-secret-change, db-schema-change,
    route-contract-change, export-added.

    Missing patches are treated conservatively as signature-change because the
    evaluator cannot prove the change is implementation-only.
    """
    semantic_intensity = _semantic_intensity(file.semantic_signals)
    if semantic_intensity:
        return semantic_intensity

    if file.status == "added":
        return "export-added"
    if file.status in ("deleted", "renamed"):
        return "signature-change"
    if not file.patch:
        return "signature-change"

    changed_lines = list(_changed_content_lines(file.patch))
    if not changed_lines:
        return "impl-only"

    if all(_is_comment_or_blank(line) for line in changed_lines):
        return "comment-only"

    added_lines = [line for marker, line in changed_lines if marker == "+"]
    removed_lines = [line for marker, line in changed_lines if marker == "-"]
    if _adds_config_key(added_lines, removed_lines):
        return "config-key-added"

    if any(_matches_any(line, CONFIG_SCHEMA_PATTERNS) for _, line in changed_lines):
        return "config-key-added"

    if any(_matches_any(line, CI_SECRET_PATTERNS) for _, line in changed_lines):
        return "ci-secret-change"

    if any(_matches_any(line, CLI_PUBLIC_PATTERNS) for _, line in changed_lines):
        return "public-cli-change"

    if any(_matches_any(line, AUTH_POLICY_PATTERNS) for _, line in changed_lines):
        return "auth-policy-change"

    if any(_matches_any(line, DB_SCHEMA_PATTERNS) for _, line in changed_lines):
        return "db-schema-change"

    if any(_matches_any(line, ROUTE_PATTERNS) for _, line in changed_lines):
        return "route-contract-change"

    if (
        any(_matches_any(line, EXPORT_PATTERNS) for line in added_lines)
        and not any(_matches_any(line, EXPORT_PATTERNS) for line in removed_lines)
    ):
        return "export-added"

    if any(_matches_any(line, SIGNATURE_PATTERNS) for _, line in changed_lines):
        return "signature-change"

    return "impl-only"


def max_intensity(files: Iterable[ChangedFile]) -> str:
    """Return the strongest intensity among files."""
    strongest = "comment-only"
    for file in files:
        intensity = classify_file_intensity(file)
        if INTENSITY_ORDER[intensity] > INTENSITY_ORDER[strongest]:
            strongest = intensity
    return strongest


def meets_min_intensity(actual: str, minimum: str) -> bool:
    """True when actual intensity is at least the configured threshold."""
    if minimum in ("", "any", None):
        return True
    return INTENSITY_ORDER.get(actual, 2) >= INTENSITY_ORDER.get(minimum, 2)


def _changed_content_lines(patch: str) -> Iterable[tuple[str, str]]:
    for raw in patch.splitlines():
        if not raw or raw.startswith(("+++", "---", "@@", "diff --git", "index ")):
            continue
        if raw.startswith("\\ No newline"):
            continue
        marker = raw[0]
        if marker in ("+", "-"):
            yield marker, raw[1:]


def _is_comment_or_blank(item: tuple[str, str]) -> bool:
    _, line = item
    stripped = line.strip()
    return (
        not stripped
        or stripped.startswith(("#", "//", "/*", "*", "*/"))
        or stripped in ('"""', "'''")
    )


def _matches_any(line: str, patterns: List[re.Pattern]) -> bool:
    return any(pattern.search(line) for pattern in patterns)


def _semantic_intensity(signals: List[str]) -> str:
    strongest = ""
    for signal in signals:
        intensity = SEMANTIC_SIGNAL_INTENSITY.get(signal)
        if not intensity:
            continue
        if not strongest or INTENSITY_ORDER[intensity] > INTENSITY_ORDER[strongest]:
            strongest = intensity
    return strongest


def _adds_config_key(added_lines: List[str], removed_lines: List[str]) -> bool:
    added_keys = _extract_config_keys(added_lines)
    removed_keys = _extract_config_keys(removed_lines)
    return bool(added_keys - removed_keys)


def _extract_config_keys(lines: List[str]) -> set[str]:
    keys = set()
    for line in lines:
        for pattern in ENV_KEY_PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            if match.groups():
                keys.add(match.group(1))
            else:
                keys.add(line.split("=", 1)[0].strip())
    return keys
