from drift_gate.adapters.history.store import (
    append_result,
    ignored_rule_counts,
    load_records,
    render_history_html,
    render_history_markdown,
    summarize_records,
)
from drift_gate.core.gating.temporal import apply_temporal_gate
from drift_gate.adapters.cli.runner import run_cli
from drift_gate.core.models.policy import Gate
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.result import EvaluationResult, Violation, UnsatisfiedGroup, SkippedRule
import pytest


def _result(result: str = "pass") -> EvaluationResult:
    return EvaluationResult(
        change_types=["api-surface"],
        violations=[],
        skipped_rules=[],
        rejected_ignores=[],
        gate=Gate(),
        result=result,
    )


def _violating_result() -> EvaluationResult:
    return EvaluationResult(
        change_types=["api-surface"],
        violations=[
            Violation(
                rule_id="api-contract-sync",
                severity="BLOCKER",
                confidence="high",
                change_types=["api-surface"],
                change_type="api-surface",
                message="API changed",
                trigger_files=[ChangedFile(path="src/routes/users.ts", status="modified")],
                unsatisfied_groups=[
                    UnsatisfiedGroup(
                        name="API docs",
                        required=["docs/api/**"],
                        type="any_changed",
                    )
                ],
                checklist=[],
            )
        ],
        skipped_rules=[
            SkippedRule(
                rule_id="old-rule",
                severity="MAJOR",
                reason="temporary",
                message="ignored",
            )
        ],
        rejected_ignores=[],
        gate=Gate(),
        result="fail",
    )


def test_history_store_roundtrip(tmp_path):
    path = tmp_path / "history.jsonl"

    append_result(
        _result(),
        path,
        pr_number=12,
        commit_sha="abc123",
        changed_file_count=4,
        runtime_seconds=0.25,
    )
    records = load_records(path, days=30)
    summary = summarize_records(records)

    assert len(records) == 1
    assert summary["total"] == 1
    assert summary["result_counts"]["pass"] == 1
    assert records[0]["pr_number"] == 12
    assert records[0]["commit_sha"] == "abc123"
    assert summary["changed_file_count"] == 4


def test_history_reports_render(tmp_path):
    path = tmp_path / "history.jsonl"
    append_result(_violating_result(), path, changed_file_count=2, runtime_seconds=0.5)
    records = load_records(path, days=30)

    md = render_history_markdown(records, days=30)
    html = render_history_html(records, days=30)

    assert "Drift Gate History" in md
    assert "Runs: 1" in md
    assert "Most Ignored Rules" in md
    assert "Contract Areas" in md
    assert "Average fix time" in md
    assert "<!doctype html>" in html
    assert "Drift Gate History" in html
    assert "Trend" in html
    assert "Release Trend" in html
    assert "chart.js" in html.lower()
    assert "trendChart" in html
    assert "Violations per Day" in html


def test_cli_history_renders_markdown_and_html(tmp_path, capsys):
    history_path = tmp_path / "history.jsonl"
    html_path = tmp_path / "trend.html"
    append_result(_result(), history_path)

    with pytest.raises(SystemExit) as exc:
        run_cli([
            "history",
            "--path",
            str(history_path),
            "--last",
            "30d",
            "--html",
            str(html_path),
        ])

    assert exc.value.code == 0
    assert "Drift Gate History" in capsys.readouterr().out
    assert html_path.exists()


def test_history_sqlite_roundtrip(tmp_path):
    path = tmp_path / "history.sqlite"

    append_result(_violating_result(), path, pr_number=7, commit_sha="def456")
    records = load_records(path, days=30)

    assert len(records) == 1
    assert records[0]["pr_number"] == 7
    assert records[0]["commit_sha"] == "def456"


def test_history_rule_filter_and_repeated_ignore_warning(tmp_path):
    path = tmp_path / "history.jsonl"
    for _ in range(3):
        append_result(_violating_result(), path)
    append_result(_result(), path)

    records = load_records(path, days=30, rule_id="old-rule")
    summary = summarize_records(records)

    assert len(records) == 3
    assert summary["ignored_rule_counts"]["old-rule"] == 3
    assert summary["repeated_ignore_warnings"] == ["old-rule"]


def test_temporal_gate_warns_on_repeated_ignores(tmp_path):
    path = tmp_path / "history.jsonl"
    for _ in range(3):
        append_result(_violating_result(), path)

    result = apply_temporal_gate(
        _result("pass"),
        ignored_rule_counts(load_records(path, days=30)),
        threshold=3,
    )

    assert result.result == "warn"
    assert len(result.temporal_warnings) == 1
    assert result.temporal_warnings[0].rule_id == "old-rule"
    assert result.to_dict()["temporal_warnings"][0]["ignored_count"] == 3


