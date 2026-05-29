"""
Tests for deterministic heuristic code review.
No network, no subprocess. Pure unit tests on file content strings.
"""
from __future__ import annotations

import pytest

from drift_gate.core.review.heuristics import (
    ReviewFinding,
    ReviewResult,
    UncoveredFunction,
    _is_core_file,
    find_reporter_field_gaps,
    find_test_gaps,
    review_file_content,
    review_files,
)


# ── _is_core_file ─────────────────────────────────────────────────────────────

class TestIsCoreFile:
    def test_core_file_detected(self):
        assert _is_core_file("drift_gate/core/engine.py") is True

    def test_core_subfolder_detected(self):
        assert _is_core_file("drift_gate/core/models/result.py") is True

    def test_adapter_file_not_core(self):
        assert _is_core_file("drift_gate/adapters/cli/runner.py") is False

    def test_test_file_not_core(self):
        assert _is_core_file("drift_gate/tests/test_engine.py") is False

    def test_bare_core_path_without_package(self):
        # "core/foo.py" without drift_gate/ prefix should not be flagged
        assert _is_core_file("core/foo.py") is False

    def test_windows_path_normalized(self):
        assert _is_core_file("drift_gate\\core\\engine.py") is True


# ── review_file_content — core I/O checks ────────────────────────────────────

class TestCoreIOChecks:
    def test_print_in_core_is_high(self):
        content = "def foo():\n    print('hello')\n"
        findings = review_file_content("drift_gate/core/engine.py", content)
        rules = [f.rule for f in findings]
        assert "core-io-print" in rules
        assert all(f.severity == "high" for f in findings if f.rule == "core-io-print")

    def test_sys_exit_in_core_is_high(self):
        content = "import sys\ndef foo():\n    sys.exit(1)\n"
        findings = review_file_content("drift_gate/core/engine.py", content)
        rules = [f.rule for f in findings]
        assert "core-io-sys-exit" in rules

    def test_subprocess_import_in_core_is_high(self):
        content = "import subprocess\n"
        findings = review_file_content("drift_gate/core/engine.py", content)
        rules = [f.rule for f in findings]
        assert "core-io-subprocess" in rules

    def test_network_import_in_core_is_high(self):
        content = "import urllib.request\n"
        findings = review_file_content("drift_gate/core/engine.py", content)
        rules = [f.rule for f in findings]
        assert "core-io-network" in rules

    def test_urllib_from_import_in_core_is_high(self):
        content = "from urllib import request\n"
        findings = review_file_content("drift_gate/core/engine.py", content)
        rules = [f.rule for f in findings]
        assert "core-io-network" in rules

    def test_print_in_adapter_is_not_flagged(self):
        content = "def foo():\n    print('hello')\n"
        findings = review_file_content("drift_gate/adapters/cli/runner.py", content)
        rules = [f.rule for f in findings]
        assert "core-io-print" not in rules

    def test_clean_core_file_no_findings(self):
        content = (
            "from dataclasses import dataclass\n"
            "from typing import List\n\n"
            "@dataclass\n"
            "class Policy:\n"
            "    rules: List[str]\n"
        )
        findings = review_file_content("drift_gate/core/models/policy.py", content)
        # Only potential: sys import check. Clean file should have 0 high findings
        high = [f for f in findings if f.severity == "high"]
        assert high == []


# ── review_file_content — quality checks ─────────────────────────────────────

class TestQualityChecks:
    def test_mutable_default_list(self):
        content = "def foo(items=[]):\n    pass\n"
        findings = review_file_content("any/file.py", content)
        rules = [f.rule for f in findings]
        assert "mutable-default" in rules

    def test_mutable_default_dict(self):
        content = "def foo(cfg={}):\n    pass\n"
        findings = review_file_content("any/file.py", content)
        rules = [f.rule for f in findings]
        assert "mutable-default-dict" in rules

    def test_bare_except(self):
        content = "try:\n    pass\nexcept:\n    pass\n"
        findings = review_file_content("any/file.py", content)
        rules = [f.rule for f in findings]
        assert "broad-except" in rules

    def test_swallowed_exception(self):
        content = "try:\n    risky()\nexcept Exception:\n    pass\n"
        findings = review_file_content("any/file.py", content)
        rules = [f.rule for f in findings]
        assert "swallowed-exception" in rules

    def test_token_logging_high(self):
        content = 'print(f"key={api_key}")\n'
        findings = review_file_content("any/file.py", content)
        rules = [f.rule for f in findings]
        assert "token-logging" in rules
        tok = next(f for f in findings if f.rule == "token-logging")
        assert tok.severity == "high"

    def test_clean_file_no_quality_issues(self):
        content = (
            "def process(items=None):\n"
            "    if items is None:\n"
            "        items = []\n"
            "    return items\n"
        )
        findings = review_file_content("any/file.py", content)
        assert findings == []


