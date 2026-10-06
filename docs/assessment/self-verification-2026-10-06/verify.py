"""Reproduce current-product checks in an isolated, committed checkout.

Run with the project's desktop/dev Python environment. No production edits,
external AI calls, or deletion of user drafts. Outputs must not already exist.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[3]
BASE = "729a3cde70c3457b633798bb50273d815d4d2c12"
HEAD = "01e28e1620941a539d3e9c14972201b30adafd3b"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    runs = []
    with tempfile.TemporaryDirectory(prefix="driftgate-self-verification-") as temporary:
        checkout = Path(temporary) / "checkout"
        subprocess.run(["git", "clone", "--shared", "--no-checkout", str(ROOT), str(checkout)], check=True, capture_output=True)
        subprocess.run(["git", "checkout", "--detach", HEAD], cwd=checkout, check=True, capture_output=True)
        env = {**os.environ, "PYTHONPATH": str(checkout), "ANTHROPIC_API_KEY": ""}

        def record(name, arguments):
            started = datetime.now(timezone.utc).isoformat()
            result = subprocess.run([sys.executable, *arguments], cwd=checkout, env=env,
                                    capture_output=True, timeout=180)
            (out / f"{name}.stdout").write_bytes(result.stdout)
            (out / f"{name}.stderr").write_bytes(result.stderr)
            runs.append({"name": name, "arguments": arguments, "exit_code": result.returncode,
                         "started_at": started})

        # First: use the unmodified product against its actual committed changes.
        record("gate", ["-m", "drift_gate", "check", "--base", BASE, "--json",
                        "--anthropic-api-key", "", "--out-html", str(out / "gate.html")])
        record("review", ["-m", "drift_gate", "review", "--base", BASE, "--format", "json"])
        record("docs-check", ["-m", "drift_gate", "docs-check", "README.md", "--json", "--fail-on-warn"])
        record("generalization", ["scripts/audit_generalization.py", "--source-root", str(checkout),
                                  "--revision", HEAD, "--out", str(out / "generalization.json")])
        (out / "changed-files.txt").write_bytes(subprocess.check_output(
            ["git", "diff", "--name-only", BASE, HEAD], cwd=checkout))
        (out / "policy.yml").write_bytes((checkout / ".drift-gate.yml").read_bytes())
    manifest = {"base": BASE, "head": HEAD, "scope": "committed changes, isolated checkout",
                "python": sys.version, "runs": runs,
                "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
