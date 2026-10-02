import subprocess

import pytest

from drift_gate.adapters.cli.runner import POLICY_PRESETS
from drift_gate.adapters.policy_loader import load_policy
from drift_gate.desktop.policy_setup import create_policy, preview_policy
from drift_gate.desktop.service import PolicyMissingError, scan_repository


def repo_with(tmp_path, files):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@e.com", "-c", "user.name=t", "commit", "-qm", "i"], check=True)
    return repo


def test_scan_without_policy_raises_a_recognizable_error(tmp_path):
    repo = repo_with(tmp_path, {"README.md": "x\n"})
    with pytest.raises(PolicyMissingError) as raised:
        scan_repository(repo)
    assert raised.value.repository == repo.resolve()
    assert ".drift-gate.yml" in str(raised.value)


def test_preview_recommends_from_the_repository_not_the_working_directory(tmp_path):
    repo = repo_with(tmp_path, {"src/routes/users.py": "x\n", "requirements.txt": "fastapi\n"})
    preview = preview_policy(repo)
    assert preview["preset"] == "api" and not preview["exists"]
    assert preview["recommendations"]["frameworks"] == ["FastAPI"]
    assert "docs/api/**" in preview["recommendations"]["docs_paths"]
    assert preview["policy"] == POLICY_PRESETS["api"]
    assert preview["presets"][0] == "auto" and "fullstack" in preview["presets"]
    assert preview_policy(repo, "db")["policy"] == POLICY_PRESETS["db"]
    assert not (repo / ".drift-gate.yml").exists()  # preview writes nothing


def test_create_writes_a_loadable_policy_and_never_overwrites(tmp_path):
    repo = repo_with(tmp_path, {"src/routes/users.py": "x\n"})
    created = create_policy(repo, "auto")
    assert created["preset"] == "api"
    assert (repo / ".drift-gate.yml").read_text(encoding="utf-8") == POLICY_PRESETS["api"]
    assert load_policy(repo / ".drift-gate.yml").rules
    (repo / ".drift-gate.yml").write_text("rules: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="덮어쓰지"):
        create_policy(repo, "api")
    assert (repo / ".drift-gate.yml").read_text(encoding="utf-8") == "rules: []\n"
    assert preview_policy(repo)["exists"]


def test_unknown_preset_is_rejected(tmp_path):
    repo = repo_with(tmp_path, {"README.md": "x\n"})
    for call in (preview_policy, create_policy):
        with pytest.raises(ValueError):
            call(repo, "../../etc")


@pytest.mark.parametrize("preset", sorted(POLICY_PRESETS))
def test_every_preset_loads_and_scans(tmp_path, preset):
    repo = repo_with(tmp_path, {"README.md": "x\n"})
    create_policy(repo, preset)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    assert scan_repository(repo).result.result in {"pass", "warn", "fail"}