# ── review_files ──────────────────────────────────────────────────────────────

class TestReviewFiles:
    def test_reviews_multiple_files(self):
        files = {
            "drift_gate/core/engine.py": "import subprocess\n",
            "other.py": "def ok():\n    pass\n",
        }

        def read_file(path):
            return files[path]

        result = review_files(list(files.keys()), read_file)
        assert len(result.files_reviewed) == 2
        assert any(f.rule == "core-io-subprocess" for f in result.findings)

    def test_skips_unreadable_file(self):
        def read_file(path):
            if path == "bad.py":
                raise OSError("permission denied")
            return ""

        result = review_files(["bad.py", "ok.py"], read_file)
        # Should not raise; unreadable file is skipped
        assert "bad.py" in result.files_reviewed
        assert "ok.py" in result.files_reviewed

    def test_no_findings_for_clean_files(self):
        files = {"clean.py": "x = 1\n"}
        result = review_files(list(files.keys()), lambda p: files[p])
        assert result.findings == []


# ── ReviewResult output ───────────────────────────────────────────────────────

class TestReviewResultOutput:
    def _make_result(self) -> ReviewResult:
        result = ReviewResult(files_reviewed=["drift_gate/core/engine.py"])
        result.findings.append(ReviewFinding(
            severity="high",
            file="drift_gate/core/engine.py",
            line=5,
            rule="core-io-print",
            message="core layer uses print(). Move output to adapters.",
            suggested_fix="Use adapters for output.",
        ))
        return result

    def test_format_markdown_contains_finding(self):
        result = self._make_result()
        md = result.format_markdown()
        assert "## Drift Gate Code Review" in md
        assert "core-io-print" in md or "print" in md.lower()

    def test_format_markdown_empty_result(self):
        result = ReviewResult(files_reviewed=[])
        md = result.format_markdown()
        assert "No issues found" in md

    def test_to_dict_structure(self):
        result = self._make_result()
        d = result.to_dict()
        assert "review" in d
        assert "findings" in d["review"]
        assert d["review"]["finding_count"] == 1

    def test_has_high_property(self):
        result = self._make_result()
        assert result.has_high is True

    def test_has_high_false_when_no_high(self):
        result = ReviewResult(files_reviewed=[])
        assert result.has_high is False

    def test_by_severity_filters_correctly(self):
        result = self._make_result()
        high_findings = result.by_severity("high")
        assert len(high_findings) == 1
        medium_findings = result.by_severity("medium")
        assert len(medium_findings) == 0


# ── line number accuracy ──────────────────────────────────────────────────────

class TestLineNumbers:
    def test_finding_line_number_correct(self):
        content = "x = 1\ny = 2\nprint('oops')\nz = 3\n"
        findings = review_file_content("drift_gate/core/x.py", content)
        print_findings = [f for f in findings if f.rule == "core-io-print"]
        assert len(print_findings) == 1
        assert print_findings[0].line == 3


# ── filesystem I/O in core ────────────────────────────────────────────────────

class TestFilesystemIOInCore:
    def test_open_in_core_is_high(self):
        content = "def load(path):\n    with open(path) as f:\n        return f.read()\n"
        findings = review_file_content("drift_gate/core/policy/loader.py", content)
        rules = [f.rule for f in findings]
        assert "core-io-filesystem" in rules

    def test_read_text_in_core_is_high(self):
        content = "from pathlib import Path\ndef load(p):\n    return Path(p).read_text()\n"
        findings = review_file_content("drift_gate/core/engine.py", content)
        rules = [f.rule for f in findings]
        assert "core-io-filesystem" in rules

    def test_open_in_adapter_not_flagged(self):
        content = "def load(path):\n    with open(path) as f:\n        return f.read()\n"
        findings = review_file_content("drift_gate/adapters/git/client.py", content)
        rules = [f.rule for f in findings]
        assert "core-io-filesystem" not in rules


# ── test gap detection ────────────────────────────────────────────────────────

_PATCH_WITH_NEW_FUNC = """\
diff --git a/drift_gate/adapters/claude/enricher.py b/drift_gate/adapters/claude/enricher.py
--- a/drift_gate/adapters/claude/enricher.py
+++ b/drift_gate/adapters/claude/enricher.py
@@ -1,3 +1,6 @@
+    def estimate_dry_run(self, result):
+        pass
"""

