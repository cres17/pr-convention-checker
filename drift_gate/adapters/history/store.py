"""Local history store for Drift Gate results."""
import html
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from drift_gate.core.models.result import EvaluationResult


DEFAULT_HISTORY_PATH = ".drift-gate-history.jsonl"


def append_result(
    result: EvaluationResult,
    path: str | Path = DEFAULT_HISTORY_PATH,
    *,
    source: str = "local",
    pr_number: int | None = None,
    commit_sha: str = "",
    changed_file_count: int = 0,
    runtime_seconds: float = 0.0,
    release: str = "",
) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "pr_number": pr_number,
        "commit_sha": commit_sha,
        "result": result.result,
        "blocker": result.blocker_count,
        "major": result.major_count,
        "minor": result.minor_count,
        "nit": result.nit_count,
        "violation_count": len(result.violations),
        "rejected_ignore_count": len(result.rejected_ignores),
        "skipped_rule_count": len(result.skipped_rules),
        "rules": [violation.rule_id for violation in result.violations],
        "severities": [violation.severity for violation in result.violations],
        "ignored_rules": [rule.rule_id for rule in result.skipped_rules],
        "rejected_ignore_rules": [rule.rule_id for rule in result.rejected_ignores],
        "ignore_audit": [entry.to_dict() for entry in result.ignore_audit],
        "change_types": result.change_types,
        "changed_file_count": changed_file_count,
        "runtime_seconds": runtime_seconds,
        "release": release,
    }
    history_path = Path(path)
    if _is_sqlite_path(history_path):
        _append_sqlite(history_path, record)
        return
    with history_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_records(
    path: str | Path = DEFAULT_HISTORY_PATH,
    *,
    days: int = 30,
    rule_id: str = "",
) -> list[dict]:
    history_path = Path(path)
    if not history_path.exists():
        return []
    if _is_sqlite_path(history_path):
        records = _load_sqlite(history_path)
    else:
        records = []
        for line in history_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            records.append(json.loads(line))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    filtered = []
    for record in records:
        timestamp = datetime.fromisoformat(record["timestamp"])
        if timestamp >= cutoff:
            filtered.append(record)
    if rule_id:
        filtered = [
            record for record in filtered
            if rule_id in record.get("rules", [])
            or rule_id in record.get("ignored_rules", [])
            or rule_id in record.get("rejected_ignore_rules", [])
        ]
    return filtered


def _compute_trend_direction(trend_dict: dict) -> str:
    """Return 'improving', 'stable', or 'worsening' based on daily violation counts.

    Compares the average violations-per-run in the first half of the date range
    against the second half.  Requires at least 2 data points to detect a trend;
    returns 'stable' when there is insufficient data.

    Returns:
        'improving'  — second-half average is lower than first-half average
        'worsening'  — second-half average is higher than first-half average
        'stable'     — no significant change (< 5 % delta) or insufficient data
    """
    days = list(trend_dict.values())
    if len(days) < 2:
        return "stable"
    mid = len(days) // 2
    first_half = days[:mid]
    second_half = days[mid:]

    def avg_violations_per_run(bucket: list[dict]) -> float:
        total_runs = sum(d["runs"] for d in bucket)
        total_violations = sum(d["violations"] for d in bucket)
        if total_runs == 0:
            return 0.0
        return total_violations / total_runs

    first_avg = avg_violations_per_run(first_half)
    second_avg = avg_violations_per_run(second_half)

    if first_avg == 0 and second_avg == 0:
        return "stable"
    if first_avg == 0:
        return "worsening"
    delta_pct = (second_avg - first_avg) / first_avg
    if delta_pct < -0.05:
        return "improving"
    if delta_pct > 0.05:
        return "worsening"
    return "stable"


def _drift_reduction_rate(trend_dict: dict) -> float:
    """Return the percentage change in violations-per-run (second half vs first half).

    Negative values indicate improvement (fewer violations per run).
    Returns 0.0 when there is insufficient data.
    """
    days = list(trend_dict.values())
    if len(days) < 2:
        return 0.0
    mid = len(days) // 2
    first_half = days[:mid]
    second_half = days[mid:]

    def avg_vpr(bucket: list[dict]) -> float:
        total_runs = sum(d["runs"] for d in bucket)
        total_violations = sum(d["violations"] for d in bucket)
        return total_violations / total_runs if total_runs else 0.0

    first_avg = avg_vpr(first_half)
    second_avg = avg_vpr(second_half)
    if first_avg == 0:
        return 0.0
    return (second_avg - first_avg) / first_avg * 100.0


