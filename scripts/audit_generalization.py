"""Record a frozen, post-development adversarial audit; failures are findings."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def counts(cases):
    # Positive means a change that should be blocked, not a passing test.
    return {
        "total": len(cases), "matched": sum(c["matched"] for c in cases),
        "tp": sum(c["expected"] == "fail" and c["actual"] == "fail" for c in cases),
        "tn": sum(c["expected"] == "pass" and c["actual"] == "pass" for c in cases),
        "fp": sum(c["expected"] == "pass" and c["actual"] == "fail" for c in cases),
        "fn": sum(c["expected"] == "fail" and c["actual"] == "pass" for c in cases),
        "errors": sum(c["actual"] not in ("pass", "fail") for c in cases),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output already exists; snapshots are never overwritten")
    source = args.source_root.resolve()
    sys.path.insert(0, str(source))
    from drift_gate.adapters.ast.analyzer import enrich_semantic_signals
    from drift_gate.core.engine import run
    from drift_gate.core.models.changed_file import ChangedFile
    from drift_gate.core.models.policy import Policy

    suite_path = ROOT / "docs/assessment/generalization-audit-v1.json"
    suite = json.loads(suite_path.read_text())
    rows = []
    for case in suite["cases"]:
        row = {key: case[key] for key in ("id", "scope", "expected", "reason")}
        try:
            files = enrich_semantic_signals([
                ChangedFile.from_dict(item) for item in case["changed_files"]
            ])
            result = run(files, policy=Policy.from_dict(suite["policies"][case["policy"]]))
            row.update(actual=result.result, report=result.to_dict())
        except Exception as exc:
            row.update(actual="error", error=f"{type(exc).__name__}: {exc}")
        row["matched"] = row["expected"] == row["actual"]
        rows.append(row)
    result = {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "revision": args.revision, "protocol": suite["protocol"],
        "python": platform.python_version(), "platform": platform.platform(),
        "dependencies": {name: importlib.metadata.version(name) for name in (
            "pyyaml", "tree-sitter", "tree-sitter-language-pack")},
        "suite_sha256": sha(suite_path), "harness_sha256": sha(Path(__file__)),
        "product_sha256": {
            str(path.relative_to(source)): sha(path)
            for path in sorted((source / "drift_gate").rglob("*.py"))
            if "tests" not in path.relative_to(source).parts
        },
        "counts": {scope: counts([c for c in rows if c["scope"] == scope])
                   for scope in ("supported", "boundary")},
        "cases": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"out": str(args.out), "counts": result["counts"],
                      "mismatches": [r["id"] for r in rows if not r["matched"]]}, indent=2))


if __name__ == "__main__":
    main()
