"""
Deterministic heuristic code review checks (core, pure logic — no I/O).

Checks:
- core layer I/O violations (print, sys.exit, subprocess, network imports)
- adapter boundary violations (I/O-related imports in core/)
- mutable default arguments
- broad/swallowed exceptions
- token/secret logging
"""
from __future__ import annotations

import io
import re
import tokenize
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import List, Optional


# Severity levels (ordered from high to low)
SEVERITY_ORDER = ["high", "medium", "low", "info"]


@dataclass
class ReviewFinding:
    severity: str        # "high" | "medium" | "low" | "info"
    file: str
    line: int
    rule: str            # short rule ID
    message: str
    suggested_fix: str = ""

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "rule": self.rule,
            "message": self.message,
            "suggested_fix": self.suggested_fix,
        }

    def format_line(self) -> str:
        fix = f"\n  Fix: {self.suggested_fix}" if self.suggested_fix else ""
        return f"- {self.severity.upper()} `{self.file}:{self.line}`\n  {self.message}{fix}"


@dataclass
class UncoveredFunction:
    """A public function/method added in a diff with no corresponding test added."""
    source_file: str
    function_name: str
    gap_type: str = "function"
    expected_test_file: str = ""
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "source_file": self.source_file,
            "function_name": self.function_name,
            "gap_type": self.gap_type,
            "expected_test_file": self.expected_test_file,
            "message": self.message,
        }

    def format_line(self) -> str:
        if self.gap_type == "validator-test-file":
            return (
                f"- `{self.source_file}` changed but `{self.expected_test_file}` "
                "was not changed in the same diff"
            )
        if self.gap_type == "reporter-field-display":
            return (
                f"- `{self.function_name}` is present in `EvaluationResult.to_dict()` "
                "but is not rendered by the configured reporter output"
            )
        return f"- `{self.source_file}` added `{self.function_name}()` but no `test_{self.function_name}` was found in diff"


@dataclass
class ReviewResult:
    findings: List[ReviewFinding] = field(default_factory=list)
    files_reviewed: List[str] = field(default_factory=list)
    test_gaps: List[UncoveredFunction] = field(default_factory=list)

    def by_severity(self, severity: str) -> List[ReviewFinding]:
        return [f for f in self.findings if f.severity == severity]

    @property
    def has_high(self) -> bool:
        return any(f.severity == "high" for f in self.findings)

    @property
    def has_medium(self) -> bool:
        return any(f.severity == "medium" for f in self.findings)

    def to_dict(self) -> dict:
        return {
            "review": {
                "files_reviewed": self.files_reviewed,
                "finding_count": len(self.findings),
                "findings": [f.to_dict() for f in self.findings],
                "test_gaps": [t.to_dict() for t in self.test_gaps],
            }
        }

    def format_markdown(self) -> str:
        lines = ["## Drift Gate Code Review", ""]
        if not self.findings and not self.test_gaps:
            lines.append("No issues found.")
            return "\n".join(lines)

        if self.findings:
            lines.append(f"**{len(self.findings)} finding(s)** across {len(self.files_reviewed)} file(s)")
            lines.append("")
            by_sev: dict[str, List[ReviewFinding]] = {}
            for f in self.findings:
                by_sev.setdefault(f.severity, []).append(f)
            lines.append("### Findings")
            lines.append("")
            for sev in SEVERITY_ORDER:
                for finding in by_sev.get(sev, []):
                    lines.append(finding.format_line())
                    lines.append("")

        if self.test_gaps:
            lines.append("### Test Gaps")
            lines.append("")
            for gap in self.test_gaps:
                lines.append(gap.format_line())
            lines.append("")

        return "\n".join(lines)


# ── check registry ─────────────────────────────────────────────────────────────

