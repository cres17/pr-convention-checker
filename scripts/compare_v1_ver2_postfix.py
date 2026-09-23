"""Re-run the frozen 12 Git changes against the v1 stub and the current ver2 code.

The original comparison and its source-locking harness remain untouched.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess
import tempfile

from compare_v1_ver2 import (FAKE_CURL, RESPONSES, ROOT, SUITE, V1_COMMIT,
                            V2_COMMIT, digest, git_fixture, must,
                            run_v1, run_v2, tally)

FROZEN_RESULT = ROOT / "docs/assessment/v1-ver2-controlled-2026-09-23/run-4/result.json"


def source_hashes():
    product = [p for p in sorted((ROOT / "drift_gate").rglob("*.py"))
               if "tests" not in p.relative_to(ROOT).parts]
    product.append(ROOT / "main.py")
    return {p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in product}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output directory already exists")
    if must(["git", "rev-parse", "v1^{}"], ROOT) != V1_COMMIT:
        parser.error("v1 tag changed")
    suite_bytes = SUITE.read_bytes()
    frozen = json.loads(FROZEN_RESULT.read_text(encoding="utf-8"))
    if digest(suite_bytes) != frozen["cases_sha256"]:
        parser.error("the frozen 12-case suite changed")
    suite = json.loads(suite_bytes)
    baseline = {row["id"]: row for row in frozen["cases"]}
    v1_bytes = subprocess.check_output(["git", "show", "v1:github-action/entrypoint.sh"], cwd=ROOT)
    if digest(v1_bytes) != frozen["v1_entrypoint_sha256"]:
        parser.error("v1 entrypoint changed")
    args.out.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="drift-gate-postfix-") as temp:
        temp_root = Path(temp)
        mock = temp_root / "mock"
        mock.mkdir()
        script = mock / "v1-entrypoint.sh"
        script.write_bytes(v1_bytes)
        curl = mock / "curl"
        curl.write_text(FAKE_CURL, encoding="utf-8")
        curl.chmod(0o755)
        for name, body in RESPONSES.items():
            (mock / (name + ".txt")).write_text(body, encoding="utf-8")
        rows = []
        for case in suite["cases"]:
            repo = temp_root / case["id"]
            base, head, diff = git_fixture(repo, suite, case)
            old = baseline[case["id"]]
            if digest(diff.encode()) != old["git_diff_sha256"]:
                raise RuntimeError(f"Git diff changed: {case['id']}")
            v1 = {name: run_v1(repo, script, mock, base, head, case["id"], name)
                  for name in RESPONSES}
            for name in RESPONSES:
                if (v1[name]["result"], v1[name]["request_emitted"]) != (
                    old["v1"][name]["result"], old["v1"][name]["request_emitted"]
                ):
                    raise RuntimeError(f"v1 stub behavior changed: {case['id']}/{name}")
            current = run_v2(repo, base)
            repeat = run_v2(repo, base)
            if current != repeat:
                raise RuntimeError(f"non-deterministic ver2 result: {case['id']}")
            rows.append({
                "id": case["id"], "scope": case["scope"], "expected": case["expected"],
                "reason": case["reason"], "git_diff_sha256": old["git_diff_sha256"],
                "v1_clear": v1["clear"], "v1_blocker": v1["blocker"],
                "ver2_before": old["v2"], "ver2_after": current,
                "v2": current, "ver2_repeat_same": current == repeat,
            })
            print(case["id"], "before", old["v2"]["result"], "after", current["result"])
    result = {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "v1_commit": V1_COMMIT, "ver2_baseline_commit": V2_COMMIT,
        "ver2_current_commit": must(["git", "rev-parse", "HEAD"], ROOT),
        "suite_sha256": digest(suite_bytes), "frozen_result_sha256": digest(FROZEN_RESULT.read_bytes()),
        "harness_sha256": digest(Path(__file__).read_bytes()),
        "shared_harness_sha256": digest((ROOT / "scripts/compare_v1_ver2.py").read_bytes()),
        "product_sha256": source_hashes(),
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "git": must(["git", "--version"], ROOT)},
        "counts_before": frozen["counts"],
        "counts_after": {scope: tally(rows, scope) for scope in ("support", "boundary")},
        "v1_request_count": sum(row["v1_clear"]["request_emitted"] for row in rows),
        "v1_response_sensitive_count": sum(row["v1_clear"]["result"] != row["v1_blocker"]["result"]
                                           for row in rows),
        "ver2_repeat_same_count": sum(row["ver2_repeat_same"] for row in rows),
        "cases": rows,
    }
    (args.out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                           encoding="utf-8")
    print(json.dumps({"counts_after": result["counts_after"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