def summarize_records(records: list[dict]) -> dict:
    rule_counts: dict[str, int] = {}
    ignored_rule_counts: dict[str, int] = {}
    contract_area_counts: dict[str, int] = {}
    result_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    for record in records:
        result_counts[record.get("result", "unknown")] = (
            result_counts.get(record.get("result", "unknown"), 0) + 1
        )
        for rule_id in record.get("rules", []):
            rule_counts[rule_id] = rule_counts.get(rule_id, 0) + 1
        for rule_id in record.get("ignored_rules", []):
            ignored_rule_counts[rule_id] = ignored_rule_counts.get(rule_id, 0) + 1
        for severity in record.get("severities", []):
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
        for change_type in record.get("change_types", []):
            contract_area_counts[change_type] = contract_area_counts.get(change_type, 0) + 1
    return {
        "total": len(records),
        "result_counts": result_counts,
        "rule_counts": dict(sorted(rule_counts.items())),
        "ignored_rule_counts": dict(sorted(ignored_rule_counts.items())),
        "contract_area_counts": dict(sorted(contract_area_counts.items())),
        "severity_counts": dict(sorted(severity_counts.items())),
        "violation_count": sum(record.get("violation_count", 0) for record in records),
        "rejected_ignore_count": sum(
            record.get("rejected_ignore_count", 0) for record in records
        ),
        "skipped_rule_count": sum(
            record.get("skipped_rule_count", 0) for record in records
        ),
        "changed_file_count": sum(record.get("changed_file_count", 0) for record in records),
        "average_runtime_seconds": _average(
            [record.get("runtime_seconds", 0.0) for record in records]
        ),
        "average_fix_hours": _average_fix_hours(records),
        "trend": _daily_trend(records),
        "release_trend": _release_trend(records),
        "repeated_ignore_warnings": [
            rule_id for rule_id, count in ignored_rule_counts.items() if count >= 3
        ],
        "trend_direction": _compute_trend_direction(_daily_trend(records)),
        "drift_reduction_rate": _drift_reduction_rate(_daily_trend(records)),
    }