# Patterns that must NOT appear in core/ files
_CORE_IO_PATTERNS = [
    # (regex_pattern, rule_id, message, suggested_fix)
    (
        re.compile(r"^\s*print\s*\(", re.MULTILINE),
        "core-io-print",
        "core layer uses print(). Move output to adapters.",
        "Replace with logging or raise an exception; emit output in adapters.",
    ),
    (
        re.compile(r"\bsys\.exit\s*\(", re.MULTILINE),
        "core-io-sys-exit",
        "core layer calls sys.exit(). Move exit logic to adapters.",
        "Raise a specific exception instead; catch it in the adapter.",
    ),
    (
        re.compile(r"^\s*import\s+subprocess|^\s*from\s+subprocess", re.MULTILINE),
        "core-io-subprocess",
        "core layer imports subprocess. Move I/O to adapters.",
        "Move subprocess calls to drift_gate/adapters/.",
    ),
    (
        re.compile(
            r"^\s*import\s+(?:urllib|requests|httpx|aiohttp|socket)|"
            r"^\s*from\s+(?:urllib|requests|httpx|aiohttp|socket)",
            re.MULTILINE,
        ),
        "core-io-network",
        "core layer imports a network library. Move I/O to adapters.",
        "Move HTTP/socket calls to drift_gate/adapters/.",
    ),
    (
        re.compile(r"^\s*import\s+sys\b", re.MULTILINE),
        "core-io-sys",
        "core layer imports sys. Verify no I/O calls (sys.exit, sys.stdout) are used.",
        "Remove sys import if only used for sys.exit; use exceptions instead.",
    ),
    (
        re.compile(
            r"\bopen\s*\(|\.read_text\s*\(|\.write_text\s*\(|\.read_bytes\s*\(|"
            r"\.write_bytes\s*\(|\.open\s*\(|os\.path\.|os\.listdir\s*\(|"
            r"os\.makedirs\s*\(|os\.remove\s*\(|shutil\.",
            re.MULTILINE,
        ),
        "core-io-filesystem",
        "core layer accesses the filesystem directly. Move file I/O to adapters.",
        "Pass file content as a string/bytes argument instead of reading in core.",
    ),
]

# Patterns that should not appear anywhere (quality/safety checks)
_QUALITY_PATTERNS = [
    (
        re.compile(r"def\s+\w+\s*\([^)]*=\s*\[\s*\]", re.MULTILINE),
        "mutable-default",
        "medium",
        "Mutable default argument (list). Use None and set inside function body.",
        "Change `= []` to `= None` and add `if arg is None: arg = []` in the body.",
    ),
    (
        re.compile(r"def\s+\w+\s*\([^)]*=\s*\{\s*\}", re.MULTILINE),
        "mutable-default-dict",
        "medium",
        "Mutable default argument (dict). Use None and set inside function body.",
        "Change `= {}` to `= None` and add `if arg is None: arg = {}` in the body.",
    ),
    (
        re.compile(r"except\s*:\s*$", re.MULTILINE),
        "broad-except",
        "medium",
        "Bare `except:` catches all exceptions including KeyboardInterrupt. Use `except Exception:`.",
        "Replace `except:` with `except Exception:`.",
    ),
    (
        re.compile(r"except\s+Exception\s*:\s*\n\s*pass\s*$", re.MULTILINE),
        "swallowed-exception",
        "medium",
        "Exception is silently swallowed (except Exception: pass). Log or re-raise.",
        "Add at minimum a comment explaining why silence is safe, or use logging.",
    ),
    (
        # Detect logging of api_key, token, secret variable *values* via f-string or % format
        # Must have an interpolation marker ({var}, %s, + var) to avoid flagging mere string mentions
        re.compile(
            r'(?:print|log(?:ging)?\.(?:info|debug|warning|error))\s*\('
            r'(?:[^)]*\{[^}]*(?:api_key|token|secret|password|credential)[^}]*\}'
            r'|[^)]*(?:api_key|token|secret|password|credential)\s*[+,])',
            re.MULTILINE | re.IGNORECASE,
        ),
        "token-logging",
        "high",
        "Potential secret/token value logged. API keys must never appear in logs.",
        "Remove the sensitive value from the log message.",
    ),
]


