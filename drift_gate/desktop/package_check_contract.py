"""Pure assertions shared by the diagnostic app and its external verifier.

These prove fixture identity and independent scan events, not the authenticity of
an arbitrary JSON document or a hostile executable.
"""
from __future__ import annotations

import re


def validate_phase(case, result, seen_run_ids):
    execution = result.get("execution", {})
    run_id = execution.get("run_id", "")
    if (not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id)
            or run_id in seen_run_ids or execution.get("status") != "success"):
        raise RuntimeError("Missing or reused package scan execution ID")
    violations = [v for v in result.get("violations", []) if v.get("rule_id") == "offline-api-docs"]
    if result.get("result") != "warn" or len(violations) != 1:
        raise RuntimeError(f"Installed app did not reject {case} drift")
    if case in {"signature", "rename"}:
        files = violations[0].get("trigger_files", [])
        if len(files) != 1 or result.get("scan_metrics", {}).get("scanned_files") != 1:
            raise RuntimeError(f"Unexpected changed files for package {case} fixture")
        changed = files[0]
        patch = changed.get("patch", "")
        if case == "signature":
            # Consume the diff marker only within hunks, preserving code prefixes.
            in_hunk = False
            changes = []
            for line in patch.splitlines():
                if line.startswith("@@ "):
                    in_hunk = True
                elif in_hunk and line.startswith(("+", "-")):
                    changes.append(line)
            valid = (changed.get("path") == "src/api.py"
                     and changed.get("status") == "modified"
                     and not changed.get("previous_path")
                     and changes == ["+        *extra,", "+        **options,"])
        else:
            valid = (changed.get("path") == "docs/api.py"
                     and changed.get("previous_path") == "src/api.py"
                     and changed.get("status") == "renamed"
                     and patch.splitlines() == [
                         "diff --git a/src/api.py b/docs/api.py", "similarity index 100%",
                         "rename from src/api.py", "rename to docs/api.py"])
        if not valid:
            raise RuntimeError(f"Package {case} result does not match its fixture")
    return run_id


def validate_phases(result):
    checks = result.get("hardening_checks", [])
    if [item.get("case") for item in checks] != ["signature", "rename"]:
        raise RuntimeError("Missing, duplicate, or reordered package phases")
    seen = {validate_phase("grammar", result["scan"]["result"], set())}
    for item in checks:
        seen.add(validate_phase(item["case"], item["result"], seen))