def ignored_rule_counts(records: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        for rule_id in record.get("ignored_rules", []):
            counts[rule_id] = counts.get(rule_id, 0) + 1
    return dict(sorted(counts.items()))


def _trend_arrow(direction: str) -> str:
    """Return a text indicator for a trend direction."""
    return {"improving": "down (improving)", "worsening": "up (worsening)", "stable": "stable"}.get(direction, direction)


def render_history_markdown(records: list[dict], *, days: int, rule_id: str = "") -> str:
    summary = summarize_records(records)
    direction = summary["trend_direction"]
    reduction = summary["drift_reduction_rate"]
    if direction == "improving":
        trend_line = f"- Drift trend: {_trend_arrow(direction)} ({abs(reduction):.0f}% fewer violations/run)"
    elif direction == "worsening":
        trend_line = f"- Drift trend: {_trend_arrow(direction)} ({abs(reduction):.0f}% more violations/run)"
    else:
        trend_line = f"- Drift trend: {_trend_arrow(direction)}"
    lines = [
        "# Drift Gate History",
        "",
        trend_line,
        f"- Window: last {days} day(s)",
        f"- Rule filter: `{rule_id}`" if rule_id else "- Rule filter: `all`",
        f"- Runs: {summary['total']}",
        f"- Violations: {summary['violation_count']}",
        f"- Rejected ignores: {summary['rejected_ignore_count']}",
        f"- Applied ignores: {summary['skipped_rule_count']}",
        f"- Changed files: {summary['changed_file_count']}",
        f"- Average runtime: {summary['average_runtime_seconds']:.3f}s",
        f"- Average fix time: {summary['average_fix_hours']:.2f}h",
        "",
        "## Rule Counts",
        "",
    ]
    if summary["rule_counts"]:
        lines.extend(
            f"- `{rule_id}`: {count}"
            for rule_id, count in summary["rule_counts"].items()
        )
    else:
        lines.append("- None")
    lines += ["", "## Most Ignored Rules", ""]
    if summary["ignored_rule_counts"]:
        lines.extend(
            f"- `{rule_id}`: {count}"
            for rule_id, count in summary["ignored_rule_counts"].items()
        )
    else:
        lines.append("- None")
    lines += ["", "## Contract Areas", ""]
    if summary["contract_area_counts"]:
        lines.extend(
            f"- `{area}`: {count}"
            for area, count in summary["contract_area_counts"].items()
        )
    else:
        lines.append("- None")
    if summary["repeated_ignore_warnings"]:
        lines += ["", "## Repeated Ignore Warnings", ""]
        lines.extend(f"- `{rule_id}` ignored repeatedly" for rule_id in summary["repeated_ignore_warnings"])
    if summary["release_trend"]:
        lines += ["", "## Release Drift Trend", ""]
        lines.extend(
            f"- `{release}`: {metrics['violations']} violation(s)"
            for release, metrics in summary["release_trend"].items()
        )
    return "\n".join(lines)


def render_history_html(records: list[dict], *, days: int, rule_id: str = "") -> str:
    summary = summarize_records(records)
    direction = summary["trend_direction"]
    reduction = summary["drift_reduction_rate"]
    if direction == "improving":
        trend_summary = (
            f"Drift trend over the last {days} day(s): "
            f"decreasing ({abs(reduction):.0f}% fewer violations/run)"
        )
    elif direction == "worsening":
        trend_summary = (
            f"Drift trend over the last {days} day(s): "
            f"increasing ({abs(reduction):.0f}% more violations/run)"
        )
    else:
        trend_summary = f"Drift trend over the last {days} day(s): stable (no significant change)"
    trend_rows = "".join(
        "<tr>"
        f"<td>{html.escape(day)}</td>"
        f"<td>{metrics['runs']}</td>"
        f"<td>{metrics['violations']}</td>"
        f"<td>{metrics['ignored']}</td>"
        "</tr>"
        for day, metrics in summary["trend"].items()
    )
    release_rows = "".join(
        "<tr>"
        f"<td>{html.escape(release)}</td>"
        f"<td>{metrics['runs']}</td>"
        f"<td>{metrics['violations']}</td>"
        "</tr>"
        for release, metrics in summary["release_trend"].items()
    )
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(record['timestamp'])}</td>"
        f"<td>{html.escape(record.get('result', '-'))}</td>"
        f"<td>{html.escape(str(record.get('pr_number') or '-'))}</td>"
        f"<td>{html.escape(record.get('commit_sha') or '-')}</td>"
        f"<td>{record.get('violation_count', 0)}</td>"
        f"<td>{record.get('changed_file_count', 0)}</td>"
        f"<td>{record.get('runtime_seconds', 0.0):.3f}s</td>"
        f"<td>{html.escape(', '.join(record.get('rules', [])) or '-')}</td>"
        "</tr>"
        for record in records
    )
    trend = summary["trend"]
    chart_labels = json.dumps(list(trend.keys()))
    chart_violations = json.dumps([m["violations"] for m in trend.values()])
    chart_runs = json.dumps([m["runs"] for m in trend.values()])
    chart_ignored = json.dumps([m["ignored"] for m in trend.values()])
    has_trend_data = "true" if trend else "false"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Drift Gate History</title>
  <style>
    body {{ font: 14px/1.5 system-ui, sans-serif; margin: 32px; color: #172033; background: #f8fafc; }}
    h1 {{ margin-bottom: 4px; }}
    .card {{ background: #fff; border: 1px solid #d8dee8; border-radius: 8px; padding: 24px; margin-bottom: 24px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-bottom: 1px solid #d8dee8; padding: 8px 10px; text-align: left; }}
    th {{ background: #f5f7fb; font-weight: 600; }}
    .chart-wrap {{ position: relative; height: 260px; }}
    .empty-chart {{ color: #888; padding: 60px 0; text-align: center; }}
  </style>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
</head>
<body>
  <h1>Drift Gate History</h1>
  <p><strong>{html.escape(trend_summary)}</strong></p>
  <p>Last {days} day(s) &mdash; rule: <code>{html.escape(rule_id or 'all')}</code> &mdash; {summary['total']} run(s), {summary['violation_count']} violation(s).</p>

  <div class="card">
    <h2 style="margin-top:0">Violations per Day</h2>
    <div class="chart-wrap">
      {"<canvas id='trendChart'></canvas>" if trend else "<p class='empty-chart'>No data in this window.</p>"}
    </div>
  </div>

  <div class="card">
    <h2 style="margin-top:0">Daily Trend Table</h2>
    <table>
      <thead><tr><th>Date</th><th>Runs</th><th>Violations</th><th>Ignored</th></tr></thead>
      <tbody>{trend_rows}</tbody>
    </table>
  </div>

  <div class="card">
    <h2 style="margin-top:0">Release Trend</h2>
    <table>
      <thead><tr><th>Release</th><th>Runs</th><th>Violations</th></tr></thead>
      <tbody>{release_rows if release_rows else "<tr><td colspan='3'>No release data.</td></tr>"}</tbody>
    </table>
  </div>

  <div class="card">
    <h2 style="margin-top:0">All Runs</h2>
    <table>
      <thead><tr><th>Timestamp</th><th>Result</th><th>PR</th><th>Commit</th><th>Violations</th><th>Files</th><th>Runtime</th><th>Rules</th></tr></thead>
      <tbody>{rows if rows else "<tr><td colspan='8'>No runs recorded.</td></tr>"}</tbody>
    </table>
  </div>

  <script>
  if ({has_trend_data}) {{
    const ctx = document.getElementById('trendChart').getContext('2d');
    new Chart(ctx, {{
      type: 'line',
      data: {{
        labels: {chart_labels},
        datasets: [
          {{
            label: 'Violations',
            data: {chart_violations},
            borderColor: '#e53e3e',
            backgroundColor: 'rgba(229,62,62,0.08)',
            tension: 0.3,
            fill: true,
            pointRadius: 4,
          }},
          {{
            label: 'Runs',
            data: {chart_runs},
            borderColor: '#3182ce',
            backgroundColor: 'rgba(49,130,206,0.06)',
            tension: 0.3,
            fill: false,
            pointRadius: 4,
          }},
          {{
            label: 'Ignored',
            data: {chart_ignored},
            borderColor: '#d69e2e',
            backgroundColor: 'rgba(214,158,46,0.06)',
            tension: 0.3,
            fill: false,
            pointRadius: 4,
            borderDash: [4, 3],
          }},
        ],
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{ legend: {{ position: 'top' }} }},
        scales: {{
          y: {{
            beginAtZero: true,
            ticks: {{ precision: 0 }},
          }},
        }},
      }},
    }});
  }}
  </script>
</body>
</html>"""


def _is_sqlite_path(path: Path) -> bool:
    return path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}


def _append_sqlite(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS drift_gate_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                record_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO drift_gate_history (timestamp, record_json) VALUES (?, ?)",
            (record["timestamp"], json.dumps(record, ensure_ascii=False)),
        )


def _load_sqlite(path: Path) -> list[dict]:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS drift_gate_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                record_json TEXT NOT NULL
            )
            """
        )
        rows = conn.execute(
            "SELECT record_json FROM drift_gate_history ORDER BY timestamp"
        ).fetchall()
    return [json.loads(row[0]) for row in rows]


def _daily_trend(records: list[dict]) -> dict:
    trend: dict[str, dict] = {}
    for record in records:
        day = record["timestamp"][:10]
        metrics = trend.setdefault(day, {"runs": 0, "violations": 0, "ignored": 0})
        metrics["runs"] += 1
        metrics["violations"] += record.get("violation_count", 0)
        metrics["ignored"] += record.get("skipped_rule_count", 0)
    return dict(sorted(trend.items()))


def _release_trend(records: list[dict]) -> dict:
    trend: dict[str, dict] = {}
    for record in records:
        release = record.get("release") or "unreleased"
        metrics = trend.setdefault(release, {"runs": 0, "violations": 0})
        metrics["runs"] += 1
        metrics["violations"] += record.get("violation_count", 0)
    return dict(sorted(trend.items()))


def _average_fix_hours(records: list[dict]) -> float:
    open_since: dict[str, datetime] = {}
    durations = []
    for record in sorted(records, key=lambda item: item["timestamp"]):
        timestamp = datetime.fromisoformat(record["timestamp"])
        rules = record.get("rules", [])
        if record.get("violation_count", 0):
            for rule_id in rules:
                open_since.setdefault(rule_id, timestamp)
        elif record.get("result") == "pass":
            for rule_id, started in list(open_since.items()):
                durations.append((timestamp - started).total_seconds() / 3600)
                del open_since[rule_id]
    return _average(durations)


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)
