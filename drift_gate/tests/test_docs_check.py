"""
Tests for docs-check (README/docs consistency checker).
No network, no subprocess. All I/O is mocked via string content.
"""
from __future__ import annotations

import pytest

from drift_gate.adapters.docs.readme_contract import (
    DocsCheckResult,
    DocsWarning,
    check_docs,
    extract_cli_commands_from_docs,
    extract_json_keys_from_docs,
    extract_yaml_keys_from_docs,
    find_stale_limitations,
    get_argparse_commands,
    get_evaluation_result_keys,
    get_policy_top_level_fields,
)


# ── CLI command extraction ─────────────────────────────────────────────────────

class TestExtractCliCommands:
    def test_extracts_from_bash_code_block(self):
        md = "```bash\npy main.py check --json\n```"
        cmds = extract_cli_commands_from_docs(md)
        assert "check" in cmds

    def test_extracts_multiple_commands(self):
        md = (
            "```bash\n"
            "py main.py doctor\n"
            "py main.py eval --compare-baseline\n"
            "```"
        )
        cmds = extract_cli_commands_from_docs(md)
        assert "doctor" in cmds
        assert "eval" in cmds

    def test_extracts_from_inline_backtick(self):
        md = "Use `py main.py self-audit --checklist file.md` to audit."
        cmds = extract_cli_commands_from_docs(md)
        assert "self-audit" in cmds

    def test_ignores_pip_and_git(self):
        md = "```bash\npip install drift-gate\ngit commit -m 'fix'\n```"
        cmds = extract_cli_commands_from_docs(md)
        assert "install" not in cmds
        assert "commit" not in cmds

    def test_deduplicates_commands(self):
        md = "```bash\npy main.py check\npy main.py check\n```"
        cmds = extract_cli_commands_from_docs(md)
        assert cmds.count("check") == 1

    def test_no_commands_in_plain_text(self):
        md = "This document describes the check subcommand without code blocks."
        cmds = extract_cli_commands_from_docs(md)
        # "check" appears in plain text but not in a code block → not extracted
        assert cmds == [] or "check" not in cmds


class TestExtractJsonKeys:
    def test_extracts_top_level_keys(self):
        md = '```json\n{"result": "pass", "violations": [], "gate": {}}\n```'
        keys = extract_json_keys_from_docs(md)
        assert "result" in keys
        assert "violations" in keys
        assert "gate" in keys

    def test_skips_malformed_json(self):
        md = "```json\n{not valid json\n```"
        keys = extract_json_keys_from_docs(md)
        assert keys == []

    def test_empty_document(self):
        keys = extract_json_keys_from_docs("")
        assert keys == []

    def test_nested_keys_not_included(self):
        md = '```json\n{"summary": {"blocker": 0}}\n```'
        keys = extract_json_keys_from_docs(md)
        assert "summary" in keys
        assert "blocker" not in keys  # nested key, not top-level


class TestGetEvaluationResultKeys:
    def test_returns_expected_keys(self):
        keys = get_evaluation_result_keys()
        for expected in ("result", "violations", "gate", "summary", "change_types"):
            assert expected in keys

    def test_returns_sorted_list(self):
        keys = get_evaluation_result_keys()
        assert keys == sorted(keys)


class TestGetArgparseCommands:
    def test_returns_known_commands(self):
        from drift_gate.adapters.cli.runner import _build_parser
        parser = _build_parser()
        cmds = get_argparse_commands(parser)
        for expected in ("check", "doctor", "eval", "init", "self-audit", "docs-check", "review"):
            assert expected in cmds, f"Expected command '{expected}' not found in {cmds}"

    def test_docs_check_accepts_positional_docs_file(self):
        from drift_gate.adapters.cli.runner import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["docs-check", "README.md", "--json"])

        assert args.command == "docs-check"
        assert args.docs_positional == ["README.md"]

    def test_report_out_alias_maps_to_markdown_output(self):
        from drift_gate.adapters.cli.runner import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["report", "--out", "report.md"])

        assert args.out_md == "report.md"


class TestFindStaleLimitations:
    def test_detects_no_historical_tracking(self):
        content = "This tool has no historical tracking of past runs."
        warnings = find_stale_limitations(content, "README.md")
        assert len(warnings) >= 1
        assert any("historical" in w.message.lower() for w in warnings)

    def test_no_false_positive_on_clean_text(self):
        content = "# Drift Gate\n\nA policy enforcement engine."
        warnings = find_stale_limitations(content, "README.md")
        assert warnings == []

    def test_captures_line_number(self):
        content = "Line 1\nLine 2 has no historical tracking here\nLine 3"
        warnings = find_stale_limitations(content, "README.md")
        assert warnings[0].line == 2


# ── full check_docs ────────────────────────────────────────────────────────────

