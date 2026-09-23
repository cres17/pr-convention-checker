"""Run frozen synthetic Git changes through v1 Action and ver2 CLI, offline."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "docs/assessment/v1-ver2-controlled-2026-09-23/cases.json"
V1_COMMIT = "13a5ded9ca03f67cf07d134421d5a1e1cd82b19e"
V2_COMMIT = "b9c2bd4b2afaca0fcf932f9e3fc1f1428e038cbd"
FAKE_CURL = '''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
if "https://api.anthropic.com/v1/messages" not in args:
    sys.exit("unexpected network destination")
if "-d" not in args:
    sys.exit("missing request body")
request = json.loads(args[args.index("-d") + 1])
pathlib.Path(os.environ["CAPTURED_REQUEST"]).write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
body = pathlib.Path(os.environ["STUB_RESPONSE"]).read_text(encoding="utf-8")
sys.stdout.write(json.dumps({"content": [{"type": "text", "text": body}]}, ensure_ascii=False))
'''
RESPONSES = {"clear": "## Check result\nNo convention issues.\n", "blocker": "## Check result\n[BLOCKER] Documentation missing.\n"}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def command(args, cwd, *, env=None, timeout=40):
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def must(args, cwd):
    p = command(args, cwd)
    if p.returncode:
        raise RuntimeError(f"{args[0]} failed: {p.stderr[-1000:]}")
    return p.stdout.strip()


def write_files(repo: Path, files: dict):
    for name, content in files.items():
        target = repo / name
        if content is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")


def git_fixture(repo: Path, suite: dict, case: dict):
    repo.mkdir()
    must(["git", "init", "-q"], repo)
    must(["git", "config", "user.name", "Controlled Test"], repo)
    must(["git", "config", "user.email", "controlled@example.invalid"], repo)
    write_files(repo, suite["baseline_files"])
    must(["git", "add", "-A"], repo)
    must(["git", "commit", "-qm", "baseline"], repo)
    base = must(["git", "rev-parse", "HEAD"], repo)
    write_files(repo, case["head_files"])
    must(["git", "add", "-A"], repo)
    must(["git", "commit", "-qm", case["id"]], repo)
    head = must(["git", "rev-parse", "HEAD"], repo)
    diff = must(["git", "diff", base + "..." + head], repo)
    return base, head, diff


def run_v1(repo: Path, script: Path, mock_dir: Path, base: str, head: str, case_id: str, response: str):
    output = mock_dir / f"{case_id}-{response}.outputs"
    request = mock_dir / f"{case_id}-{response}.request.json"
    report_dir = mock_dir / f"{case_id}-{response}-report"
    report_dir.mkdir()
    env = os.environ.copy()
    env.update(PATH=str(mock_dir) + os.pathsep + env.get("PATH", ""),
               ANTHROPIC_API_KEY="synthetic-not-a-secret", BASE_SHA=base, HEAD_SHA=head,
               CONVENTION_FILES="CLAUDE.md", GITHUB_OUTPUT=str(output), RUNNER_TEMP=str(report_dir),
               PR_NUMBER="", REPO="", GITHUB_TOKEN="", STUB_RESPONSE=str(mock_dir / (response + ".txt")),
               CAPTURED_REQUEST=str(request))
    proc = command(["bash", str(script)], repo, env=env)
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines() if "=" in line) if output.exists() else {}
    request_body = json.loads(request.read_text()) if request.exists() else None
    prompt = request_body["messages"][0]["content"] if request_body else ""
    return {"exit_code": proc.returncode, "result": outputs.get("result", "error"),
            "blocker_count": outputs.get("blocker_count"), "request_emitted": bool(request_body),
            "prompt_sha256": digest(prompt.encode()) if prompt else None,
            "prompt_has_rule": "When a public route changes" in prompt,
            "prompt_has_git_diff": "diff --git" in prompt,
            "prompt_has_env_example_change": "diff --git a/.env.example" in prompt,
            "prompt_has_route_change": "diff --git a/src/routes/users.py" in prompt,
            "stderr_tail": proc.stderr[-500:] if proc.returncode else ""}


def run_v2(repo: Path, base: str):
    proc = command([sys.executable, str(ROOT / "main.py"), "check", "--base", base, "--json"], repo)
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"exit_code": proc.returncode, "result": "error", "stderr_tail": proc.stderr[-500:],
                "stdout_tail": proc.stdout[-500:]}
    return {"exit_code": proc.returncode, "result": result.get("result", "error"),
            "violation_rule_ids": [v.get("rule_id") for v in result.get("violations", [])],
            "skip_reason": result.get("skip_reason"),
            "analysis_methods": {x["path"]: x["method"] for x in result.get("scan_metrics", {}).get("analysis_notes", [])}}


def tally(rows, scope):
    subset = [r for r in rows if r["scope"] == scope]
    counts = {"total": len(subset), "matched": 0, "tp": 0, "tn": 0, "fp": 0, "fn": 0, "error_or_skip": 0}
    for row in subset:
        actual, expected = row["v2"]["result"], row["expected"]
        if actual not in ("pass", "fail"):
            counts["error_or_skip"] += 1
        elif actual == expected:
            counts["matched"] += 1
            counts["tp" if expected == "fail" else "tn"] += 1
        else:
            counts["fp" if expected == "pass" else "fn"] += 1
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output directory already exists")
    if command(["git", "merge-base", "--is-ancestor", V2_COMMIT, "HEAD"], ROOT).returncode:
        parser.error("the frozen ver2 commit is not in this checkout")
    if must(["git", "rev-parse", "v1^{}"], ROOT) != V1_COMMIT:
        parser.error("v1 tag changed")
    product_files = [p for p in sorted((ROOT / "drift_gate").rglob("*.py"))
                     if "tests" not in p.relative_to(ROOT).parts]
    product_files.append(ROOT / "main.py")
    for path in product_files:
        relative = path.relative_to(ROOT).as_posix()
        baseline = subprocess.check_output(["git", "show", f"{V2_COMMIT}:{relative}"], cwd=ROOT)
        if path.read_bytes() != baseline:
            parser.error(f"ver2 product source changed since the frozen commit: {relative}")
    suite_bytes = SUITE.read_bytes()
    suite = json.loads(suite_bytes)
    v1_bytes = subprocess.check_output(["git", "show", "v1:github-action/entrypoint.sh"], cwd=ROOT)
    args.out.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="drift-gate-v1-v2-") as temp:
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
            v1 = {name: run_v1(repo, script, mock, base, head, case["id"], name) for name in RESPONSES}
            v2a = run_v2(repo, base)
            v2b = run_v2(repo, base)
            rows.append({"id": case["id"], "scope": case["scope"], "expected": case["expected"],
                         "reason": case["reason"], "git_diff_sha256": digest(diff.encode()),
                         "v1": v1, "v2": v2a, "v2_repeat_same": v2a == v2b})
            print(case["id"], "v1", v1["clear"]["result"], v1["blocker"]["result"], "v2", v2a["result"])
    result = {"measured_at_utc": datetime.now(timezone.utc).isoformat(),
              "v1_commit": V1_COMMIT, "v2_commit": V2_COMMIT,
              "protocol_sha256": digest((SUITE.parent / "protocol.md").read_bytes()),
              "cases_sha256": digest(suite_bytes), "harness_sha256": digest(Path(__file__).read_bytes()),
              "v1_entrypoint_sha256": digest(v1_bytes),
              "v2_product_sha256": {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in product_files},
              "environment": {"python": platform.python_version(), "platform": platform.platform(),
                              "git": must(["git", "--version"], ROOT), "jq": must(["jq", "--version"], ROOT)},
              "counts": {scope: tally(rows, scope) for scope in ("support", "boundary")},
              "v1_request_count": sum(x["v1"]["clear"]["request_emitted"] for x in rows),
              "v1_response_sensitive_count": sum(x["v1"]["clear"]["result"] != x["v1"]["blocker"]["result"] for x in rows),
              "v2_repeat_same_count": sum(x["v2_repeat_same"] for x in rows),
              "cases": rows}
    (args.out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"counts": result["counts"], "v1_request_count": result["v1_request_count"],
                      "v1_response_sensitive_count": result["v1_response_sensitive_count"],
                      "v2_repeat_same_count": result["v2_repeat_same_count"]}, indent=2))


if __name__ == "__main__":
    main()
