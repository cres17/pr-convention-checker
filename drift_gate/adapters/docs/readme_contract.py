"""
README/docs consistency checker (adapter).

Extracts CLI commands, JSON schema keys, and feature claims from documentation
files and compares them against the actual argparse configuration and
EvaluationResult.to_dict() output.

All I/O is here; no network or subprocess calls needed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class DocsWarning:
    kind: str   # e.g. "missing-cli-command" | "extra-cli-command" |
                #      "json-schema-mismatch" | "stale-limitation"
    message: str
    file: str = ""
    line: Optional[int] = None

    def to_dict(self) -> dict:
        d: dict = {"kind": self.kind, "message": self.message}
        if self.file:
            d["file"] = self.file
        if self.line is not None:
            d["line"] = self.line
        return d


@dataclass
class DocsCheckResult:
    warnings: List[DocsWarning] = field(default_factory=list)
    checked_commands: List[str] = field(default_factory=list)
    checked_json_keys: List[str] = field(default_factory=list)
    checked_policy_fields: List[str] = field(default_factory=list)
    docs_files: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "docs_check": {
                "docs_files": self.docs_files,
                "checked_commands": self.checked_commands,
                "checked_json_keys": self.checked_json_keys,
                "checked_policy_fields": self.checked_policy_fields,
                "warnings": [w.to_dict() for w in self.warnings],
                "warning_count": len(self.warnings),
            }
        }

    def format_report(self) -> str:
        lines = ["## docs-consistency warnings", ""]
        if not self.warnings:
            lines.append("No docs-consistency issues found.")
            return "\n".join(lines)
        for w in self.warnings:
            loc = f" ({w.file}:{w.line})" if w.file and w.line else (f" ({w.file})" if w.file else "")
            lines.append(f"- **{w.kind}**{loc}: {w.message}")
        return "\n".join(lines)


# ── CLI command extraction ─────────────────────────────────────────────────────

_SHELL_CMD_RE = re.compile(
    r"(?:py|python|python3|drift-gate)[ \t]+(?:main\.py[ \t]+)?([a-z][a-z-]*)",
    re.MULTILINE,
)

# Matches only shell-labelled code blocks: ```bash, ```sh, ```shell
_CODE_BLOCK_RE = re.compile(r"```(?:bash|sh|shell)\n(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`(?:py|python3?|drift-gate)\s+(?:main\.py\s+)?([a-z][a-z-]+)[^`]*`")


def extract_cli_commands_from_docs(content: str) -> List[str]:
    """Return unique command names mentioned in documentation."""
    commands = set()

    # From code blocks
    for block in _CODE_BLOCK_RE.finditer(content):
        block_text = block.group(1)
        for m in _SHELL_CMD_RE.finditer(block_text):
            cmd = m.group(1)
            if _is_plausible_command(cmd):
                commands.add(cmd)

    # From inline code
    for m in _INLINE_CODE_RE.finditer(content):
        cmd = m.group(1)
        if _is_plausible_command(cmd):
            commands.add(cmd)

    return sorted(commands)


def _is_plausible_command(cmd: str) -> bool:
    """Filter out common false positives (filenames, flags, etc.)."""
    excluded = {
        "main", "py", "python", "python3", "pytest", "install", "pip",
        "git", "npm", "yarn", "docker", "curl",
    }
    return (
        cmd not in excluded
        and len(cmd) >= 2
        and not cmd.startswith("-")
        and not cmd.endswith(".py")
    )


def get_argparse_commands(parser) -> List[str]:
    """Introspect argparse to get all registered subcommand names."""
    commands = []
    for action in parser._subparsers._group_actions:  # type: ignore[attr-defined]
        if hasattr(action, "_name_parser_map"):
            commands.extend(action._name_parser_map.keys())
    return sorted(commands)


# ── Policy field extraction ────────────────────────────────────────────────────

_YAML_BLOCK_RE = re.compile(r"```yaml\n(.*?)```", re.DOTALL)
# Match top-level YAML keys: lines starting with a word char followed by ':'
_YAML_TOP_KEY_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*):", re.MULTILINE)


def extract_yaml_keys_from_docs(content: str) -> List[str]:
    """Extract top-level YAML keys from fenced yaml blocks in documentation."""
    keys: set[str] = set()
    for block in _YAML_BLOCK_RE.finditer(content):
        for m in _YAML_TOP_KEY_RE.finditer(block.group(1)):
            keys.add(m.group(1))
    return sorted(keys)


def get_policy_top_level_fields() -> List[str]:
    """Return the top-level field names accepted by Policy.from_dict()."""
    from drift_gate.core.models.policy import Policy
    import dataclasses
    return sorted(
        f.name for f in dataclasses.fields(Policy)
        if f.name != "load_warnings"  # internal field, not a YAML key
    )


# ── JSON schema key extraction ─────────────────────────────────────────────────

_JSON_BLOCK_RE = re.compile(r"```json\n(\{.*?\})\n```", re.DOTALL)


def extract_json_keys_from_docs(content: str) -> List[str]:
    """Extract top-level JSON keys from fenced json blocks in documentation."""
    keys = set()
    for block in _JSON_BLOCK_RE.finditer(content):
        try:
            obj = json.loads(block.group(1))
            if isinstance(obj, dict):
                keys.update(obj.keys())
        except json.JSONDecodeError:
            pass
    return sorted(keys)


def get_evaluation_result_keys() -> List[str]:
    """Return the top-level keys from EvaluationResult.to_dict()."""
    from drift_gate.core.models.result import (
        EvaluationResult, ScanMetrics, SkippedRule, RejectedIgnore,
    )
    from drift_gate.core.models.policy import Gate
    result = EvaluationResult(
        change_types=[],
        violations=[],
        skipped_rules=[],
        rejected_ignores=[],
        gate=Gate(),
    )
    return sorted(result.to_dict().keys())


# ── stale limitation detection ─────────────────────────────────────────────────

_STALE_PATTERNS = [
    (r"no\s+historical\s+tracking", "stale-limitation",
     "Stale limitation: 'No historical tracking' — history feature is implemented"),
    (r"tree.sitter\s+not\s+available", "stale-limitation",
     "Stale limitation: tree-sitter note may be outdated"),
    (r"no\s+llm", "stale-limitation",
     "Stale limitation: 'no LLM' — Claude enricher is implemented"),
]


def find_stale_limitations(content: str, filename: str) -> List[DocsWarning]:
    warnings = []
    lines = content.splitlines()
    for i, line in enumerate(lines, start=1):
        line_lower = line.lower()
        for pattern, kind, message in _STALE_PATTERNS:
            if re.search(pattern, line_lower):
                warnings.append(DocsWarning(
                    kind=kind,
                    message=message,
                    file=filename,
                    line=i,
                ))
    return warnings


# ── main check function ────────────────────────────────────────────────────────

def check_docs(doc_paths: List[Path], parser=None) -> DocsCheckResult:
    """Run all docs-consistency checks and return a DocsCheckResult.

    Args:
        doc_paths: list of documentation file paths to check
        parser: argparse.ArgumentParser for CLI command introspection.
                If None, the default CLI parser will be loaded.
    """
    from drift_gate.adapters.cli.runner import _build_parser

    if parser is None:
        parser = _build_parser()

    actual_commands = set(get_argparse_commands(parser))
    actual_result_keys = set(get_evaluation_result_keys())
    actual_policy_fields = set(get_policy_top_level_fields())

    all_doc_commands: set[str] = set()
    all_doc_json_keys: set[str] = set()
    all_doc_yaml_keys: set[str] = set()
    warnings: List[DocsWarning] = []
    doc_files_found: List[str] = []

    for doc_path in doc_paths:
        if not doc_path.exists():
            warnings.append(DocsWarning(
                kind="missing-docs-file",
                message=f"Documentation file not found: {doc_path}",
            ))
            continue

        content = doc_path.read_text(encoding="utf-8", errors="replace")
        fname = str(doc_path)
        doc_files_found.append(fname)

        doc_commands = extract_cli_commands_from_docs(content)
        all_doc_commands.update(doc_commands)

        doc_json_keys = extract_json_keys_from_docs(content)
        all_doc_json_keys.update(doc_json_keys)

        doc_yaml_keys = extract_yaml_keys_from_docs(content)
        all_doc_yaml_keys.update(doc_yaml_keys)

        warnings.extend(find_stale_limitations(content, fname))

    # CLI command drift
    for cmd in sorted(all_doc_commands):
        if cmd not in actual_commands:
            warnings.append(DocsWarning(
                kind="missing-cli-command",
                message=(
                    f"README mentions `{cmd}`, but argparse subcommand is missing. "
                    f"Known commands: {', '.join(sorted(actual_commands))}"
                ),
            ))

    # JSON schema drift — check for keys in docs that are missing from result
    if all_doc_json_keys:
        for key in sorted(all_doc_json_keys):
            if key not in actual_result_keys:
                warnings.append(DocsWarning(
                    kind="json-schema-mismatch",
                    message=(
                        f"README JSON sample contains key `{key}` which is absent "
                        f"from EvaluationResult.to_dict(). "
                        f"Actual keys: {', '.join(sorted(actual_result_keys))}"
                    ),
                ))

    # Keys in result but missing from docs JSON samples
    if all_doc_json_keys:
        for key in sorted(actual_result_keys):
            if key not in all_doc_json_keys:
                warnings.append(DocsWarning(
                    kind="json-schema-mismatch",
                    message=(
                        f"EvaluationResult.to_dict() has key `{key}` which is missing "
                        f"from all README JSON samples."
                    ),
                ))

    # Policy field drift — YAML blocks mentioning unknown fields
    # Only check if the doc actually has yaml blocks (avoid false positives on empty docs)
    if all_doc_yaml_keys:
        # All known valid keys across policy structure + common non-policy YAML keys
        # that legitimately appear in docs (GitHub Actions, docker-compose, etc.)
        _KNOWN_YAML_KEYS = actual_policy_fields | {
            "id", "when", "require", "severity", "message",  # rule-level keys
            "any_changed", "all_changed", "groups", "name",   # sub-keys
            "fail_on_blocker", "fail_on_major_count",         # gate sub-keys
            "allow_ignore", "min_change_intensity",           # rule extras
            "allow_ignores", "require_codeowners_approval",   # suppression sub-keys
            "allowed_rules", "repeated_ignore_threshold",
            "provider", "mode",                               # enrichment sub-keys
            # GitHub Actions / CI YAML keys that appear in docs examples
            "on", "jobs", "permissions", "steps", "uses", "with",
            "run", "runs", "name", "env", "if", "needs", "outputs",
        }
        for key in sorted(all_doc_yaml_keys):
            if key in _KNOWN_YAML_KEYS:
                continue
            warnings.append(DocsWarning(
                kind="policy-field-mismatch",
                message=(
                    f"YAML block mentions `{key}` which is not a recognized "
                    f"Policy field. Known top-level fields: {', '.join(sorted(actual_policy_fields))}"
                ),
            ))

    return DocsCheckResult(
        warnings=warnings,
        checked_commands=sorted(all_doc_commands),
        checked_json_keys=sorted(all_doc_json_keys),
        checked_policy_fields=sorted(all_doc_yaml_keys & actual_policy_fields),
        docs_files=doc_files_found,
    )
