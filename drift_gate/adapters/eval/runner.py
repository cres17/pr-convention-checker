"""
Offline evaluation runner for Drift Gate fixtures.

The runner measures whether policy changes improve behavior over a stable set
of PR-like JSON cases. It is intentionally local and deterministic.
"""
import argparse
import html
import json
import sys
import time
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List

from drift_gate.adapters.ast.analyzer import enrich_semantic_signals
from drift_gate.core.engine import run
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.policy import Policy
from drift_gate.core.models.result import DriftIgnoreDirective


@dataclass
class EvalCaseResult:
    name: str
    description: str
    category: str
    risk: str
    expected_reason: str
    source: str
    false_positive_target: str
    expected_result: str
    actual_result: str
    expected_rules: List[str]
    actual_rules: List[str]
    actual_report: dict
    changed_file_count: int = 0
    runtime_seconds: float = 0.0
    false_positive_rules: List[str] = field(default_factory=list)
    false_negative_rules: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            self.expected_result == self.actual_result
            and not self.false_positive_rules
            and not self.false_negative_rules
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "risk": self.risk,
            "expected_reason": self.expected_reason,
            "source": self.source,
            "false_positive_target": self.false_positive_target,
            "passed": self.passed,
            "expected_result": self.expected_result,
            "actual_result": self.actual_result,
            "expected_rules": self.expected_rules,
            "actual_rules": self.actual_rules,
            "actual_report": self.actual_report,
            "changed_file_count": self.changed_file_count,
            "runtime_seconds": self.runtime_seconds,
            "false_positive_rules": self.false_positive_rules,
            "false_negative_rules": self.false_negative_rules,
        }


@dataclass
class EvalSummary:
    total: int
    passed: int
    failed: int
    expected_rule_count: int
    actual_rule_count: int
    false_positive_count: int
    false_negative_count: int
    precision: float
    recall: float
    f1: float
    runtime_seconds: float
    files_per_second: float
    cases: List[EvalCaseResult]
    category_metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "expected_rule_count": self.expected_rule_count,
            "actual_rule_count": self.actual_rule_count,
            "false_positive_count": self.false_positive_count,
            "false_negative_count": self.false_negative_count,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "runtime_seconds": self.runtime_seconds,
            "files_per_second": self.files_per_second,
            "category_metrics": self.category_metrics,
            "cases": [case.to_dict() for case in self.cases],
        }


@dataclass
class EvalComparison:
    baseline: EvalSummary
    candidate: EvalSummary

    @property
    def false_positive_delta(self) -> int:
        return self.baseline.false_positive_count - self.candidate.false_positive_count

    @property
    def false_negative_delta(self) -> int:
        return self.baseline.false_negative_count - self.candidate.false_negative_count

    @property
    def f1_delta(self) -> float:
        return self.candidate.f1 - self.baseline.f1

    def to_dict(self) -> dict:
        return {
            "baseline": self.baseline.to_dict(),
            "candidate": self.candidate.to_dict(),
            "improvement": {
                "false_positive_reduction": self.false_positive_delta,
                "false_negative_reduction": self.false_negative_delta,
                "f1_delta": self.f1_delta,
            },
        }


@dataclass
class EvalEngineComparison:
    summaries: dict[str, EvalSummary]

    @property
    def candidate(self) -> EvalSummary:
        return self.summaries.get("semantic-aware") or self.summaries.get("patch-aware") or next(iter(self.summaries.values()))

    def to_dict(self) -> dict:
        return {
            "engines": {
                name: summary.to_dict()
                for name, summary in self.summaries.items()
            }
        }


def benchmark_gate_failures(
    report: EvalSummary | EvalComparison | EvalEngineComparison,
    *,
    max_fp: int | None = None,
    max_fn: int | None = None,
    min_f1: float | None = None,
    min_f1_delta: float | None = None,
) -> List[str]:
    """Return benchmark budget violations for CI/release gates."""
    summary = report.candidate if isinstance(report, (EvalComparison, EvalEngineComparison)) else report
    failures = []

    if max_fp is not None and summary.false_positive_count > max_fp:
        failures.append(
            f"false positives {summary.false_positive_count} > budget {max_fp}"
        )
    if max_fn is not None and summary.false_negative_count > max_fn:
        failures.append(
            f"false negatives {summary.false_negative_count} > budget {max_fn}"
        )
    if min_f1 is not None and summary.f1 < min_f1:
        failures.append(f"F1 {summary.f1:.3f} < minimum {min_f1:.3f}")
    if min_f1_delta is not None:
        if not isinstance(report, EvalComparison):
            failures.append("--min-f1-delta requires --compare-baseline")
        elif report.f1_delta < min_f1_delta:
            failures.append(
                f"F1 delta {report.f1_delta:+.3f} < minimum {min_f1_delta:+.3f}"
            )

    return failures


