import pytest

from drift_gate.adapters.mcp.tools import (
    drift_gate_check_pr,
    drift_gate_explain_rule,
    drift_gate_get_evidence,
    drift_gate_history,
    drift_gate_list_rules,
    drift_gate_prepare_fix_plan,
    drift_gate_suggest_policy,
)
from drift_gate.adapters.mcp.server import handle_request
from drift_gate.adapters.history.store import append_result
from drift_gate.core.models.policy import Gate
from drift_gate.core.models.result import EvaluationResult


def test_mcp_list_and_explain_rules(tmp_path):
    policy = tmp_path / ".drift-gate.yml"
    policy.write_text(
        """
rules:
  - id: api-contract-sync
    when:
      any_changed: ["src/routes/**"]
    require:
      groups:
        - name: docs
          any_changed: ["docs/**"]
    severity: blocker
    message: API docs required
""",
        encoding="utf-8",
    )

    rules = drift_gate_list_rules(str(policy))
    explained = drift_gate_explain_rule("api-contract-sync", str(policy))

    assert rules[0]["id"] == "api-contract-sync"
    assert explained["severity"] == "blocker"
    with pytest.raises(KeyError):
        drift_gate_explain_rule("missing", str(policy))


def test_mcp_suggest_policy(tmp_path):
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / "src" / "routes").mkdir(parents=True)

    suggestion = drift_gate_suggest_policy(str(tmp_path))

    assert "api" in suggestion["suggested_presets"]
    assert "ci" in suggestion["suggested_presets"]


def test_mcp_history(tmp_path):
    history_path = tmp_path / "history.jsonl"
    append_result(
        EvaluationResult(
            change_types=[],
            violations=[],
            skipped_rules=[],
            rejected_ignores=[],
            gate=Gate(),
        ),
        history_path,
    )

    history = drift_gate_history(path=str(history_path), days=30)

    assert history["summary"]["total"] == 1
    assert history["records"][0]["result"] == "pass"


def test_mcp_check_pr(monkeypatch, tmp_path):
    from drift_gate.adapters.github.client import GitHubAdapter
    from drift_gate.core.models.changed_file import ChangedFile

    policy = tmp_path / ".drift-gate.yml"
    policy.write_text(
        """
rules:
  - id: api-contract-sync
    when:
      any_changed: ["src/routes/**"]
    require:
      groups:
        - name: docs
          any_changed: ["docs/**"]
    severity: blocker
""",
        encoding="utf-8",
    )

    def fake_files_and_body(self, pr_number):
        return [ChangedFile(path="src/routes/users.ts", status="modified")], ""

    monkeypatch.setattr(GitHubAdapter, "get_pr_files_and_body", fake_files_and_body)

    report = drift_gate_check_pr(
        1,
        repo="owner/repo",
        token="token",
        policy_path=str(policy),
    )

    assert report["result"] == "fail"
    assert report["violations"][0]["rule_id"] == "api-contract-sync"
    assert isinstance(report["violations"][0]["trigger_files"][0], str)
    assert "patch" not in report["violations"][0]


