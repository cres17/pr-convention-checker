"""Run the same environment-content cases against an explicit product tree."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys

HARNESS_ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--revision", required=True, help="Commit plus worktree change description")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("refusing to overwrite an existing result")
    sys.path.insert(0, str(args.source_root.resolve()))
    from drift_gate.core.models.policy import Policy
    from drift_gate.core.models.changed_file import ChangedFile
    from drift_gate.core.engine import run
    suite_path = HARNESS_ROOT / "docs/assessment/env-contract-v1.json"
    suite = json.loads(suite_path.read_text())
    rows = []
    for case in suite["cases"]:
        result = run([ChangedFile.from_dict(f) for f in case["changed_files"]], policy=Policy.from_dict(suite["policy"]))
        rows.append({"id": case["id"], "expected": case["expected"], "actual": result.result,
                     "passed": result.result == case["expected"], "report": result.to_dict()})
    data = {"revision": args.revision, "python": platform.python_version(), "suite": suite["version"],
            "fixture_sha256": hashlib.sha256(suite_path.read_bytes()).hexdigest(),
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "source_hashes": {str(p.relative_to(args.source_root)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sorted((args.source_root / "drift_gate").rglob("*.py"))},
            "passed": sum(row["passed"] for row in rows), "total": len(rows), "cases": rows}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(f"{data['passed']}/{data['total']} cases matched expectations; saved {args.out}")


if __name__ == "__main__":
    main()