def evaluate_paths(paths: Iterable[Path]) -> EvalSummary:
    cases = [_evaluate_case(path) for path in sorted(paths)]
    return summarize_cases(cases)


def compare_paths(paths: Iterable[Path]) -> EvalComparison:
    baseline_cases = [
        _evaluate_case(path, strip_intensity_thresholds=True)
        for path in sorted(paths)
    ]
    candidate_cases = [_evaluate_case(path) for path in sorted(paths)]
    return EvalComparison(
        baseline=summarize_cases(baseline_cases),
        candidate=summarize_cases(candidate_cases),
    )


def compare_engines(
    paths: Iterable[Path],
    engines: Iterable[str],
) -> EvalEngineComparison:
    summaries = {}
    sorted_paths = sorted(paths)
    for engine in engines:
        engine_name = engine.strip()
        if not engine_name:
            continue
        if engine_name not in {"path-only", "patch-aware", "semantic-aware", "llm-enriched"}:
            raise ValueError(f"unknown eval engine: {engine_name}")
        summaries[engine_name] = summarize_cases([
            _evaluate_case(path, engine=engine_name)
            for path in sorted_paths
        ])
    return EvalEngineComparison(summaries=summaries)


def summarize_cases(cases: List[EvalCaseResult]) -> EvalSummary:
    metrics = _case_metrics(cases)

    return EvalSummary(
        total=metrics["total"],
        passed=metrics["passed"],
        failed=metrics["failed"],
        expected_rule_count=metrics["expected_rule_count"],
        actual_rule_count=metrics["actual_rule_count"],
        false_positive_count=metrics["false_positive_count"],
        false_negative_count=metrics["false_negative_count"],
        precision=metrics["precision"],
        recall=metrics["recall"],
        f1=metrics["f1"],
        runtime_seconds=metrics["runtime_seconds"],
        files_per_second=metrics["files_per_second"],
        cases=cases,
        category_metrics=_category_metrics(cases),
    )


def discover_fixture_paths(root: Path, *, recursive: bool = False) -> List[Path]:
    if root.is_file():
        return [root]
    pattern = "**/*.json" if recursive else "*.json"
    return sorted(root.glob(pattern))