_PATCH_WITH_FUNC_AND_TEST = """\
diff --git a/drift_gate/adapters/claude/enricher.py b/drift_gate/adapters/claude/enricher.py
--- a/drift_gate/adapters/claude/enricher.py
+++ b/drift_gate/adapters/claude/enricher.py
@@ -1,3 +1,4 @@
+    def estimate_dry_run(self, result):
+        pass
diff --git a/drift_gate/tests/test_enricher.py b/drift_gate/tests/test_enricher.py
--- a/drift_gate/tests/test_enricher.py
+++ b/drift_gate/tests/test_enricher.py
@@ -1,3 +1,4 @@
+    def test_estimate_dry_run(self):
+        pass
"""


class TestFindUncoveredFunctions:
    def test_detects_gap_when_no_test_added(self):
        changed = ["drift_gate/adapters/claude/enricher.py"]
        gaps = find_test_gaps(_PATCH_WITH_NEW_FUNC, changed)
        names = [g.function_name for g in gaps]
        assert "estimate_dry_run" in names

    def test_no_gap_when_test_is_in_diff(self):
        changed = ["drift_gate/adapters/claude/enricher.py"]
        gaps = find_test_gaps(_PATCH_WITH_FUNC_AND_TEST, changed)
        names = [g.function_name for g in gaps]
        assert "estimate_dry_run" not in names

    def test_skips_private_functions(self):
        patch = (
            "diff --git a/drift_gate/adapters/foo.py b/drift_gate/adapters/foo.py\n"
            "+++ b/drift_gate/adapters/foo.py\n"
            "+    def _internal(self):\n"
            "+        pass\n"
        )
        gaps = find_test_gaps(patch, ["drift_gate/adapters/foo.py"])
        names = [g.function_name for g in gaps]
        assert "_internal" not in names

    def test_skips_test_files(self):
        patch = (
            "diff --git a/drift_gate/tests/test_foo.py b/drift_gate/tests/test_foo.py\n"
            "+++ b/drift_gate/tests/test_foo.py\n"
            "+    def new_helper(self):\n"
            "+        pass\n"
        )
        gaps = find_test_gaps(patch, ["drift_gate/tests/test_foo.py"])
        assert gaps == []

    def test_empty_patch_no_gaps(self):
        gaps = find_test_gaps("", ["drift_gate/adapters/foo.py"])
        assert gaps == []

    def test_gap_attributes(self):
        changed = ["drift_gate/adapters/claude/enricher.py"]
        gaps = find_test_gaps(_PATCH_WITH_NEW_FUNC, changed)
        if gaps:
            g = gaps[0]
            assert g.source_file == "drift_gate/adapters/claude/enricher.py"
            assert isinstance(g.function_name, str)

    def test_review_result_includes_test_gaps(self):
        result = ReviewResult(files_reviewed=["drift_gate/adapters/foo.py"])
        result.test_gaps = [UncoveredFunction(source_file="drift_gate/adapters/foo.py", function_name="my_func")]
        md = result.format_markdown()
        assert "Test Gaps" in md
        assert "my_func" in md

    def test_to_dict_includes_test_gaps(self):
        result = ReviewResult(files_reviewed=[])
        result.test_gaps = [UncoveredFunction(source_file="foo.py", function_name="bar")]
        d = result.to_dict()
        assert "test_gaps" in d["review"]
        assert d["review"]["test_gaps"][0]["function_name"] == "bar"

    def test_validator_change_requires_validator_test_file(self):
        gaps = find_test_gaps(
            "",
            ["drift_gate/core/policy/validator.py"],
        )
        assert any(g.gap_type == "validator-test-file" for g in gaps)
        assert gaps[0].expected_test_file == "drift_gate/tests/test_validator.py"

    def test_validator_gap_satisfied_by_validator_test_file(self):
        gaps = find_test_gaps(
            "",
            [
                "drift_gate/core/policy/validator.py",
                "drift_gate/tests/test_validator.py",
            ],
        )
        assert not any(g.gap_type == "validator-test-file" for g in gaps)


class TestReporterFieldGaps:
    def test_detects_result_field_missing_from_reporter_output(self):
        gaps = find_reporter_field_gaps(
            {"result": "pass", "change_types": [], "new_field": "value"},
            {
                "markdown": "Result: pass\nChange types: -",
                "html": "<h1>Result</h1><p>Change Types</p>",
            },
        )
        assert [g.function_name for g in gaps] == ["new_field"]
        assert gaps[0].gap_type == "reporter-field-display"

    def test_reporter_gap_accepts_snake_case_or_readable_label(self):
        gaps = find_reporter_field_gaps(
            {"change_types": [], "scan_metrics": {}},
            {
                "markdown": "Change types\n",
                "html": "scan_metrics",
            },
        )
        assert gaps == []

    def test_current_reporters_cover_evaluation_result_fields_used_by_review(self):
        from drift_gate.adapters.cli.runner import _review_reporter_field_gaps

        gaps = _review_reporter_field_gaps(
            ["drift_gate/core/models/result.py"],
            find_reporter_field_gaps,
        )

        assert gaps == []
