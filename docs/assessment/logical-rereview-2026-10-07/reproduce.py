"""Replay small synthetic contracts; write a NEW result file, never overwrite."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from drift_gate.core.engine import run
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.policy.loader import load_policy_from_dict, PolicyLoadError


def reproduce(cases):
    results = []
    for case in cases:
        try:
            policy = load_policy_from_dict(case["policy"])
            files = []
            for data in case.get("files", []):
                file = ChangedFile.from_dict(data)
                file.before_source = data.get("before_source")
                file.after_source = data.get("after_source")
                files.append(file)
            result = run(files, policy=policy).to_dict()
            actual = {"gate": result["result"], "decision": result["rule_decisions"][0]["decision"],
                      "verification": result["verification"], "violations": len(result["violations"])}
        except PolicyLoadError as exc:
            result = {"error": str(exc)}
            actual = {"error": "policy-error"}
        results.append({"id": case["id"], "expected": case["expected"], "actual": actual,
                        "matched": actual == case["expected"], "result": result})
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("cases.json"))
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text())
    results = reproduce(cases)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump({"cases": results, "matched": sum(r["matched"] for r in results), "total": len(results)}, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    raise SystemExit(0 if all(r["matched"] for r in results) else 1)