def render_markdown(summary: EvalSummary) -> str:
    lines = [
        "# Drift Gate Eval",
        "",
        f"- Cases: {summary.total}",
        f"- Passed: {summary.passed}",
        f"- Failed: {summary.failed}",
        f"- Precision: {summary.precision:.3f}",
        f"- Recall: {summary.recall:.3f}",
        f"- F1: {summary.f1:.3f}",
        f"- False positives: {summary.false_positive_count}",
        f"- False negatives: {summary.false_negative_count}",
        f"- Runtime: {summary.runtime_seconds:.3f}s",
        f"- Files/sec: {summary.files_per_second:.1f}",
        "",
        "## Category Metrics",
        "",
        "| Category | Cases | Passed | Precision | Recall | F1 | FP | FN | Files/sec |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for category, metrics in summary.category_metrics.items():
        lines.append(
            f"| {category} | {metrics['total']} | {metrics['passed']} | "
            f"{metrics['precision']:.3f} | {metrics['recall']:.3f} | "
            f"{metrics['f1']:.3f} | {metrics['false_positive_count']} | "
            f"{metrics['false_negative_count']} | {metrics['files_per_second']:.1f} |"
        )
    lines += [
        "",
        "| Case | Result | Expected | Actual | FP | FN |",
        "|---|---:|---|---|---|---|",
    ]
    for case in summary.cases:
        result = "PASS" if case.passed else "FAIL"
        lines.append(
            "| "
            f"{case.name} | {result} | "
            f"{', '.join(case.expected_rules) or '-'} | "
            f"{', '.join(case.actual_rules) or '-'} | "
            f"{', '.join(case.false_positive_rules) or '-'} | "
            f"{', '.join(case.false_negative_rules) or '-'} |"
        )
    return "\n".join(lines)


def render_comparison_markdown(comparison: EvalComparison) -> str:
    baseline = comparison.baseline
    candidate = comparison.candidate
    lines = [
        "# Drift Gate Benchmark",
        "",
        "## Summary",
        "",
        "| Engine | Cases | Passed | Precision | Recall | F1 | FP | FN | Files/sec |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        _summary_row("Path-only baseline", baseline),
        _summary_row("Patch-aware candidate", candidate),
        "",
        "## Improvement",
        "",
        f"- False positive reduction: {comparison.false_positive_delta}",
        f"- False negative reduction: {comparison.false_negative_delta}",
        f"- F1 delta: {comparison.f1_delta:+.3f}",
        "",
        "## Case Details",
        "",
        "| Case | Category | Risk | Baseline | Candidate | Baseline FP | Candidate FP |",
        "|---|---|---|---:|---:|---|---|",
    ]
    baseline_by_name = {case.name: case for case in baseline.cases}
    for candidate_case in candidate.cases:
        baseline_case = baseline_by_name[candidate_case.name]
        lines.append(
            "| "
            f"{candidate_case.name} | "
            f"{candidate_case.category} | "
            f"{candidate_case.risk} | "
            f"{'PASS' if baseline_case.passed else 'FAIL'} | "
            f"{'PASS' if candidate_case.passed else 'FAIL'} | "
            f"{', '.join(baseline_case.false_positive_rules) or '-'} | "
            f"{', '.join(candidate_case.false_positive_rules) or '-'} |"
        )
    return "\n".join(lines)


def render_engine_comparison_markdown(comparison: EvalEngineComparison) -> str:
    lines = [
        "# Drift Gate Multi-Engine Benchmark",
        "",
        "| Engine | Cases | Passed | Precision | Recall | F1 | FP | FN | Files/sec |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, summary in comparison.summaries.items():
        lines.append(_summary_row(name, summary))
    lines += ["", "## Case Details", ""]
    first = next(iter(comparison.summaries.values()), None)
    if not first:
        return "\n".join(lines)
    engine_names = list(comparison.summaries)
    lines.append("| Case | " + " | ".join(engine_names) + " |")
    lines.append("|---|" + "---:|" * len(engine_names))
    cases_by_engine = {
        name: {case.name: case for case in summary.cases}
        for name, summary in comparison.summaries.items()
    }
    for case in first.cases:
        statuses = [
            "PASS" if cases_by_engine[name][case.name].passed else "FAIL"
            for name in engine_names
        ]
        lines.append(f"| {case.name} | " + " | ".join(statuses) + " |")
    return "\n".join(lines)


def render_comparison_html(comparison: EvalComparison) -> str:
    baseline = comparison.baseline
    candidate = comparison.candidate
    rows = []
    baseline_by_name = {case.name: case for case in baseline.cases}
    for candidate_case in candidate.cases:
        baseline_case = baseline_by_name[candidate_case.name]
        status = "improved" if not baseline_case.passed and candidate_case.passed else ""
        intensities = _case_intensities(candidate_case)
        rows.append(
            "<tr>"
            f"<td>{html.escape(candidate_case.name)}</td>"
            f"<td>{html.escape(candidate_case.description or '-')}</td>"
            f"<td>{html.escape(candidate_case.category)}</td>"
            f"<td>{html.escape(candidate_case.risk)}</td>"
            f"<td>{_badge(baseline_case.passed)}</td>"
            f"<td>{_badge(candidate_case.passed)}</td>"
            f"<td>{html.escape(', '.join(baseline_case.false_positive_rules) or '-')}</td>"
            f"<td>{html.escape(', '.join(candidate_case.false_positive_rules) or '-')}</td>"
            f"<td>{html.escape(', '.join(intensities) or '-')}</td>"
            f"<td>{status}</td>"
            "</tr>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Drift Gate Benchmark</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #172033;
      --muted: #5f6b7a;
      --line: #d8dee8;
      --panel: #ffffff;
      --wash: #f5f7fb;
      --soft: #edf1f7;
      --good: #0f8a5f;
      --bad: #b42318;
      --accent: #2457d6;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font: 14px/1.5 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--wash);
    }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 40px 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 32px; letter-spacing: 0; }}
    .lede {{ margin: 0 0 24px; color: var(--muted); }}
    .hero {{
      display: flex;
      justify-content: space-between;
      gap: 24px;
      align-items: flex-end;
      border-bottom: 1px solid var(--line);
      padding-bottom: 18px;
    }}
    .stamp {{ color: var(--muted); font-size: 12px; text-align: right; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
      margin: 24px 0;
    }}
    .metric {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
    .metric b {{ display: block; font-size: 26px; margin-top: 4px; }}
    .label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; }}
    th {{ background: var(--soft); font-size: 12px; text-transform: uppercase; color: var(--muted); }}
    tr:last-child td {{ border-bottom: 0; }}
    td {{ vertical-align: top; }}
    .pass, .fail {{
      display: inline-block;
      min-width: 52px;
      padding: 2px 8px;
      border-radius: 999px;
      color: white;
      font-size: 12px;
      text-align: center;
    }}
    .pass {{ background: var(--good); }}
    .fail {{ background: var(--bad); }}
    .comparison {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 12px;
      margin-bottom: 20px;
    }}
    h2 {{ margin: 28px 0 12px; font-size: 18px; }}
    .note {{
      background: #fff8e6;
      border: 1px solid #f3d38a;
      border-radius: 8px;
      padding: 12px 14px;
      margin: 0 0 18px;
      color: #4f3b00;
    }}
  </style>