def review_file_content(
    file_path: str,
    content: str,
) -> List[ReviewFinding]:
    """Run all heuristic checks on a single file's content.

    Args:
        file_path: POSIX-style path (used for context in findings)
        content: full source text

    Returns:
        List of ReviewFinding (may be empty)
    """
    findings: List[ReviewFinding] = []
    is_core = _is_core_file(file_path)
    structural_content = _strip_python_strings_and_comments(content)

    # Core I/O checks
    if is_core:
        for pattern, rule_id, message, fix in _CORE_IO_PATTERNS:
            for match in pattern.finditer(structural_content):
                line_num = structural_content[: match.start()].count("\n") + 1
                findings.append(ReviewFinding(
                    severity="high",
                    file=file_path,
                    line=line_num,
                    rule=rule_id,
                    message=message,
                    suggested_fix=fix,
                ))

    # Quality checks (all files)
    for pattern, rule_id, severity, message, fix in _QUALITY_PATTERNS:
        for match in pattern.finditer(content):
            line_num = content[: match.start()].count("\n") + 1
            findings.append(ReviewFinding(
                severity=severity,
                file=file_path,
                line=line_num,
                rule=rule_id,
                message=message,
                suggested_fix=fix,
            ))

    return findings


def review_files(
    file_paths: List[str],
    read_file,  # callable(path: str) -> str
) -> ReviewResult:
    """Review a list of files using the provided reader function.

    Args:
        file_paths: list of POSIX file paths
        read_file: callable that takes a path string and returns file content

    Returns:
        ReviewResult containing all findings
    """
    result = ReviewResult(files_reviewed=list(file_paths))
    for path in file_paths:
        try:
            content = read_file(path)
        except Exception:
            continue
        findings = review_file_content(path, content)
        result.findings.extend(findings)
    return result


_ADDED_FUNC_RE = re.compile(r"^\+\s*def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", re.MULTILINE)
_ADDED_TEST_RE = re.compile(r"^\+\s*def\s+(test[_a-zA-Z0-9]+)\s*\(", re.MULTILINE)


def find_test_gaps(
    patch_text: str,
    changed_files: List[str],
) -> List[UncoveredFunction]:
    """Find public functions added in the diff that have no corresponding test.

    Only checks non-test source files. Skips private functions (starting with _).
    A test is considered present if the diff adds a function named
    ``test_<func_name>`` or ``test<FuncName>`` anywhere in the diff.
    """
    # Collect all newly added test function names from the whole diff
    added_tests: set[str] = {m.group(1).lower() for m in _ADDED_TEST_RE.finditer(patch_text)}

    gaps: List[UncoveredFunction] = []
    gaps.extend(_find_validator_test_file_gaps(changed_files))
    source_files = [
        f for f in changed_files
        if f.endswith(".py")
        and "test" not in PurePosixPath(f.replace("\\", "/")).name
        and "test" not in PurePosixPath(f.replace("\\", "/")).parts
    ]

    if not source_files or not patch_text:
        return gaps

    # Split patch into per-file hunks to attribute functions to the right file
    file_hunk_re = re.compile(r"^diff --git.*?(?=^diff --git|\Z)", re.MULTILINE | re.DOTALL)
    for hunk_match in file_hunk_re.finditer(patch_text):
        hunk = hunk_match.group(0)
        # Identify which source file this hunk belongs to
        file_header = re.search(r"^\+\+\+ b/(.+)$", hunk, re.MULTILINE)
        if not file_header:
            continue
        hunk_file = file_header.group(1).strip()
        # Normalise to match changed_files list
        if hunk_file not in source_files and hunk_file.replace("\\", "/") not in source_files:
            continue

        # Very common method names that appear everywhere — not worth flagging
        _GENERIC_NAMES = {
            "to_dict", "from_dict", "to_json", "from_json", "render", "run",
            "format_report", "format_line", "format_markdown", "setup", "teardown",
            "main", "init", "parse", "load", "save", "close", "open", "read", "write",
            "update", "reset", "clear", "validate", "check",
        }

        for m in _ADDED_FUNC_RE.finditer(hunk):
            func_name = m.group(1)
            # Skip private, dunder, test, and very generic functions
            if func_name.startswith("_") or func_name.startswith("test"):
                continue
            if func_name in _GENERIC_NAMES:
                continue
            # Check if a test was added anywhere in the diff
            expected_test = f"test_{func_name}".lower()
            if expected_test not in added_tests and not any(
                t.startswith(f"test_{func_name}".lower()) or t.startswith(f"test{func_name}".lower())
                for t in added_tests
            ):
                gaps.append(UncoveredFunction(source_file=hunk_file, function_name=func_name))

    return gaps


