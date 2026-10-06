"""Tiny stdio MCP server wrapper for Drift Gate helpers.

This intentionally implements the small JSON-RPC surface needed by local AI
tools: ``initialize``, ``tools/list``, and ``tools/call``. It also accepts the
legacy ``{"tool": "...", "args": {...}}`` JSON-line shape used by tests.
"""
import json
import inspect
import os
import sys
from pathlib import Path

from drift_gate.adapters.mcp import tools

MAX_REQUEST_BYTES = 1_000_000
MAX_RESPONSE_BYTES = 2_000_000
ALLOWED_ROOT = None  # fixed when the server starts; requests cannot widen it


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
    if not isinstance(request, dict):
        return _jsonrpc_error(None, -32600, "request must be an object; batches are unsupported")
    if "method" in request:
        response = _handle_jsonrpc(request)
        if ('id' not in request and request.get('jsonrpc') == '2.0'
            and isinstance(request.get('method'), str) and isinstance(request.get('params', {}), dict)):
            return {}
        return response

    tool_name = request.get("tool", "")
    args = request.get("args", {})
    if not isinstance(tool_name, str) or not isinstance(args, dict):
        return {"ok": False, "error": "tool must be a string and args an object"}
    if tool_name not in TOOL_MAP:
        return {"ok": False, "error": f"unknown tool: {tool_name}"}
    try:
        return {"ok": True, "result": _call_tool(tool_name, args)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _handle_jsonrpc(request: dict) -> dict:
    request_id = request.get("id")
    method = request.get("method", "")
    params = request.get("params", {})
    if (request.get("jsonrpc") != "2.0" or not isinstance(method, str)
            or (request_id is not None and (type(request_id) not in (str, int)))
            or not isinstance(params, dict)):
        return _jsonrpc_error(None, -32600, "invalid JSON-RPC envelope")

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
            args = params.get("arguments", {})
            if not isinstance(name, str) or not isinstance(args, dict):
                return _jsonrpc_error(request_id, -32602, "name must be a string and arguments an object")
            if name not in TOOL_MAP:
                raise KeyError(f"unknown tool: {name}")
            try:
                tool_result = _call_tool(name, args)
            except (TypeError, ValueError) as exc:
                return _jsonrpc_error(request_id, -32602, str(exc))
            result = {
                "content": [{
                    "type": "text",
                    "text": json.dumps(tool_result, ensure_ascii=False, indent=2, allow_nan=False),
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


def _call_tool(name: str, arguments: dict):
    function = TOOL_MAP[name]
    bound = inspect.signature(function).bind(**arguments)
    bound.apply_defaults()
    for key, value in bound.arguments.items():
        annotation = inspect.signature(function).parameters[key].annotation
        if annotation in (str, int, bool) and type(value) is not annotation:
            raise TypeError(f'{key} must be {annotation.__name__}')
        if ALLOWED_ROOT is not None and key in ('path', 'policy_path', 'repo_root'):
            target = Path(value).expanduser().resolve()
            if not target.is_relative_to(ALLOWED_ROOT):
                raise ValueError(f'{key} is outside the server repository')
            if target.is_file() and target.stat().st_size > MAX_REQUEST_BYTES:
                raise ValueError(f'{key} exceeds the server file size limit')
    return function(**arguments)


def _tool_schema(name: str) -> dict:
    parameters = inspect.signature(TOOL_MAP[name]).parameters
    properties = {}
    required = []
    for key, parameter in parameters.items():
        kind = {str: "string", int: "integer", bool: "boolean"}.get(parameter.annotation, "string")
        properties[key] = {"type": kind}
        if parameter.default is inspect.Parameter.empty:
            required.append(key)
    return {
        "name": name,
        "description": TOOL_DESCRIPTIONS.get(name, name),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": required,
        },
    }


def main(argv=None) -> None:
    global ALLOWED_ROOT
    repo = _parse_repo_arg(sys.argv[1:] if argv is None else argv)
    if repo:
        os.chdir(repo)
    ALLOWED_ROOT = Path.cwd().resolve()
    while True:
        line = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
        if not line:
            break
        if len(line) > MAX_REQUEST_BYTES:
            while line and not line.endswith(b'\n'):
                line = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
            print(json.dumps(_jsonrpc_error(None, -32600, 'request exceeds size limit')), flush=True)
            continue
        if not line.strip():
            continue
        request = None
        try:
            request = json.loads(line.decode('utf-8'), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f'non-finite JSON number: {value}')))
            response = handle_request(request)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
            response = _jsonrpc_error(None, -32700, f'invalid json: {exc}')
        except Exception as exc:
            # A bad frame or tool must not terminate the remaining stdio session.
            response = _jsonrpc_error(None, -32603, str(exc))
        if response:
            try:
                encoded = json.dumps(response, ensure_ascii=False, allow_nan=False)
                if len(encoded.encode('utf-8')) > MAX_RESPONSE_BYTES:
                    raise ValueError('response exceeds size limit')
            except (ValueError, TypeError, RecursionError) as exc:
                encoded = json.dumps(_jsonrpc_error(request.get('id') if isinstance(request, dict) else None,
                                                    -32603, str(exc)))
            print(encoded, flush=True)


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