</head>
<body>
<main>
  <header class="hero">
    <div>
      <h1>Drift Gate Benchmark</h1>
      <p class="lede">Path-only baseline vs patch-aware candidate on labeled PR fixtures.</p>
    </div>
    <div class="stamp">Deterministic fixture evaluation<br>Raw JSON reports supported</div>
  </header>

  <section class="metrics">
    <div class="metric"><span class="label">False Positive Reduction</span><b>{comparison.false_positive_delta}</b></div>
    <div class="metric"><span class="label">F1 Delta</span><b>{comparison.f1_delta:+.3f}</b></div>
    <div class="metric"><span class="label">Candidate Precision</span><b>{candidate.precision:.3f}</b></div>
    <div class="metric"><span class="label">Candidate Recall</span><b>{candidate.recall:.3f}</b></div>
  </section>

  <section class="comparison">
    {_engine_card("Path-only baseline", baseline)}
    {_engine_card("Patch-aware candidate", candidate)}
  </section>

  <p class="note">This report is generated from local fixtures, so every pass, false positive, and false negative can be reproduced without LLM calls.</p>

  <h2>Case Details</h2>
  <table>
    <thead>
      <tr>
        <th>Case</th><th>Description</th><th>Category</th><th>Risk</th><th>Baseline</th><th>Candidate</th><th>Baseline FP</th><th>Candidate FP</th><th>Intensity</th><th>Note</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
</main>
</body>
</html>"""


def render_engine_comparison_html(comparison: EvalEngineComparison) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(name)}</td>"
        f"<td>{summary.total}</td>"
        f"<td>{summary.passed}</td>"
        f"<td>{summary.precision:.3f}</td>"
        f"<td>{summary.recall:.3f}</td>"
        f"<td>{summary.f1:.3f}</td>"
        f"<td>{summary.false_positive_count}</td>"
        f"<td>{summary.false_negative_count}</td>"
        f"<td>{summary.files_per_second:.1f}</td>"
        "</tr>"
        for name, summary in comparison.summaries.items()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Drift Gate Multi-Engine Benchmark</title>
  <style>
    body {{ font: 14px/1.5 system-ui, sans-serif; margin: 32px; color: #172033; background: #f5f7fb; }}
    table {{ width: 100%; border-collapse: collapse; background: white; border: 1px solid #d8dee8; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #d8dee8; text-align: left; }}
    th {{ background: #edf1f7; }}
  </style>
</head>
<body>
  <h1>Drift Gate Multi-Engine Benchmark</h1>
  <p>Deterministic comparison across path-only, patch-aware, semantic-aware, and optional LLM-enriched modes.</p>
  <table>
    <thead><tr><th>Engine</th><th>Cases</th><th>Passed</th><th>Precision</th><th>Recall</th><th>F1</th><th>FP</th><th>FN</th><th>Files/sec</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</body>
</html>"""


