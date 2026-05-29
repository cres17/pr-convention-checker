"""Tiny stdio MCP server wrapper for Drift Gate helpers.

This intentionally implements the small JSON-RPC surface needed by local AI
tools: ``initialize``, ``tools/list``, and ``tools/call``. It also accepts the
legacy ``{"tool": "...", "args": {...}}`` JSON-line shape used by tests.
"""
import json
import os
import sys
from pathlib import Path

from drift_gate.adapters.mcp import tools


TOOL_MAP = {
    "drift_gate_check_local": tools.drift_gate_check_local,
    "drift_gate_check_pr": tools.drift_gate_check_pr,
    "drift_gate_get_evidence": tools.drift_gate_get_evidence,
    "drift_gate_list_rules": tools.drift_gate_list_rules,
    "drift_gate_explain_rule": tools.drift_gate_explain_rule,
    "drift_gate_history": tools.drift_gate_history,
    "drift_gate_suggest_policy": tools.drift_gate_suggest_policy,
    "drift_gate_prepare_fix_plan": tools.drift_gate_prepare_fix_plan,
}


TOOL_DESCRIPTIONS = {
    "drift_gate_check_local": "Evaluate the current repository diff against .drift-gate.yml.",
    "drift_gate_check_pr": "Evaluate a GitHub pull request against .drift-gate.yml.",
    "drift_gate_get_evidence": "Fetch bounded diff evidence for one Drift Gate rule.",
    "drift_gate_list_rules": "List configured Drift Gate policy rules.",
    "drift_gate_explain_rule": "Explain one configured Drift Gate policy rule.",
    "drift_gate_history": "Summarize local Drift Gate history records.",
    "drift_gate_suggest_policy": "Suggest policy presets for a repository.",
    "drift_gate_prepare_fix_plan": "Return missing docs/contracts to update for the current diff.",
}


def handle_request(request: dict) -> dict:
    if "method" in request:
        return _handle_jsonrpc(request)

    tool_name = request.get("tool", "")
    args = request.get("args", {})
    if tool_name not in TOOL_MAP:
        return {"ok": False, "error": f"unknown tool: {tool_name}"}
    try:
        return {"ok": True, "result": TOOL_MAP[tool_name](**args)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _handle_jsonrpc(request: dict) -> dict:
    request_id = request.get("id")
    method = request.get("method", "")
    params = request.get("params") or {}

    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "drift-gate", "version": "1.0.0"},
            }
        elif method == "tools/list":
            result = {"tools": [_tool_schema(name) for name in sorted(TOOL_MAP)]}
        elif method == "tools/call":
            name = params.get("name", "")
            args = params.get("arguments") or {}
            if name not in TOOL_MAP:
                raise KeyError(f"unknown tool: {name}")
            tool_result = TOOL_MAP[name](**args)
            result = {
                "content": [{
                    "type": "text",
                    "text": json.dumps(tool_result, ensure_ascii=False, indent=2),
                }]
            }
        elif method.startswith("notifications/"):
            return {}
        else:
            return _jsonrpc_error(request_id, -32601, f"method not found: {method}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception as exc:
        return _jsonrpc_error(request_id, -32000, str(exc))


def _jsonrpc_error(request_id, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _tool_schema(name: str) -> dict:
    return {
        "name": name,
        "description": TOOL_DESCRIPTIONS.get(name, name),
        "inputSchema": {
            "type": "object",
            "additionalProperties": True,
            "properties": {},
        },
    }


def main(argv=None) -> None:
    repo = _parse_repo_arg(sys.argv[1:] if argv is None else argv)
    if repo:
        os.chdir(repo)
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            response = handle_request(request)
        except json.JSONDecodeError as exc:
            response = {"ok": False, "error": f"invalid json: {exc}"}
        if response:
            print(json.dumps(response, ensure_ascii=False), flush=True)


def _parse_repo_arg(argv) -> str:
    args = list(argv)
    if not args:
        return ""
    if args[0] in ("-h", "--help"):
        print("usage: drift-gate serve [--repo PATH]", file=sys.stderr)
        sys.exit(0)
    if args[0] == "--repo" and len(args) >= 2:
        repo = Path(args[1]).expanduser().resolve()
        if not repo.exists() or not repo.is_dir():
            print(f"ERROR: repo path not found: {repo}", file=sys.stderr)
            sys.exit(2)
        return str(repo)
    print(f"ERROR: unknown serve args: {' '.join(args)}", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
