import json
from urllib.parse import parse_qs, urlparse

from drift_gate.adapters.github.client import GitHubAdapter
from drift_gate.adapters.github_action.runner import (
    _escape_workflow_command,
    _is_fork_pr,
)


def test_workflow_command_escape():
    assert _escape_workflow_command("a:b,c%") == "a%3Ab%2Cc%25"
    assert _escape_workflow_command("line1\nline2") == "line1%0Aline2"


def test_fork_pr_detection(tmp_path):
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps({
            "pull_request": {
                "head": {"repo": {"full_name": "someone/fork"}},
                "base": {"repo": {"full_name": "owner/repo"}},
            }
        }),
        encoding="utf-8",
    )

    assert _is_fork_pr(str(event_path), "owner/repo") is True


def test_same_repo_pr_not_fork(tmp_path):
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps({
            "pull_request": {
                "head": {"repo": {"full_name": "owner/repo"}},
                "base": {"repo": {"full_name": "owner/repo"}},
            }
        }),
        encoding="utf-8",
    )

    assert _is_fork_pr(str(event_path), "owner/repo") is False


def test_github_adapter_paginates_pr_files(monkeypatch):
    pages = {
        1: [{"filename": f"file_{i}.py", "status": "modified"} for i in range(100)],
        2: [{"filename": "last.py", "status": "added"}],
    }

    def fake_get(self, url):
        page = int(parse_qs(urlparse(url).query)["page"][0])
        return pages[page]

    monkeypatch.setattr(GitHubAdapter, "_get", fake_get)

    files = GitHubAdapter(token="token", repo="owner/repo").get_pr_files(1)

    assert len(files) == 101
    assert files[-1].path == "last.py"
