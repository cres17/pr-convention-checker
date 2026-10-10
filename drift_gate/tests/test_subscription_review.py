import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.policy import Gate
from drift_gate.core.models.result import EvaluationResult
from drift_gate.desktop.service import DesktopScan
from drift_gate.desktop import subscription_review as module


def response(verdict="warn"):
    return {"verdict": verdict, "summary": "문서 확인 필요", "findings": [
        {"rule_id": "api", "reason": "새 경로가 문서에 없음", "suggestion": "문서 갱신"}],
        "limitations": ["전체 파일은 제공되지 않음"]}


def scan(files=()):
    result = EvaluationResult([], [], [], [], Gate(), result="pass")
    return DesktopScan(Path("/sample"), "HEAD", len(files), result, tuple(files), "rules: []")


def test_prompt_contains_passed_changes_and_excludes_env_values():
    value = scan([ChangedFile("src/api.py", "modified", patch="+@app.get('/members')"),
                  ChangedFile(".env", "modified", patch="+TOKEN=private-value")])
    prompt = module.build_review_prompt(value)
    assert "/members" in prompt
    assert "private-value" not in prompt
    assert value.result.result == "pass"


def test_large_prompt_discloses_omissions():
    prompt = module.build_review_prompt(scan([ChangedFile(f"src/{i}.py", "modified", patch="x" * 6000)
                                             for i in range(80)]))
    payload = json.loads(prompt.split("검사 자료:\n", 1)[1])
    assert payload["omitted_files"] > 0
    assert any(file["truncated"] for file in payload["files"])
    assert sum(len(file["patch"]) for file in payload["files"]) <= 24000


@pytest.mark.parametrize("data", ["not json", {}, {**response(), "verdict": "approved"},
                                  {**response(), "findings": ["bad"]},
                                  {**response(), "summary": ""}])
def test_invalid_review_never_becomes_a_pass(data):
    with pytest.raises(module.ReviewError):
        module.parse_review(data, "codex")


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_official_cli_protocol_and_subscription_auth(monkeypatch, provider):
    calls = []
    monkeypatch.setattr(module, "find_cli", lambda *args: "/official/cli")
    monkeypatch.setenv("CODEX_API_KEY", "do-not-forward")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "do-not-forward")

    def execute(args, **kwargs):
        calls.append((args, kwargs))
        assert "CODEX_API_KEY" not in kwargs["env"]
        assert "ANTHROPIC_API_KEY" not in kwargs["env"]
        if len(calls) == 1:
            auth = "Logged in using ChatGPT" if provider == "codex" else json.dumps(
                {"loggedIn": True, "authMethod": "claude.ai"})
            return subprocess.CompletedProcess(args, 0, auth, "")
        output = json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(response())}}) if provider == "codex" else json.dumps({"is_error": False, "structured_output": response()})
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(module, "_execute", execute)
    answer = module.review_with_subscription("private prompt", provider)
    assert answer.verdict == "warn"
    args, kwargs = calls[-1]
    assert "private prompt" not in args
    assert kwargs["input_text"] == "private prompt"
    assert kwargs["cwd"] != str(Path.cwd())
    if provider == "codex":
        assert "read-only" in args and "--ignore-user-config" in args
        assert "features.shell_tool=false" in args
    else:
        assert "--safe-mode" in args and args[args.index("--tools") + 1] == ""


def test_api_login_does_not_trigger_subscription_review(monkeypatch):
    monkeypatch.setattr(module, "find_cli", lambda *args: "/official/cli")
    calls = []
    def execute(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "Logged in using an API key", "")
    monkeypatch.setattr(module, "_execute", execute)
    with pytest.raises(module.ReviewError, match="구독 계정"):
        module.review_with_subscription("prompt", "codex")
    assert len(calls) == 1


def test_cancel_kills_process(tmp_path):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(module.ReviewError, match="중지"):
        module._execute([sys.executable, "-c", "import time; time.sleep(30)"],
                        cwd=tmp_path, env=dict(os.environ), cancel=cancel, timeout=5)


def test_timeout_is_not_a_pass(tmp_path):
    with pytest.raises(module.ReviewError, match="시간"):
        module._execute([sys.executable, "-c", "import time; time.sleep(30)"],
                        cwd=tmp_path, env=dict(os.environ), cancel=threading.Event(), timeout=0.05)


def test_sensitive_html_is_escaped():
    pytest.importorskip("PySide6")
    from drift_gate.desktop.review_dialog import review_html
    answer = module.parse_review({**response(), "summary": "<img src=x>"}, "codex")
    assert "<img src=x>" not in review_html(answer)


def test_windows_npm_shim_uses_node_without_shell(tmp_path, monkeypatch):
    script = tmp_path / "node_modules/@openai/codex/bin/codex.js"
    script.parent.mkdir(parents=True)
    script.write_text("// fixture", encoding="utf-8")
    monkeypatch.setattr(module.shutil, "which", lambda _: "node.exe")
    assert module._cli_prefix(str(tmp_path / "codex.cmd"), "codex") == ["node.exe", str(script)]
