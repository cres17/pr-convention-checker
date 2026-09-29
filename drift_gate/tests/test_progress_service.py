"""Controlled cases for document-sourced project progress."""

import subprocess

import pytest

from drift_gate.desktop.progress_service import (
    BaselineError,
    evidence_candidates,
    extract_requirements,
    inspect_progress,
    list_documents,
    load_baseline,
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
    assert report["items"][0]["effective_status"] == "implemented"
    (repo / "src/login.py").write_text(
        "def login():\n    raise NotImplementedError\n", encoding="utf-8"
    )
    changed = inspect_progress(repo, tmp_path / "state")
    assert changed["items"][0]["stale_evidence"]
    assert changed["items"][0]["effective_status"] == "unknown"
    assert changed["counts"]["unknown"] == 2
    statuses = [entry["effective_status"] for entry in changed["items"]]
    assert statuses.count("unknown") == changed["counts"]["unknown"]
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
    first = inspect_progress(repo, tmp_path / "state")
    assert first["total"] == 1
    assert [entry["effective_status"] for entry in first["items"]] == ["unknown", "excluded"]
    (repo / "README.md").write_text("# Service\n새 계획\n", encoding="utf-8")
    report = inspect_progress(repo, tmp_path / "state")
    assert report["stale_documents"] == ["README.md"]
    assert report["counts"]["unknown"] == 1
    assert [entry["effective_status"] for entry in report["items"]] == ["unknown", "excluded"]
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


def test_code_blocks_are_not_requirements_and_real_headings_survive(tmp_path):
    repo = project(tmp_path)
    (repo / "GUIDE.md").write_text(
        "## 로그인\n\n```md\n- [ ] 코드블록 안 체크\n## 예시 제목\n```\n\n"
        "~~~\n- [x] 물결 펜스 안\n~~~\n\n````\n```\n- [ ] 중첩 펜스 안\n```\n````\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(repo), "add", "GUIDE.md"], check=True)
    titles = [
        item["title"]
        for item in extract_requirements(repo, ["GUIDE.md"])["requirements"]
    ]
    assert titles == ["로그인"]


def test_unclosed_fence_hides_the_rest_but_keeps_earlier_items(tmp_path):
    repo = project(tmp_path)
    (repo / "GUIDE.md").write_text(
        "- [ ] 앞 항목\n```\n- [ ] 닫히지 않은 블록\n", encoding="utf-8"
    )
    subprocess.run(["git", "-C", str(repo), "add", "GUIDE.md"], check=True)
    titles = [i["title"] for i in extract_requirements(repo, ["GUIDE.md"])["requirements"]]
    assert titles == ["앞 항목"]


def test_same_title_in_several_documents_is_kept_as_duplicate_locations(tmp_path):
    repo = project(tmp_path)
    (repo / "a.md").write_text("- [x] 로그인\n", encoding="utf-8")
    (repo / "b.md").write_text("- [ ] 로그인\n- [ ] 로그인\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "a.md", "b.md"], check=True)
    draft = extract_requirements(repo, ["a.md", "b.md"])
    assert len(draft["requirements"]) == 1
    item = draft["requirements"][0]
    assert item["source"]["path"] == "a.md"
    assert [(d["path"], d["line"]) for d in item["duplicates"]] == [("b.md", 1), ("b.md", 2)]
    saved = save_baseline(repo, tmp_path / "state", draft)
    assert len(saved["requirements"][0]["duplicates"]) == 2


def test_doc_whose_only_item_is_a_duplicate_does_not_fall_back_to_headings(tmp_path):
    repo = project(tmp_path)
    (repo / "a.md").write_text("- [x] 로그인\n", encoding="utf-8")
    (repo / "b.md").write_text("## 개요\n- [ ] 로그인\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "a.md", "b.md"], check=True)
    draft = extract_requirements(repo, ["a.md", "b.md"])
    assert [i["title"] for i in draft["requirements"]] == ["로그인"]


def test_save_reports_every_invalid_item_with_its_field(tmp_path):
    repo = project(tmp_path)
    draft = extract_requirements(repo, ["README.md"])
    first, second = draft["requirements"]
    first["implementation_status"] = "implemented"
    first["evidence"] = {"path": "src/login.py", "line": 99, "note": ""}
    second["title"] = " "
    second["implementation_status"] = "not_implemented"
    with pytest.raises(BaselineError) as raised:
        save_baseline(repo, tmp_path / "state", draft)
    found = {(e["id"], e["field"]) for e in raised.value.errors}
    assert found == {
        (first["id"], "evidence.line"),
        (second["id"], "title"),
        (second["id"], "implementation_note"),
    }
    assert "3개 항목" in str(raised.value)
    assert load_baseline(repo, tmp_path / "state") is None


def test_duplicate_locations_must_point_at_selected_documents(tmp_path):
    repo = project(tmp_path)
    draft = extract_requirements(repo, ["README.md"])
    draft["requirements"][0]["duplicates"] = [{"path": "other.md", "line": 1}]
    with pytest.raises(BaselineError):
        save_baseline(repo, tmp_path / "state", draft)