class TestCheckDocs:
    def test_missing_file_produces_warning(self, tmp_path):
        result = check_docs([tmp_path / "nonexistent.md"])
        kinds = [w.kind for w in result.warnings]
        assert "missing-docs-file" in kinds

    def test_known_command_no_warning(self, tmp_path):
        """A command that exists in argparse should produce no missing-cli-command warning."""
        doc = tmp_path / "README.md"
        doc.write_text("```bash\npy main.py check\n```\n", encoding="utf-8")
        result = check_docs([doc])
        kinds = [w.kind for w in result.warnings]
        assert "missing-cli-command" not in kinds

    def test_unknown_command_produces_warning(self, tmp_path):
        """A command in docs but not in argparse should produce a warning."""
        doc = tmp_path / "README.md"
        doc.write_text("```bash\npy main.py nonexistent-command\n```\n", encoding="utf-8")
        result = check_docs([doc])
        kinds = [w.kind for w in result.warnings]
        assert "missing-cli-command" in kinds

    def test_to_dict_structure(self, tmp_path):
        doc = tmp_path / "README.md"
        doc.write_text("# Docs\n", encoding="utf-8")
        result = check_docs([doc])
        d = result.to_dict()
        assert "docs_check" in d
        assert "warnings" in d["docs_check"]
        assert "checked_commands" in d["docs_check"]
        assert "checked_json_keys" in d["docs_check"]

    def test_clean_docs_no_warnings(self, tmp_path):
        doc = tmp_path / "README.md"
        doc.write_text("# Clean\nNo stale content here.\n", encoding="utf-8")
        result = check_docs([doc])
        # No stale limitations, no commands, no JSON blocks → minimal or no warnings
        json_schema_warnings = [w for w in result.warnings if w.kind != "json-schema-mismatch"]
        assert len(json_schema_warnings) == 0

    def test_format_report_no_warnings(self, tmp_path):
        doc = tmp_path / "README.md"
        doc.write_text("# Clean\n", encoding="utf-8")
        result = check_docs([doc])
        # Remove JSON schema mismatch for cleaner test
        result.warnings = []
        report = result.format_report()
        assert "No docs-consistency issues found" in report

    def test_format_report_with_warnings(self, tmp_path):
        doc = tmp_path / "README.md"
        doc.write_text("This has no historical tracking.\n", encoding="utf-8")
        result = check_docs([doc])
        report = result.format_report()
        assert "## docs-consistency warnings" in report

    def test_to_dict_includes_policy_fields(self, tmp_path):
        doc = tmp_path / "README.md"
        doc.write_text("```yaml\nrules:\n  - id: test\n```\n", encoding="utf-8")
        result = check_docs([doc])
        d = result.to_dict()
        assert "checked_policy_fields" in d["docs_check"]


# ── YAML key extraction ────────────────────────────────────────────────────────

class TestExtractYamlKeys:
    def test_extracts_top_level_keys(self):
        md = "```yaml\nrules:\n  - id: test\ngate:\n  fail_on_blocker: true\n```"
        keys = extract_yaml_keys_from_docs(md)
        assert "rules" in keys
        assert "gate" in keys

    def test_does_not_extract_indented_keys(self):
        md = "```yaml\nrules:\n  - id: test\n    severity: blocker\n```"
        keys = extract_yaml_keys_from_docs(md)
        assert "id" not in keys
        assert "severity" not in keys

    def test_empty_document(self):
        keys = extract_yaml_keys_from_docs("")
        assert keys == []

    def test_multiple_blocks(self):
        md = "```yaml\nrules: []\n```\nSome text.\n```yaml\ngate:\n  fail_on_blocker: true\n```"
        keys = extract_yaml_keys_from_docs(md)
        assert "rules" in keys
        assert "gate" in keys


# ── Policy field model ─────────────────────────────────────────────────────────

class TestGetPolicyTopLevelFields:
    def test_returns_expected_fields(self):
        fields = get_policy_top_level_fields()
        for expected in ("rules", "gate", "ignore_paths", "suppression", "enrichment"):
            assert expected in fields, f"Expected policy field '{expected}' not in {fields}"

    def test_excludes_load_warnings(self):
        fields = get_policy_top_level_fields()
        assert "load_warnings" not in fields

    def test_returns_sorted_list(self):
        fields = get_policy_top_level_fields()
        assert fields == sorted(fields)


# ── Policy field mismatch detection ───────────────────────────────────────────

class TestPolicyFieldMismatch:
    def test_unknown_yaml_key_produces_warning(self, tmp_path):
        doc = tmp_path / "README.md"
        doc.write_text("```yaml\nunknown_custom_field: value\n```\n", encoding="utf-8")
        result = check_docs([doc])
        kinds = [w.kind for w in result.warnings]
        assert "policy-field-mismatch" in kinds

    def test_known_policy_field_no_warning(self, tmp_path):
        doc = tmp_path / "README.md"
        doc.write_text("```yaml\nrules:\n  - id: test\ngate:\n  fail_on_blocker: true\nignore_paths: []\n```\n", encoding="utf-8")
        result = check_docs([doc])
        mismatch_warnings = [w for w in result.warnings if w.kind == "policy-field-mismatch"]
        assert mismatch_warnings == []

    def test_checked_policy_fields_populated(self, tmp_path):
        doc = tmp_path / "README.md"
        doc.write_text("```yaml\nrules: []\ngate:\n  fail_on_blocker: true\n```\n", encoding="utf-8")
        result = check_docs([doc])
        assert "rules" in result.checked_policy_fields
        assert "gate" in result.checked_policy_fields

    def test_github_actions_yaml_no_false_positive(self, tmp_path):
        doc = tmp_path / "README.md"
        doc.write_text(
            "```yaml\non:\n  push:\n    branches: [main]\njobs:\n  build:\n    runs-on: ubuntu-latest\n```\n",
            encoding="utf-8",
        )
        result = check_docs([doc])
        mismatch_warnings = [w for w in result.warnings if w.kind == "policy-field-mismatch"]
        assert mismatch_warnings == []