def run_eval(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="drift-gate-eval",
        description="Run offline Drift Gate fixture evaluation",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="drift_gate/tests/fixtures",
        help="Fixture JSON file or directory",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Discover fixture JSON files recursively",
    )
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument(
        "--compare-baseline",
        action="store_true",
        help="Compare candidate against path-only baseline",
    )
    parser.add_argument(
        "--engines",
        help="Comma-separated engine comparison, e.g. path-only,patch-aware,semantic-aware,llm-enriched",
    )
    parser.add_argument("--out", help="Write report to file")
    parser.add_argument(
        "--html-out",
        help="Write a shareable HTML benchmark report (compare mode only)",
    )
    parser.add_argument(
        "--case-report-dir",
        help="Write raw per-case JSON reports to a directory",
    )
    parser.add_argument(
        "--max-fp",
        type=int,
        help="Fail if candidate false positives exceed this budget",
    )
    parser.add_argument(
        "--max-fn",
        type=int,
        help="Fail if candidate false negatives exceed this budget",
    )
    parser.add_argument(
        "--min-f1",
        type=float,
        help="Fail if candidate F1 is below this value",
    )
    parser.add_argument(
        "--min-f1-delta",
        type=float,
        help="Fail if compare-mode F1 delta is below this value",
    )
    args = parser.parse_args(argv)

    paths = discover_fixture_paths(Path(args.path), recursive=args.recursive)
    report = (
        compare_engines(paths, args.engines.split(","))
        if args.engines
        else compare_paths(paths) if args.compare_baseline else evaluate_paths(paths)
    )
    output = (
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
        if args.json_output
        else (
            render_engine_comparison_markdown(report)
            if isinstance(report, EvalEngineComparison)
            else render_comparison_markdown(report)
            if args.compare_baseline
            else render_markdown(report)
        )
    )
    if isinstance(report, EvalEngineComparison) and not args.json_output:
        output = render_engine_comparison_markdown(report)

    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
    if args.html_out:
        if not args.compare_baseline and not args.engines:
            parser.error("--html-out requires --compare-baseline or --engines")
        Path(args.html_out).write_text(
            render_engine_comparison_html(report)
            if isinstance(report, EvalEngineComparison)
            else render_comparison_html(report),
            encoding="utf-8",
        )
    if args.case_report_dir:
        write_case_reports(report, Path(args.case_report_dir))
    _write_stdout(output)
    gate_failures = benchmark_gate_failures(
        report,
        max_fp=args.max_fp,
        max_fn=args.max_fn,
        min_f1=args.min_f1,
        min_f1_delta=args.min_f1_delta,
    )
    for failure in gate_failures:
        print(f"[drift-gate-eval] benchmark gate failed: {failure}", file=sys.stderr)
    failed = report.candidate.failed if isinstance(report, (EvalComparison, EvalEngineComparison)) else report.failed
    sys.exit(1 if failed or gate_failures else 0)


def _evaluate_case(
    path: Path,
    *,
    strip_intensity_thresholds: bool = False,
    engine: str = "patch-aware",
) -> EvalCaseResult:
    data = json.loads(path.read_text(encoding="utf-8"))
    if strip_intensity_thresholds or engine == "path-only":
        data = _strip_intensity_thresholds(data)
    changed_files = [ChangedFile.from_dict(f) for f in data["changed_files"]]
    if engine in {"path-only", "patch-aware"}:
        changed_files = [
            ChangedFile(
                path=f.path,
                status=f.status,
                previous_path=f.previous_path,
                patch=f.patch,
            )
            for f in changed_files
        ]
    elif engine in {"semantic-aware", "llm-enriched"}:
        changed_files = enrich_semantic_signals(changed_files)
    drift_ignores = [
        DriftIgnoreDirective.from_dict(d)
        for d in data.get("drift_ignores", [])
    ]
    policy = Policy.from_dict(data["policy"])
    start = time.perf_counter()
    result = run(changed_files=changed_files, drift_ignores=drift_ignores, policy=policy)
    runtime_seconds = time.perf_counter() - start

    expected = data.get("expected", {})
    expected_rules = sorted(expected.get("violation_rule_ids", []))
    actual_rules = sorted(v.rule_id for v in result.violations)

    return EvalCaseResult(
        name=path.name,
        description=data.get("description", ""),
        category=data.get("category", _infer_category(data)),
        risk=data.get("risk", "medium"),
        expected_reason=data.get("expected_reason", ""),
        source=data.get("source", "fixture"),
        false_positive_target=data.get("false_positive_target", ""),
        expected_result=expected.get("result", ""),
        actual_result=result.result,
        expected_rules=expected_rules,
        actual_rules=actual_rules,
        actual_report=result.to_dict(),
        changed_file_count=len(changed_files),
        runtime_seconds=runtime_seconds,
        false_positive_rules=sorted(set(actual_rules) - set(expected_rules)),
        false_negative_rules=sorted(set(expected_rules) - set(actual_rules)),
    )


