"""Controlled cases for document-sourced project progress."""

import subprocess

import pytest

from drift_gate.desktop.progress_service import (
    evidence_candidates,
    extract_requirements,
    inspect_progress,
    list_documents,
    save_baseline,
)


def project(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "README.md").write_text(
        "# Service\n- [x] 로그인 화면을 `src/login.py`에 만든다\n"
        "- [ ] 요청과 세션을 연결한다\n",
        encoding="utf-8",
    )
    (repo / "src").mkdir()
    (repo / "src/login.py").write_text(
        'def login():\n    return "demo"\n', encoding="utf-8"
    )
    subprocess.run(
        ["git", "-C", str(repo), "add", "README.md", "src/login.py"], check=True
    )
    return repo


def test_checkmark_and_found_file_do_not_mean_complete(tmp_path):
    repo = project(tmp_path)
    assert list_documents(repo)["documents"][0]["path"] == "README.md"
    draft = extract_requirements(repo, ["README.md"])
    assert len(draft["requirements"]) == 2
    assert (
        evidence_candidates(repo, draft["requirements"][0])[0]["path"] == "src/login.py"
    )
    saved = save_baseline(repo, tmp_path / "state", draft)
    report = inspect_progress(repo, tmp_path / "state")
    assert saved["version"] == 1
    assert report["counts"]["unknown"] == 2
    assert report["counts"]["complete"] == 0


def test_verified_requires_reviewed_code_and_note(tmp_path):
    repo = project(tmp_path)
    draft = extract_requirements(repo, ["README.md"])
    item = draft["requirements"][0]
    item["implementation_status"] = "implemented"
    item["evidence"] = {
        "path": "src/login.py",
        "line": 1,
        "note": "로그인 함수를 정의한 줄을 확인함",
    }
    item["verification_status"] = "verified"
    item["verification_note"] = "로컬에서 로그인 흐름을 수동으로 확인함"
    save_baseline(repo, tmp_path / "state", draft)
    report = inspect_progress(repo, tmp_path / "state")
    assert report["counts"]["implemented"] == 1
    assert report["counts"]["complete"] == 1
    assert report["items"][0]["evidence"]["sha256"]
    (repo / "src/login.py").write_text(
        "def login():\n    raise NotImplementedError\n", encoding="utf-8"
    )
    changed = inspect_progress(repo, tmp_path / "state")
    assert changed["items"][0]["stale_evidence"]
    assert changed["counts"]["unknown"] == 2
    assert changed["counts"]["complete"] == 0


def test_missing_evidence_cannot_be_marked_implemented(tmp_path):
    repo = project(tmp_path)
    draft = extract_requirements(repo, ["README.md"])
    draft["requirements"][0]["implementation_status"] = "implemented"
    draft["requirements"][0]["evidence"] = {
        "path": "src/missing.py",
        "line": 1,
        "note": "추측",
    }
    with pytest.raises(ValueError):
        save_baseline(repo, tmp_path / "state", draft)


def test_document_change_invalidates_progress_and_excluded_item_leaves_denominator(
    tmp_path,
):
    repo = project(tmp_path)
    draft = extract_requirements(repo, ["README.md"])
    draft["requirements"][1]["included"] = False
    save_baseline(repo, tmp_path / "state", draft)
    assert inspect_progress(repo, tmp_path / "state")["total"] == 1
    (repo / "README.md").write_text("# Service\n새 계획\n", encoding="utf-8")
    report = inspect_progress(repo, tmp_path / "state")
    assert report["stale_documents"] == ["README.md"]
    assert report["counts"]["unknown"] == 1
    with pytest.raises(ValueError, match="변경"):
        save_baseline(repo, tmp_path / "state", draft)


def test_untracked_doc_is_visible_and_path_traversal_blocked(tmp_path):
    repo = project(tmp_path)
    (repo / "plan.md").write_text("## 대시보드\n", encoding="utf-8")
    docs = list_documents(repo)["documents"]
    assert any(d["path"] == "plan.md" and not d["tracked"] for d in docs)
    with pytest.raises(ValueError):
        extract_requirements(repo, ["../secret.md"])


def test_completion_table_becomes_reviewable_features(tmp_path):
    repo = project(tmp_path)
    (repo / "plan.md").write_text(
        "## 로드맵\n| 단계 | 구현 범위 | 완료 조건 |\n"
        "|---|---|---|\n| 로그인 | 화면 | 요청이 연결된다 |\n",
        encoding="utf-8",
    )
    result = extract_requirements(repo, ["plan.md"])
    assert len(result["requirements"]) == 1
    assert result["requirements"][0]["title"] == "로그인"
    assert result["requirements"][0]["criterion"] == "요청이 연결된다"
    assert result["requirements"][0]["implementation_status"] == "unknown"