def test_mcp_prepare_fix_plan(monkeypatch, tmp_path):
    from drift_gate.adapters.git.client import GitAdapter
    from drift_gate.core.models.changed_file import ChangedFile

    policy = tmp_path / ".drift-gate.yml"
    policy.write_text(
        """
rules:
  - id: api-contract-sync
    when:
      any_changed: ["src/routes/**"]
    require:
      groups:
        - name: docs
          any_changed: ["docs/api/**"]
    severity: blocker
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        GitAdapter,
        "get_changed_files",
        lambda self, base: [ChangedFile(path="src/routes/users.ts", status="modified")],
    )

    plan = drift_gate_prepare_fix_plan(policy_path=str(policy))

    assert plan["result"] == "fail"
    assert plan["actions"][0]["suggested_targets"] == ["docs/api/**"]


def test_mcp_server_handle_request(tmp_path):
    policy = tmp_path / ".drift-gate.yml"
    policy.write_text(
        """
rules:
  - id: api-contract-sync
    when:
      any_changed: ["src/routes/**"]
    require:
      groups:
        - name: docs
          any_changed: ["docs/**"]
    severity: blocker
""",
        encoding="utf-8",
    )

    response = handle_request({
        "tool": "drift_gate_list_rules",
        "args": {"policy_path": str(policy)},
    })

    assert response["ok"] is True
    assert response["result"][0]["id"] == "api-contract-sync"


def test_mcp_compact_local_and_bounded_evidence(monkeypatch, tmp_path):
    from drift_gate.adapters.git.client import GitAdapter
    from drift_gate.core.models.changed_file import ChangedFile
    from drift_gate.adapters.mcp.tools import drift_gate_check_local

    policy = tmp_path / ".drift-gate.yml"
    policy.write_text(
        """
rules:
  - id: api-contract-sync
    when:
      any_changed: ["src/routes/**"]
    require:
      groups:
        - name: docs
          any_changed: ["docs/**"]
    severity: blocker
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        GitAdapter,
        "get_changed_files",
        lambda self, base: [
            ChangedFile(
                path="src/routes/users.ts",
                status="modified",
                patch="diff --git a/src/routes/users.ts b/src/routes/users.ts\n"
                "@@ -1 +1 @@\n-router.get('/users', old)\n"
                "+router.get('/users', next)\n",
            )
        ],
    )

    compact = drift_gate_check_local(policy_path=str(policy), token_budget=400)
    evidence = drift_gate_get_evidence(
        policy_path=str(policy),
        rule_id="api-contract-sync",
        max_lines_per_file=3,
    )

    assert compact["token_strategy"]["mode"] == "compact"
    assert "rule_decisions" not in compact
    assert compact["violations"][0]["trigger_files"] == ["src/routes/users.ts"]
    assert "router.get" in evidence["evidence"][0]["files"][0]["diff_snippet"]


@pytest.mark.parametrize('frame', [[], None, 3, 'bad', {'jsonrpc':'2.0', 'method':[]},
    {'jsonrpc':'2.0', 'method':'tools/list', 'params':[]},
    {'jsonrpc':'2.0', 'method':'tools/call', 'params':{'name':[], 'arguments':{}}},
    {'jsonrpc':'2.0', 'method':'tools/call', 'params':{'name':'drift_gate_history', 'arguments':[]}},
    {'tool':[], 'args':{}}, {'tool':'drift_gate_history', 'args':[]}])
def test_mcp_rejects_bad_shapes_without_raising(frame):
    response = handle_request(frame)
    assert 'error' in response


def test_mcp_stdio_survives_bad_frames_and_advertises_real_arguments():
    import json
    import subprocess
    import sys
    frames = [[], None, {'jsonrpc':'2.0','id':1,'method':'tools/list','params':[]},
              {'jsonrpc':'2.0','id':2,'method':'tools/list'}]
    value = subprocess.run([sys.executable, '-m', 'drift_gate.adapters.mcp.server'],
        input='\n'.join(json.dumps(frame) for frame in frames) + '\n', capture_output=True, text=True, timeout=20)
    assert value.returncode == 0, value.stderr
    responses = [json.loads(line) for line in value.stdout.splitlines()]
    assert len(responses) == 4 and all('error' in row for row in responses[:3])
    tool = next(row for row in responses[-1]['result']['tools'] if row['name'] == 'drift_gate_check_pr')
    assert set(tool['inputSchema']['required']) == {'pr_number', 'repo', 'token'}
    assert tool['inputSchema']['properties']['pr_number']['type'] == 'integer'
    assert not tool['inputSchema']['additionalProperties']


@pytest.mark.parametrize('arguments', [{'days':'30'}, {'days':True}, {'unknown':1}])
def test_mcp_rejects_arguments_before_calling_the_tool(arguments, monkeypatch):
    from drift_gate.adapters.mcp import tools
    monkeypatch.setattr(tools, 'load_records', lambda *a, **k: pytest.fail('tool should not run'))
    response = handle_request({'jsonrpc':'2.0','id':1,'method':'tools/call',
        'params':{'name':'drift_gate_history', 'arguments':arguments}})
    assert response['error']['code'] == -32602


def test_mcp_oversized_frame_is_drained_without_losing_the_next_request():
    import json
    import subprocess
    import sys
    from drift_gate.adapters.mcp.server import MAX_REQUEST_BYTES
    valid = {'jsonrpc':'2.0', 'id':7, 'method':'tools/list'}
    result = subprocess.run([sys.executable, '-m', 'drift_gate.adapters.mcp.server'],
        input='x' * (MAX_REQUEST_BYTES + 200) + '\n' + json.dumps(valid) + '\n',
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 0
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(rows) == 2 and rows[0]['error']['code'] == -32600
    assert rows[1]['id'] == 7 and 'result' in rows[1]
