"""The desktop path must match local CLI semantics without changing cwd."""

import os
from pathlib import Path
import subprocess

import pytest

from drift_gate.desktop.service import scan_repository


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "sample"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "src").mkdir()
    (root / "src" / "api.py").write_text("before\n", encoding="utf-8")
    (root / ".drift-gate.yml").write_text(
        "rules:\n"
        "  - id: api-doc-sync\n"
        "    when:\n"
        "      any_changed: ['src/**']\n"
        "    require:\n"
        "      groups:\n"
        "        - name: API docs\n"
        "          any_changed: ['docs/api.md']\n"
        "    severity: blocker\n"
        "gate:\n"
        "  fail_on_blocker: true\n",
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "baseline")
    return root


def test_scan_selected_repo_without_changing_process_directory(repository):
    original = Path.cwd()
    (repository / "src" / "api.py").write_text("after\n", encoding="utf-8")
    scan = scan_repository(repository / "src", "HEAD")
    assert scan.repository == repository.resolve()
    assert scan.changed_file_count == 1
    assert scan.result.result == "fail"
    assert scan.result.rule_decisions[0].rule_id == "api-doc-sync"
    assert Path.cwd() == original


def test_invalid_base_is_error_not_empty_pass(repository):
    with pytest.raises(ValueError, match="비교 기준"):
        scan_repository(repository, "does-not-exist")


def test_empty_repository_path_is_error():
    with pytest.raises(ValueError, match="폴더"):
        scan_repository("")


def test_missing_policy_is_error(repository):
    os.remove(repository / ".drift-gate.yml")
    with pytest.raises(ValueError, match=".drift-gate.yml"):
        scan_repository(repository)


def test_resolve_document_allows_only_text_files_inside_repository(tmp_path):
    from drift_gate.desktop.service import resolve_document

    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs/api.md").write_text("# API\n", encoding="utf-8")
    (repo / "run.sh").write_text("echo hi\n", encoding="utf-8")
    (tmp_path / "outside.md").write_text("x", encoding="utf-8")
    assert resolve_document(repo, "docs/api.md") == (repo / "docs/api.md").resolve()
    for bad in ("docs/missing.md", "run.sh", "../outside.md", "docs/**", "", str(tmp_path / "outside.md")):
        with pytest.raises(ValueError):
            resolve_document(repo, bad)
