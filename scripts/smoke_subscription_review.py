"""Opt-in live subscription smoke check; sends synthetic data and uses plan quota."""
import argparse
import json
from pathlib import Path
import subprocess
import time

from drift_gate.core.engine import run
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.policy.loader import load_policy_from_text
from drift_gate.desktop.service import DesktopScan
from drift_gate.desktop.subscription_review import build_review_prompt, find_cli, review_with_subscription


POLICY = """rules:
  - id: api-doc-sync
    when:
      any_changed: [src/routes/**]
    require:
      groups:
        - name: API docs
          any_changed: [docs/api.md]
          content: api-routes
    severity: blocker
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["codex", "claude"], required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output already exists")
    files = (
        ChangedFile("src/routes/users.py", "modified", patch="@@ -1 +1 @@\n-@app.get('/users')\n+@app.get('/members')\n"),
        ChangedFile("docs/api.md", "modified", patch="@@ -1 +1 @@\n-GET /users\n+GET /customers\n"),
    )
    result = run(list(files), policy=load_policy_from_text(POLICY))
    assert result.result == "fail", "Synthetic baseline must detect the mismatched route"
    scan = DesktopScan(Path("/synthetic"), "HEAD", len(files), result, files, POLICY)
    before = result.to_dict()
    version = subprocess.run([find_cli(args.provider), "--version"], capture_output=True,
                             text=True, encoding="utf-8", check=True).stdout.strip()
    started = time.monotonic()
    answer = review_with_subscription(build_review_prompt(scan), args.provider)
    report = {"synthetic": True, "provider": args.provider, "cli_version": version,
              "case": "code GET /members versus docs GET /customers", "expected_llm_verdict": "fail",
              "policy": POLICY, "files": [f.to_dict() for f in files],
              "rule_gate_before": before["result"], "rule_gate_after": result.result,
              "gate_unchanged": before == result.to_dict(),
              "elapsed_seconds": round(time.monotonic() - started, 2), "review": answer.to_dict()}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"provider": args.provider, "verdict": answer.verdict,
                      "gate_unchanged": report["gate_unchanged"], "output": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
