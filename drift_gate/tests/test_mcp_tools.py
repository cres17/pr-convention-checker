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