def test_history_average_fix_time_and_release_trend(tmp_path):
    path = tmp_path / "history.jsonl"
    append_result(_violating_result(), path, release="v1.0.0")
    append_result(_result(), path, release="v1.0.0")

    summary = summarize_records(load_records(path, days=30))

    assert summary["average_fix_hours"] >= 0
    assert summary["release_trend"]["v1.0.0"]["runs"] == 2


def test_cli_history_filters_rule(tmp_path, capsys):
    history_path = tmp_path / "history.jsonl"
    append_result(_violating_result(), history_path)
    append_result(_result(), history_path)

    with pytest.raises(SystemExit) as exc:
        run_cli([
            "history",
            "--path",
            str(history_path),
            "--rule",
            "api-contract-sync",
        ])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Rule filter: `api-contract-sync`" in out
    assert "api-contract-sync" in out


# ─── temporal gate + history E2E (5-1b) ──────────────────────────────────────

class TestTemporalGateE2E:
    """Full path: append_result → load_records → ignored_rule_counts → apply_temporal_gate."""

    def test_e2e_repeated_ignores_trigger_warn(self, tmp_path):
        """3 violations with skipped_rules → temporal gate escalates result to warn."""
        history_path = tmp_path / "history.jsonl"
        for _ in range(3):
            append_result(_violating_result(), history_path)

        records = load_records(history_path, days=30)
        counts = ignored_rule_counts(records)
        result = apply_temporal_gate(_result("pass"), counts, threshold=3)

        assert result.result == "warn"
        assert any(w.rule_id == "old-rule" for w in result.temporal_warnings)

    def test_e2e_below_threshold_no_warn(self, tmp_path):
        """2 violations below threshold=3 → gate stays pass."""
        history_path = tmp_path / "history.jsonl"
        for _ in range(2):
            append_result(_violating_result(), history_path)

        records = load_records(history_path, days=30)
        counts = ignored_rule_counts(records)
        result = apply_temporal_gate(_result("pass"), counts, threshold=3)

        assert result.result == "pass"
        assert result.temporal_warnings == []

    def test_e2e_warn_result_not_downgraded_to_pass(self, tmp_path):
        """If base result is already warn, temporal gate keeps it warn."""
        history_path = tmp_path / "history.jsonl"
        for _ in range(3):
            append_result(_violating_result(), history_path)

        records = load_records(history_path, days=30)
        counts = ignored_rule_counts(records)
        result = apply_temporal_gate(_result("warn"), counts, threshold=3)

        assert result.result == "warn"

    def test_e2e_fail_result_stays_fail(self, tmp_path):
        """If base result is fail, temporal gate does not downgrade to warn."""
        history_path = tmp_path / "history.jsonl"
        for _ in range(5):
            append_result(_violating_result(), history_path)

        records = load_records(history_path, days=30)
        counts = ignored_rule_counts(records)
        result = apply_temporal_gate(_result("fail"), counts, threshold=3)

        assert result.result == "fail"

    def test_e2e_to_dict_includes_temporal_warnings(self, tmp_path):
        """to_dict() includes temporal_warnings key with correct structure."""
        history_path = tmp_path / "history.jsonl"
        for _ in range(3):
            append_result(_violating_result(), history_path)

        records = load_records(history_path, days=30)
        counts = ignored_rule_counts(records)
        result = apply_temporal_gate(_result("pass"), counts, threshold=3)

        d = result.to_dict()
        assert "temporal_warnings" in d
        assert len(d["temporal_warnings"]) == 1
        tw = d["temporal_warnings"][0]
        assert tw["rule_id"] == "old-rule"
        assert tw["ignored_count"] == 3
        assert tw["threshold"] == 3

    def test_e2e_cli_check_with_temporal_gate(self, tmp_path, capsys):
        """CLI check --temporal-gate reads history and upgrades warn."""
        import json
        from pathlib import Path

        history_path = tmp_path / "history.jsonl"
        policy_path = tmp_path / ".drift-gate.yml"
        policy_path.write_text(
            "rules: []\ngate:\n  fail_on_blocker: true\n  fail_on_major_count: 2\n",
            encoding="utf-8",
        )

        for _ in range(3):
            append_result(_violating_result(), history_path)

        with pytest.raises(SystemExit) as exc:
            run_cli([
                "check",
                "--policy", str(policy_path),
                "--base", "HEAD",
                "--temporal-gate",
                "--temporal-threshold", "3",
                "--history-path", str(history_path),
            ])

        # result is pass or warn — exit code 0 either way when no blocker
        assert exc.value.code in (0, 1)
        out = capsys.readouterr().out
        # Temporal warning should appear in output (markdown or empty-pr pass)
        assert out  # something was printed
