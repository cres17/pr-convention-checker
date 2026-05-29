import json
from pathlib import Path

import pytest

from drift_gate.adapters.cli.runner import run_cli
from drift_gate.adapters.eval.runner import (
    benchmark_gate_failures,
    compare_engines,
    compare_paths,
    discover_fixture_paths,
    evaluate_paths,
    render_engine_comparison_html,
    render_engine_comparison_markdown,
    render_comparison_html,
    render_comparison_markdown,
    render_markdown,
    write_case_reports,
)


FIXTURES = Path(__file__).parent / "fixtures"


class TestEvalRunner:

    def test_default_fixtures_pass(self):
        summary = evaluate_paths(discover_fixture_paths(FIXTURES))

        assert summary.total >= 11
        assert summary.failed == 0
        assert summary.false_positive_count == 0
        assert summary.false_negative_count == 0
        assert summary.precision == 1.0
        assert summary.recall == 1.0
        assert summary.f1 == 1.0
        assert summary.runtime_seconds >= 0
        assert summary.files_per_second >= 0
        assert "api" in summary.category_metrics

    def test_markdown_report_contains_metrics(self):
        summary = evaluate_paths(discover_fixture_paths(FIXTURES))
        md = render_markdown(summary)

        assert "# Drift Gate Eval" in md
        assert "Precision" in md
        assert "Category Metrics" in md
        assert "Files/sec" in md
        assert "False positives" in md
        assert "pr_api_change.json" in md

    def test_baseline_comparison_shows_patch_aware_improvement(self):
        paths = discover_fixture_paths(FIXTURES)
        comparison = compare_paths(paths)

        assert comparison.baseline.false_positive_count == 3
        assert comparison.candidate.false_positive_count == 0
        assert comparison.false_positive_delta == 3
        assert comparison.candidate.failed == 0

    def test_comparison_markdown_contains_benchmark_table(self):
        comparison = compare_paths(discover_fixture_paths(FIXTURES))
        md = render_comparison_markdown(comparison)

        assert "# Drift Gate Benchmark" in md
        assert "Path-only baseline" in md
        assert "Patch-aware candidate" in md
        assert "Files/sec" in md
        assert "Category" in md
        assert "False positive reduction: 3" in md

    def test_comparison_html_contains_shareable_report(self):
        comparison = compare_paths(discover_fixture_paths(FIXTURES))
        html = render_comparison_html(comparison)

        assert "<!doctype html>" in html
        assert "Drift Gate Benchmark" in html
        assert "False Positive Reduction" in html
        assert "pr_comment_only_api_no_doc.json" in html
        assert "Description" in html
        assert "Category" in html
        assert "Raw JSON reports supported" in html

    def test_multi_engine_comparison_reports_all_modes(self):
        comparison = compare_engines(
            discover_fixture_paths(FIXTURES),
            ["path-only", "patch-aware", "semantic-aware", "llm-enriched"],
        )
        md = render_engine_comparison_markdown(comparison)
        html = render_engine_comparison_html(comparison)

        assert set(comparison.summaries) == {
            "path-only", "patch-aware", "semantic-aware", "llm-enriched",
        }
        assert "Multi-Engine Benchmark" in md
        assert "semantic-aware" in md
        assert "llm-enriched" in html

    def test_case_report_dir_writes_raw_reports(self, tmp_path):
        comparison = compare_paths(discover_fixture_paths(FIXTURES))

        write_case_reports(comparison, tmp_path)

        assert (tmp_path / "summary.json").exists()
        assert (
            tmp_path
            / "candidate"
            / "pr_comment_only_api_no_doc.report.json"
        ).exists()
        raw = json.loads(
            (
                tmp_path
                / "candidate"
                / "pr_comment_only_api_no_doc.report.json"
            ).read_text(encoding="utf-8")
        )
        assert raw["actual_report"]["result"] == "pass"
        assert raw["category"] == "api"
        assert "violations" in raw["actual_report"]

    def test_case_report_dir_writes_multi_engine_reports(self, tmp_path):
        comparison = compare_engines(
            discover_fixture_paths(FIXTURES),
            ["path-only", "semantic-aware"],
        )
        write_case_reports(comparison, tmp_path)

        assert (tmp_path / "path-only" / "pr_api_change.report.json").exists()
        assert (tmp_path / "semantic-aware" / "pr_api_change.report.json").exists()

    def test_benchmark_gate_passes_with_current_budgets(self):
        comparison = compare_paths(discover_fixture_paths(FIXTURES))

        failures = benchmark_gate_failures(
            comparison,
            max_fp=0,
            max_fn=0,
            min_f1=1.0,
            min_f1_delta=0.05,
        )

        assert failures == []

    def test_false_positive_is_counted(self, tmp_path):
        data = json.loads((FIXTURES / "pr_docs_only.json").read_text(encoding="utf-8"))
        data["changed_files"] = [
            {
                "path": "src/routes/users.ts",
                "status": "modified",
                "patch": "",
            }
        ]
        data["expected"] = {
            "result": "pass",
            "violation_rule_ids": [],
        }
        path = tmp_path / "false_positive.json"
        path.write_text(json.dumps(data), encoding="utf-8")

        summary = evaluate_paths([path])

        assert summary.failed == 1
        assert summary.false_positive_count == 1
        assert summary.cases[0].false_positive_rules == ["api-contract-sync"]

    def test_recursive_fixture_discovery_supports_external_packs(self, tmp_path):
        pack = tmp_path / "real-world" / "api"
        pack.mkdir(parents=True)
        fixture = pack / "sample.json"
        fixture.write_text(
            (FIXTURES / "pr_docs_only.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        shallow = discover_fixture_paths(tmp_path)
        recursive = discover_fixture_paths(tmp_path, recursive=True)

        assert shallow == []
        assert recursive == [fixture]

    def test_recursive_real_oss_style_sample_eval(self):
        paths = discover_fixture_paths(FIXTURES / "real_oss_samples", recursive=True)
        summary = evaluate_paths(paths)

        assert summary.total == 1
        assert summary.passed == 1
        assert summary.cases[0].source == "real-oss-style-sample"

    def test_benchmark_gate_reports_budget_failures(self, tmp_path):
        data = json.loads((FIXTURES / "pr_docs_only.json").read_text(encoding="utf-8"))
        data["changed_files"] = [
            {
                "path": "src/routes/users.ts",
                "status": "modified",
                "patch": "",
            }
        ]
        data["expected"] = {
            "result": "pass",
            "violation_rule_ids": [],
        }
        path = tmp_path / "false_positive.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        summary = evaluate_paths([path])

        failures = benchmark_gate_failures(summary, max_fp=0, max_fn=0, min_f1=1.0)

        assert any("false positives" in failure for failure in failures)
        assert any("F1" in failure for failure in failures)

    def test_cli_eval_subcommand_runs_budgeted_comparison(self, capsys):
        with pytest.raises(SystemExit) as exc:
            run_cli([
                "eval",
                str(FIXTURES),
                "--compare-baseline",
                "--max-fp",
                "0",
                "--max-fn",
                "0",
                "--min-f1",
                "1.0",
            ])

        assert exc.value.code == 0
        assert "Drift Gate Benchmark" in capsys.readouterr().out

    def test_cli_eval_subcommand_runs_multi_engine_comparison(self, capsys):
        with pytest.raises(SystemExit) as exc:
            run_cli([
                "eval",
                str(FIXTURES),
                "--engines",
                "path-only,patch-aware,semantic-aware",
            ])

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "Multi-Engine Benchmark" in out
        assert "semantic-aware" in out

    def test_cli_init_preset_writes_target_policy(self, tmp_path):
        policy_path = tmp_path / ".drift-gate.yml"

        with pytest.raises(SystemExit) as exc:
            run_cli([
                "init",
                "--policy",
                str(policy_path),
                "--preset",
                "api",
            ])

        assert exc.value.code == 0
        policy_text = policy_path.read_text(encoding="utf-8")
        assert "api-contract-sync" in policy_text
        assert "env-config-sync" not in policy_text

    def test_cli_init_auth_and_ci_presets(self, tmp_path):
        auth_policy = tmp_path / "auth.yml"
        ci_policy = tmp_path / "ci.yml"

        with pytest.raises(SystemExit) as auth_exit:
            run_cli(["init", "--policy", str(auth_policy), "--preset", "auth"])
        with pytest.raises(SystemExit) as ci_exit:
            run_cli(["init", "--policy", str(ci_policy), "--preset", "ci"])

        assert auth_exit.value.code == 0
        assert ci_exit.value.code == 0
        assert "auth-security-sync" in auth_policy.read_text(encoding="utf-8")
        assert "workflow-secret-sync" in ci_policy.read_text(encoding="utf-8")

    def test_cli_explain_rule(self, tmp_path, capsys):
        policy = tmp_path / "policy.yml"
        policy.write_text(
            """
rules:
  - id: api-contract-sync
    when:
      any_changed:
        - "src/routes/**"
      min_change_intensity: signature-change
    require:
      groups:
        - name: "API docs"
          any_changed:
            - "docs/api/**"
    severity: blocker
    message: "API changed without docs"
gate:
  fail_on_blocker: true
  fail_on_major_count: 2
""",
            encoding="utf-8",
        )

        with pytest.raises(SystemExit) as exc:
            run_cli(["explain", "api-contract-sync", "--policy", str(policy)])

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "Drift Gate Rule: api-contract-sync" in out
        assert "Min change intensity" in out
        assert "docs/api/**" in out

    def test_cli_init_auto_uses_repo_recommendations(self, tmp_path, monkeypatch, capsys):
        (tmp_path / "src" / "routes").mkdir(parents=True)
        (tmp_path / "src" / "routes" / "users.ts").write_text(
            "export function users() {}\n",
            encoding="utf-8",
        )
        policy_path = tmp_path / ".drift-gate.yml"
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit) as exc:
            run_cli(["init", "--preset", "auto", "--policy", str(policy_path)])

        assert exc.value.code == 0
        policy_text = policy_path.read_text(encoding="utf-8")
        out = capsys.readouterr().out
        assert "Preset: api" in out
        assert "Repo recommendations" in out
        assert "docs/api/**" in out
        assert "api-contract-sync" in policy_text

    def test_cli_setup_creates_policy_and_mcp_config(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit) as exc:
            run_cli(["setup"])

        assert exc.value.code == 0
        assert (tmp_path / ".drift-gate.yml").exists()
        mcp = (tmp_path / ".mcp.json").read_text(encoding="utf-8")
        assert '"drift-gate"' in mcp
        assert '"serve"' in mcp
        out = capsys.readouterr().out
        assert "Drift Gate setup complete" in out
        assert "Daily commands" in out

    def test_cli_init_recommend_detects_framework_and_docs(self, tmp_path, monkeypatch, capsys):
        (tmp_path / "package.json").write_text(
            '{"dependencies":{"next":"latest","express":"latest"}}',
            encoding="utf-8",
        )
        (tmp_path / "app" / "api").mkdir(parents=True)
        (tmp_path / "app" / "api" / "route.ts").write_text("", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit) as exc:
            run_cli(["init", "--recommend"])

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "Express" in out
        assert "Next.js" in out
        assert "docs/api/**" in out

    def test_doctor_dead_rule_warning_helper(self, tmp_path):
        from drift_gate.adapters.cli.runner import _dead_rule_warnings
        from drift_gate.core.models.policy import Policy

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
        policy = Policy.from_dict({
            "rules": [{
                "id": "dead-rule",
                "when": {"any_changed": ["missing/routes/**"]},
                "require": {"groups": [{
                    "name": "Docs",
                    "any_changed": ["docs/**"],
                }]},
                "severity": "minor",
            }],
        })

        warnings = _dead_rule_warnings(policy, tmp_path)

        assert warnings
        assert "dead-rule" in warnings[0]