def write_case_reports(report: EvalSummary | EvalComparison | EvalEngineComparison, directory: Path) -> None:
    """Write raw JSON reports that can be inspected or attached as artifacts."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "summary.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if isinstance(report, EvalComparison):
        _write_summary_cases(report.baseline, directory / "baseline")
        _write_summary_cases(report.candidate, directory / "candidate")
    elif isinstance(report, EvalEngineComparison):
        for engine, summary in report.summaries.items():
            _write_summary_cases(summary, directory / engine)
    else:
        _write_summary_cases(report, directory / "cases")


def _write_summary_cases(summary: EvalSummary, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for case in summary.cases:
        filename = Path(case.name).with_suffix(".report.json").name
        (directory / filename).write_text(
            json.dumps(case.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _strip_intensity_thresholds(data: dict) -> dict:
    baseline = deepcopy(data)
    for rule in baseline.get("policy", {}).get("rules", []):
        rule.get("when", {}).pop("min_change_intensity", None)
    return baseline


def _case_metrics(cases: List[EvalCaseResult]) -> dict:
    total = len(cases)
    passed = sum(1 for case in cases if case.passed)
    false_positive_count = sum(len(c.false_positive_rules) for c in cases)
    false_negative_count = sum(len(c.false_negative_rules) for c in cases)
    expected_rule_count = sum(len(c.expected_rules) for c in cases)
    actual_rule_count = sum(len(c.actual_rules) for c in cases)
    true_positive_count = actual_rule_count - false_positive_count
    changed_file_count = sum(case.changed_file_count for case in cases)
    runtime_seconds = sum(case.runtime_seconds for case in cases)
    precision = _ratio(true_positive_count, actual_rule_count)
    recall = _ratio(true_positive_count, expected_rule_count)
    f1 = _f1(precision, recall)
    files_per_second = _ratio(changed_file_count, runtime_seconds)
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "expected_rule_count": expected_rule_count,
        "actual_rule_count": actual_rule_count,
        "false_positive_count": false_positive_count,
        "false_negative_count": false_negative_count,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "runtime_seconds": runtime_seconds,
        "files_per_second": files_per_second,
    }


def _category_metrics(cases: List[EvalCaseResult]) -> dict:
    categories = sorted(set(case.category for case in cases))
    return {
        category: _case_metrics([case for case in cases if case.category == category])
        for category in categories
    }


def _infer_category(data: dict) -> str:
    rule_ids = " ".join(
        rule.get("id", "")
        for rule in data.get("policy", {}).get("rules", [])
    )
    paths = " ".join(file.get("path", "") for file in data.get("changed_files", []))
    signal = f"{rule_ids} {paths}"
    if any(token in signal for token in ("api", "routes", "openapi")):
        return "api"
    if any(token in signal for token in ("db", "migration", "prisma")):
        return "db"
    if any(token in signal for token in ("env", "config")):
        return "env"
    if any(token in signal for token in ("auth", "security", "rbac")):
        return "auth"
    return "general"


def _summary_row(label: str, summary: EvalSummary) -> str:
    return (
        f"| {label} | {summary.total} | {summary.passed} | "
        f"{summary.precision:.3f} | {summary.recall:.3f} | "
        f"{summary.f1:.3f} | {summary.false_positive_count} | "
        f"{summary.false_negative_count} | {summary.files_per_second:.1f} |"
    )


def _engine_card(label: str, summary: EvalSummary) -> str:
    return (
        '<div class="metric">'
        f'<span class="label">{html.escape(label)}</span>'
        f"<b>{summary.passed}/{summary.total}</b>"
        f"<div>Precision {summary.precision:.3f} · Recall {summary.recall:.3f} · "
        f"F1 {summary.f1:.3f}</div>"
        f"<div>FP {summary.false_positive_count} · FN {summary.false_negative_count} · "
        f"{summary.files_per_second:.1f} files/sec</div>"
        "</div>"
    )


def _case_intensities(case: EvalCaseResult) -> List[str]:
    values = []
    for violation in case.actual_report.get("violations", []):
        if violation.get("change_intensity"):
            values.append(violation["change_intensity"])
    return sorted(set(values))


def _badge(passed: bool) -> str:
    if passed:
        return '<span class="pass">PASS</span>'
    return '<span class="fail">FAIL</span>'


def _write_stdout(output: str) -> None:
    data = (output + "\n").encode("utf-8")
    if hasattr(sys.stdout, "buffer"):
        sys.stdout.buffer.write(data)
    else:
        sys.stdout.write(output + "\n")


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return numerator / denominator


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


if __name__ == "__main__":
    run_eval()