_VALIDATOR_SOURCE_PATHS = {
    "drift_gate/core/policy/validator.py",
    "drift_gate/core/policy/loader.py",
    "drift_gate/core/models/policy.py",
}
_VALIDATOR_TEST_PATH = "drift_gate/tests/test_validator.py"


def _find_validator_test_file_gaps(changed_files: List[str]) -> List[UncoveredFunction]:
    """Require validator-focused tests when policy validation files change."""
    normalized = {f.replace("\\", "/") for f in changed_files}
    if _VALIDATOR_TEST_PATH in normalized:
        return []
    return [
        UncoveredFunction(
            source_file=path,
            function_name="validator_contract",
            gap_type="validator-test-file",
            expected_test_file=_VALIDATOR_TEST_PATH,
            message="Policy validator changes need drift_gate/tests/test_validator.py coverage.",
        )
        for path in sorted(normalized & _VALIDATOR_SOURCE_PATHS)
    ]


def find_reporter_field_gaps(
    result_dict: dict,
    rendered_outputs: dict[str, str],
    *,
    ignored_fields: Optional[set[str]] = None,
) -> List[UncoveredFunction]:
    """Find EvaluationResult fields that are absent from reporter output."""
    ignored = ignored_fields or set()
    aliases = {
        "gate": {"gate decision"},
        "ignore_audit": {"applied ignores", "rejected ignores"},
        "rejected_ignores": {"rejected ignores"},
        "result": {"result", "pass", "warn", "fail"},
        "rule_decisions": {"rule summary", "rule pass/fail"},
        "scan_metrics": {"scanned files", "runtime", "evaluated rules"},
        "skipped_rules": {"skipped rules", "applied ignores"},
        "temporal_warnings": {"temporal warnings", "temporal gate warnings"},
        "violations": {"violations", "contract drift"},
    }
    gaps: List[UncoveredFunction] = []
    for field_name in sorted(result_dict):
        if field_name in ignored:
            continue
        labels = {field_name, field_name.replace("_", " ")}
        labels.update(aliases.get(field_name, set()))
        if any(
            any(label in output.lower() for label in labels)
            for output in rendered_outputs.values()
        ):
            continue
        gaps.append(
            UncoveredFunction(
                source_file="drift_gate/core/models/result.py",
                function_name=field_name,
                gap_type="reporter-field-display",
                message=(
                    f"`{field_name}` is serialized by EvaluationResult.to_dict() "
                    "but was not found in reporter output."
                ),
            )
        )
    return gaps


def _is_core_file(path: str) -> bool:
    """Return True if the path is inside drift_gate/core/."""
    parts = PurePosixPath(path.replace("\\", "/")).parts
    try:
        core_idx = parts.index("core")
        # Must be drift_gate/core/... (core is inside drift_gate)
        return core_idx > 0 and "drift_gate" in parts
    except ValueError:
        return False


def _strip_python_strings_and_comments(content: str) -> str:
    """Blank string/comment tokens while preserving line and column offsets."""
    lines = content.splitlines(keepends=True)
    if not lines:
        return content
    mutable = [list(line) for line in lines]
    try:
        tokens = tokenize.generate_tokens(io.StringIO(content).readline)
    except tokenize.TokenError:
        return content

    for token in tokens:
        if token.type not in (tokenize.STRING, tokenize.COMMENT):
            continue
        (start_line, start_col), (end_line, end_col) = token.start, token.end
        for line_no in range(start_line, end_line + 1):
            idx = line_no - 1
            if idx < 0 or idx >= len(mutable):
                continue
            line_start = start_col if line_no == start_line else 0
            line_end = end_col if line_no == end_line else len(mutable[idx])
            for col in range(line_start, min(line_end, len(mutable[idx]))):
                if mutable[idx][col] not in ("\n", "\r"):
                    mutable[idx][col] = " "
    return "".join("".join(line) for line in mutable)
