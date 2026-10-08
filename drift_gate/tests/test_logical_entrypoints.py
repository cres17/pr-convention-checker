"""Real local entrypoints and mocked GitHub transport share policy semantics."""
from copy import deepcopy
import json
import subprocess

import pytest
import yaml

from drift_gate.adapters.cli.runner import run_cli
from drift_gate.adapters.git.client import GitAdapter
from drift_gate.adapters.docs.content import attach_env_documents, local_document_reader
from drift_gate.adapters.github.client import GitHubAdapter
from drift_gate.adapters.github_action import runner as action
from drift_gate.adapters.mcp import tools
from drift_gate.desktop.service import scan_repository
from drift_gate.tests.test_logical_contracts import raw_policy, source, openapi, changed, policy


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.PIPE)


@pytest.mark.parametrize("case,expected", [("correct", "pass"), ("stale", "fail"), ("unsupported", "warn"), ("already-current", "pass")])
@pytest.mark.parametrize("minimum", ["any", "route-contract-change"])
@pytest.mark.parametrize('mode', ['api-schema', 'auto-strict'])
def test_local_cli_mcp_desktop_and_action_match(tmp_path, monkeypatch, capsys, case, expected, minimum, mode):
    git(tmp_path, "init")
    (tmp_path / "src").mkdir()
    before = source()
    after = source("id: list[int]") if case == "unsupported" else source("id: int")
    current_doc = openapi() if case != "stale" else openapi({"id": {"type": "integer"}, "label": {"type": "string"}})
    (tmp_path / "src/api.py").write_text(before)
    (tmp_path / "openapi.json").write_text(current_doc if case == "already-current" else openapi({"id": {"type": "integer"}, "label": {"type": "string"}}))
    config = raw_policy(action="warn", mode=mode)
    config["rules"][0]["when"]["min_change_intensity"] = minimum
    (tmp_path / ".drift-gate.yml").write_text(yaml.safe_dump(config))
    git(tmp_path, "add", ".")
    git(tmp_path, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "baseline")
    (tmp_path / "src/api.py").write_text(after)
    (tmp_path / "openapi.json").write_text(current_doc)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exit_status:
        run_cli(["check", "--base", "HEAD", "--json"])
    cli = json.loads(capsys.readouterr().out)
    assert exit_status.value.code == int(expected == "fail")
    mcp = tools.drift_gate_check_local(mode="full")
    desktop = scan_repository(tmp_path).result.to_dict()
    if case == "unsupported":
        evidence = tools.drift_gate_get_evidence(rule_id="response-contract")
        plan = tools.drift_gate_prepare_fix_plan()
        assert evidence["verification_limits"][0]["decision"] == "undetermined"
        assert plan["verification_limits"][0]["decision"] == "undetermined"
        assert not plan["actions"]  # no invented document correction for unknown semantics

    class Remote:
        def __init__(self, **kwargs):
            pass
        def get_pr_files_and_body(self, number):
            return deepcopy(GitAdapter(tmp_path).get_changed_files("HEAD")), ""
        def attach_env_documents(self, number, files, loaded):
            return attach_env_documents(files, loaded, local_document_reader(tmp_path))

    monkeypatch.setattr(action, "GitHubAdapter", Remote)
    monkeypatch.setattr("drift_gate.adapters.github.approvals.verify_ignores", lambda *args, **kwargs: [])
    for name, value in {"GITHUB_TOKEN": "fixture", "REPO": "fixture/repo", "PR_NUMBER": "1",
                        "GITHUB_WORKSPACE": str(tmp_path), "RUNNER_TEMP": str(tmp_path),
                        "POST_COMMENT": "false", "ANTHROPIC_API_KEY": "", "GITHUB_EVENT_PATH": "",
                        "GITHUB_OUTPUT": "", "GITHUB_STEP_SUMMARY": ""}.items():
        monkeypatch.setenv(name, value)
    action.main()
    github = json.loads((tmp_path / "drift_gate_report.json").read_text(encoding='utf-8'))
    for result in [cli, mcp, desktop, github]:
        assert result["result"] == expected
        assert result["rule_decisions"] == cli["rule_decisions"]
        assert result["summary"] == cli["summary"]
        assert result["schema_version"] == 3
        assert result["execution"]["input_sha256"] == cli["execution"]["input_sha256"]
    assert github["execution"]["source"] == "github-pr"


def test_remote_schema_snapshot_uses_merge_base_not_base_tip(monkeypatch):
    remote = GitHubAdapter(token="fixture", repo="fixture/repo")
    remote._snapshot_head, remote._snapshot_base = "head", "ahead-base"
    reads, comparisons = [], []
    def request(url):
        comparisons.append(url)
        return {"merge_base_commit": {"sha": "actual-merge-base"}}
    def read(path, ref):
        reads.append((path, ref))
        return openapi() if path == "openapi.json" else source("id: int") if ref == "head" else source()
    monkeypatch.setattr(remote, "_get", request)
    monkeypatch.setattr(remote, "get_file_text", read)
    file = changed()
    file.before_source = file.after_source = None
    files = remote.attach_env_documents(1, [file], policy())
    assert comparisons[0].endswith("/compare/ahead-base...head")
    assert ("src/api.py", "actual-merge-base") in reads
    assert files[0].before_source == source()
    assert files[0].after_source == source("id: int")


def test_remote_snapshot_failure_stays_unknown(monkeypatch):
    from drift_gate.adapters.inspection import inspect
    remote = GitHubAdapter(token="fixture", repo="fixture/repo")
    remote._snapshot_head, remote._snapshot_base = "head", "base"
    monkeypatch.setattr(remote, "_get", lambda url: (_ for _ in ()).throw(RuntimeError("unavailable")))
    monkeypatch.setattr(remote, "get_file_text", lambda path, ref: openapi() if path.endswith(".json") else source("id: int"))
    file = changed()
    file.before_source = file.after_source = None
    result = inspect(changed_files=remote.attach_env_documents(1, [file], policy(action="warn")), policy=policy(action="warn"))
    assert result.result == "warn"
    assert result.rule_decisions[0].decision == "undetermined"


def test_missing_document_and_read_error_have_different_meanings(tmp_path):
    from drift_gate.adapters.inspection import inspect
    absent = attach_env_documents([changed()], policy(action="warn"), local_document_reader(tmp_path))
    denied = attach_env_documents([changed()], policy(action="warn"), lambda path: (_ for _ in ()).throw(OSError("denied")))
    assert absent[-1].document_input_state == "missing"
    assert denied[-1].document_input_state == "unavailable"
    assert inspect(changed_files=absent, policy=policy(action="warn")).result == "fail"
    assert inspect(changed_files=denied, policy=policy(action="warn")).result == "warn"
