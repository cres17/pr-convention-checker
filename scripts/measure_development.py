"""Save an immutable development snapshot and optionally compare with a baseline.

Run with the project dependencies and pytest installed. Does not call an LLM or
GitHub, post comments, or change product code. Tree-sitter may fetch grammars
when its installed distribution requires them.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(paths):
    return {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


def command(args):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=300)


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def metric_rows(data):
    rows = {"pytest passed": data["pytest"]["passed"],
            "pytest failed/errors": data["pytest"]["failed"] + data["pytest"]["errors"],
            "parser smoke passed / 3": sum(case["passed"] for case in data["parser_smoke"]),
            "challenge passed / 8": sum(case["passed"] for case in data["challenge"]["cases"])}
    for name, result in data["benchmark"].items():
        for field in ("passed", "false_positive_count", "false_negative_count", "precision", "recall", "f1"):
            rows[f"{name} {field}"] = result[field]
    return rows


def compare(before, after):
    compatible = (
        before["manifests"]["fixtures"] == after["manifests"]["fixtures"]
        and before["manifests"]["challenge"] == after["manifests"]["challenge"]
        and before["manifests"]["harness"] == after["manifests"]["harness"]
    )
    env_equal = all(before[key] == after[key] for key in ("python", "platform", "dependencies"))
    lines = ["# Development comparison", "",
             f"Baseline: `{before['commit']}` ({before['measured_at_utc']})",
             f"Candidate: `{after['commit']}` ({after['measured_at_utc']})", "",
             f"Same fixtures, challenge suite and harness: **{compatible}**",
             f"Same Python, platform and dependency versions: **{env_equal}**", "",
             "Counts are limited to these synthetic cases; they are not production accuracy.",
             "Pytest counts can change when tests are added. Compare fixed-case results separately.", ""]
    if not compatible:
        return "\n".join(lines + ["Comparison withheld: remeasure both revisions with the same suite and harness.", ""])
    if not env_equal:
        lines += ["Environment differs: deltas are descriptive, not attributable solely to code changes.", ""]
    lines += ["| Metric | Before | After | Delta (after - before) |", "|---|---:|---:|---:|"]
    old = metric_rows(before)
    for name, value in metric_rows(after).items():
        lines.append(f"| {name} | {old[name]:.6g} | {value:.6g} | {value-old[name]:+.6g} |")
    lines += ["", "## Fixed challenge cases", "", "| Case | Before | After | Expected |", "|---|---|---|---|"]
    prior = {case["id"]: case for case in before["challenge"]["cases"]}
    for case in after["challenge"]["cases"]:
        lines.append(f"| {case['id']} | {prior[case['id']]['actual']} | {case['actual']} | {case['expected']} |")
    lines += ["", "Inspect raw reports and changed source hashes before claiming improvement.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="New directory; existing directories are never overwritten")
    parser.add_argument("--compare", type=Path, help="Baseline summary.json")
    args = parser.parse_args()
    baseline = json.loads(args.compare.read_text(encoding="utf-8")) if args.compare else None
    args.out.mkdir(parents=True, exist_ok=False)

    from drift_gate.adapters.ast.tree_sitter_support import parse_sexp
    from drift_gate.adapters.ast.analyzer import enrich_semantic_signals
    from drift_gate.adapters.eval.runner import compare_engines, discover_fixture_paths
    from drift_gate.adapters.github.client import parse_drift_ignores
    from drift_gate.core.engine import run
    from drift_gate.core.models.changed_file import ChangedFile
    from drift_gate.core.models.policy import Policy

    fixture_paths = discover_fixture_paths(ROOT / "drift_gate/tests/fixtures", recursive=True)
    suite_path = ROOT / "docs/assessment/challenge-v1.json"
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    source_paths = list((ROOT / "drift_gate").rglob("*.py"))
    snapshot = {
        "schema_version": 1, "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "commit": command(["git", "rev-parse", "HEAD"]).stdout.strip(),
        "git_status": command(["git", "status", "--short"]).stdout,
        "python": platform.python_version(), "platform": platform.platform(),
        "dependencies": {},
        "manifests": {"fixtures": digest(fixture_paths), "challenge": digest([suite_path]),
                      "harness": digest([Path(__file__).resolve()]),
                      "source_and_tests": digest(source_paths),
                      "configuration": digest([ROOT / "pyproject.toml", ROOT / "action.yml"])}
    }
    for name in ("pytest", "pyyaml", "tree-sitter", "tree-sitter-language-pack"):
        try:
            snapshot["dependencies"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            snapshot["dependencies"][name] = "not installed"
    frozen = command([sys.executable, "-m", "pip", "freeze"])
    # uv-created environments may omit pip; known dependency versions remain recorded.
    (args.out / "environment.txt").write_text(
        json.dumps({key: snapshot[key] for key in ("python", "platform", "dependencies")}, indent=2)
        + "\n\n" + (frozen.stdout if frozen.returncode == 0 else "pip freeze unavailable; see versions above\n"), encoding="utf-8")

    smoke = []
    for language, lines, expected in [
        ("python", ["def create_user():", "    pass"], "function_definition"),
        ("typescript", ["export function createUser(id: string) {}"], "function_declaration"),
        ("go", ["package main", "func CreateUser(id string) {}"], "function_declaration"),
    ]:
        try:
            tree = parse_sexp(language, lines)
            smoke.append({"language": language, "passed": expected in tree, "error": ""})
        except Exception as exc:
            smoke.append({"language": language, "passed": False, "error": f"{type(exc).__name__}: {exc}"})
    snapshot["parser_smoke"] = smoke

    benchmark = compare_engines(fixture_paths, ["path-only", "patch-aware", "semantic-aware"])
    write_json(args.out / "benchmark-full.json", benchmark.to_dict())
    snapshot["benchmark"] = {
        name: {key: value for key, value in summary.to_dict().items()
               if key not in ("cases", "category_metrics", "runtime_seconds", "files_per_second")}
        for name, summary in benchmark.summaries.items()
    }

    challenge_results = []
    for case in suite["cases"]:
        files = enrich_semantic_signals([ChangedFile.from_dict(item) for item in case["changed_files"]])
        result = run(files, policy=Policy.from_dict(suite["policies"][case["policy"]]),
                     drift_ignores=parse_drift_ignores(case.get("pr_body", "")))
        challenge_results.append({"id": case["id"], "expected": case["expected"],
                                  "actual": result.result, "passed": result.result == case["expected"],
                                  "reason": case["reason"], "report": result.to_dict()})
    snapshot["challenge"] = {"suite": suite["version"], "cases": challenge_results}

    test_run = command([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        f"--junitxml={args.out.resolve() / 'pytest.xml'}"])
    (args.out / "pytest.txt").write_text(test_run.stdout + test_run.stderr, encoding="utf-8")
    counts = {"total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0, "exit_code": test_run.returncode}
    xml_path = args.out / "pytest.xml"
    if xml_path.exists():
        for case in ET.parse(xml_path).iter("testcase"):
            counts["total"] += 1
            outcome = ("failed" if case.find("failure") is not None else "errors" if case.find("error") is not None
                       else "skipped" if case.find("skipped") is not None else "passed")
            counts[outcome] += 1
    snapshot["pytest"] = counts
    docs = command([sys.executable, "main.py", "docs-check", "README.md", "--json"])
    (args.out / "docs-check.json").write_text(docs.stdout, encoding="utf-8")
    snapshot["docs_check_exit_code"] = docs.returncode
    write_json(args.out / "summary.json", snapshot)
    if baseline:
        (args.out / "comparison.md").write_text(compare(baseline, snapshot), encoding="utf-8")
    print(json.dumps({"out": str(args.out), "metrics": metric_rows(snapshot), "pytest_exit_code": test_run.returncode}, ensure_ascii=False, indent=2))
    # This is a recording tool: observed product failures are data, not a failure
    # to save the snapshot. Inspect pytest.exit_code and case results in summary.


if __name__ == "__main__":
    main()
