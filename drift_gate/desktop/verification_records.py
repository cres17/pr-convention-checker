"""Read-only links between requirements and an existing test-result file.

The app never runs tests. A user-chosen JUnit XML (pytest --junitxml and most
runners) or Jest/Vitest JSON file is parsed, and tests whose names contain an
item's patterns are attached to it as an *automatic verification record*. The
record is shown next to the manual verification; it never changes the progress
counts, because a passing test does not prove the completion condition.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 20_000_000
MAX_TESTS = 50_000
MAX_PATTERNS = 5
MAX_PATTERN_LENGTH = 200
MAX_FAILING_LISTED = 5
MAX_TEST_SOURCES = 2000
MAX_TEST_SOURCE_BYTES = 512_000
# Clock and checkout noise: a code file this much newer than the results counts as changed after them.
NEWER_TOLERANCE_SECONDS = 2.0
TEST_SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".go", ".java", ".kt", ".rs", ".swift", ".vue", ".rb", ".cs"}
_TEST_FILE = re.compile(
    r"(^|/)(test_[^/]*|[^/]*_test\.[^/]*|[^/]*\.(test|spec)\.[^/]*|[^/]*Tests?\.[^/]*)$"
)
_TEST_DIRECTORY = re.compile(r"(^|/)(tests?|__tests__|spec)/")
_DOCTYPE = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)


def marker(item_id: str) -> str:
    """Text that links a test to an item without any configuration: put it in the test name."""
    return f"req-{item_id[:8]}"


def _junit(data: bytes) -> list[dict]:
    if _DOCTYPE.search(data):
        raise ValueError("DTD가 포함된 XML은 읽지 않습니다.")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"JUnit XML을 읽지 못했습니다: {exc}") from exc
    tests = []
    for case in root.iter("testcase"):
        name = case.get("name", "")
        classname = case.get("classname", "")
        children = {child.tag for child in case}
        status = (
            "failed" if children & {"failure", "error"}
            else "skipped" if "skipped" in children
            else "passed"
        )
        tests.append({"name": f"{classname}::{name}" if classname else name, "status": status})
        if len(tests) > MAX_TESTS:
            raise ValueError("테스트 결과가 너무 많습니다.")
    return tests


def _jest(data: bytes) -> list[dict]:
    try:
        payload = json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"JSON을 읽지 못했습니다: {exc}") from exc
    suites = payload.get("testResults") if isinstance(payload, dict) else None
    if not isinstance(suites, list):
        raise ValueError("Jest/Vitest JSON 형식(testResults)이 아닙니다.")
    tests = []
    for suite in suites:
        if not isinstance(suite, dict):
            continue
        file = re.split(r"[\\/]", str(suite.get("name", "")))[-1]  # Windows paths use backslashes
        for result in suite.get("assertionResults") or []:
            if not isinstance(result, dict):
                continue
            title = str(result.get("fullName") or result.get("title") or "")
            status = {"passed": "passed", "failed": "failed"}.get(str(result.get("status")), "skipped")
            tests.append({"name": f"{file}::{title}" if file else title, "status": status})
            if len(tests) > MAX_TESTS:
                raise ValueError("테스트 결과가 너무 많습니다.")
    return tests


def parse_results(path: str | Path) -> dict:
    """Parse a result file into ``{"format", "file", "modified", "tests": [{name, status}]}``."""
    target = Path(path)
    if not target.is_file():
        raise ValueError("테스트 결과 파일을 찾지 못했습니다.")
    stat = target.stat()
    if stat.st_size > MAX_BYTES:
        raise ValueError("테스트 결과 파일이 너무 큽니다(20MB 초과).")
    data = target.read_bytes()
    first = data.lstrip()[:1]
    if first == b"<":
        kind, tests = "junit", _junit(data)
    elif first == b"{":
        kind, tests = "jest", _jest(data)
    else:
        raise ValueError("JUnit XML 또는 Jest/Vitest JSON 파일을 선택해 주세요.")
    return {
        "format": kind,
        "file": target.name,
        "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "mtime": stat.st_mtime,
        "tests": tests,
    }


def clean_patterns(value: object) -> list[str] | None:
    """Normalized user patterns, or None when the value is not a valid pattern list."""
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_PATTERNS:
        return None
    patterns = []
    for entry in value:
        if not isinstance(entry, str) or len(entry) > MAX_PATTERN_LENGTH:
            return None
        if entry.strip() and entry.strip() not in patterns:
            patterns.append(entry.strip())
    return patterns


def _code_newer(root: Path | None, item: dict, results_mtime: float | None) -> bool:
    """The item's evidence file was modified after the result file was written (heuristic)."""
    evidence = item.get("evidence")
    if root is None or results_mtime is None or not isinstance(evidence, dict):
        return False
    relative = evidence.get("path")
    if not isinstance(relative, str):
        return False
    try:
        return (root / relative).stat().st_mtime > results_mtime + NEWER_TOLERANCE_SECONDS
    except OSError:
        return False


def link_tests(parsed: dict, items: list[dict], root: Path | None = None) -> dict:
    """Attach matching tests to each included item (patterns plus the ``req-`` marker).

    With ``root``, an item is also flagged ``code_newer`` when its evidence file was
    changed after the result file was written, i.e. the results may predate the code.
    """
    tests = parsed["tests"]
    linked = {}
    for item in items:
        if not item.get("included"):
            continue
        patterns = clean_patterns(item.get("test_patterns")) or []
        needles = [*patterns, marker(item["id"])]
        matched = [t for t in tests if any(needle in t["name"] for needle in needles)]
        if not matched and not patterns:
            continue
        counts = {status: sum(1 for t in matched if t["status"] == status) for status in ("passed", "failed", "skipped")}
        linked[item["id"]] = {
            "patterns": patterns,
            "matched": len(matched),
            **counts,
            "failing": [t["name"] for t in matched if t["status"] == "failed"][:MAX_FAILING_LISTED],
            "no_match": not matched,
            "code_newer": bool(matched) and _code_newer(root, item, parsed.get("mtime")),
        }
    return {
        "format": parsed["format"],
        "file": parsed["file"],
        "modified": parsed["modified"],
        "total": len(tests),
        "items": linked,
    }


def is_test_source(path: str) -> bool:
    """Whether a repository path looks like a test file (by name or test folder)."""
    return (
        Path(path).suffix.lower() in TEST_SOURCE_SUFFIXES
        and bool(_TEST_FILE.search(path) or _TEST_DIRECTORY.search(path))
    )


def find_unmatched_patterns(root: Path, files: set[str], items: list[dict]) -> dict[str, list[str]]:
    """Per item, the user's test-name patterns that appear in no test file of the repository.

    Catches typos before any result file exists. A pattern counts as found when the
    text appears anywhere in a test file (a function name, a describe/it title), so this
    is a hint, not proof that a test with that exact name exists.
    """
    wanted = {
        item["id"]: patterns
        for item in items
        if item.get("included") and (patterns := clean_patterns(item.get("test_patterns")))
    }
    if not wanted:
        return {}
    remaining = {pattern for patterns in wanted.values() for pattern in patterns}
    candidates = sorted(name for name in files if is_test_source(name))[:MAX_TEST_SOURCES]
    for name in candidates:
        if not remaining:
            break
        try:
            target = root / name
            if target.is_symlink() or target.stat().st_size > MAX_TEST_SOURCE_BYTES:
                continue
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        remaining -= {pattern for pattern in remaining if pattern in text}
    return {
        item_id: missing
        for item_id, patterns in wanted.items()
        if (missing := [pattern for pattern in patterns if pattern in remaining])
    }
