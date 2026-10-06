"""Controlled cases for document-sourced project progress."""

import shutil
import subprocess
from copy import deepcopy

import pytest

from drift_gate.desktop.progress_service import (
    BaselineError,
    evidence_candidates,
    extract_requirements,
    inspect_progress,
    list_documents,
    load_baseline,
    progress_history_view,
    record_snapshot,
    normalize_remote,
    save_baseline,
    scan_impact,
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


def _origin(repo, url):
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", url], check=True)


def test_remote_urls_of_one_repository_normalize_to_the_same_identity():
    same = [
        "git@github.com:cres17/pr-convention-checker.git",
        "https://github.com/cres17/pr-convention-checker",
        "https://user:token@GitHub.com/cres17/pr-convention-checker.git/",
        "ssh://git@github.com/cres17/pr-convention-checker.git",
    ]
    assert {normalize_remote(url) for url in same} == {"github.com/cres17/pr-convention-checker"}
    assert normalize_remote("https://github.com/cres17/other") != normalize_remote(same[0])
    for local in ("", "/srv/git/x.git", "../x.git", "C:\\repos\\x", "file:///srv/x.git", "~/x", "plain"):
        assert normalize_remote(local) is None


def test_baseline_follows_the_remote_when_the_folder_moves(tmp_path):
    repo = project(tmp_path)
    _origin(repo, "git@github.com:acme/shop.git")
    draft = extract_requirements(repo, ["README.md"])
    save_baseline(repo, tmp_path / "state", draft)
    moved = tmp_path / "moved" / "shop-clone"
    moved.parent.mkdir()
    shutil.copytree(repo, moved)
    subprocess.run(["git", "-C", str(moved), "remote", "set-url", "origin", "https://github.com/acme/shop"], check=True)
    loaded = load_baseline(moved, tmp_path / "state")
    assert loaded and loaded["version"] == 1 and loaded["remote"] == "github.com/acme/shop"
    assert inspect_progress(moved, tmp_path / "state")["total"] == 2


def test_projects_with_different_remotes_keep_separate_baselines(tmp_path):
    first = project(tmp_path)
    _origin(first, "https://github.com/acme/one.git")
    save_baseline(first, tmp_path / "state", extract_requirements(first, ["README.md"]))
    second = tmp_path / "second"
    shutil.copytree(first, second)
    subprocess.run(["git", "-C", str(second), "remote", "set-url", "origin", "https://github.com/acme/two.git"], check=True)
    assert load_baseline(second, tmp_path / "state") is None


def test_baseline_saved_before_remote_keys_is_found_and_rewritten(tmp_path):
    repo = project(tmp_path)
    draft = extract_requirements(repo, ["README.md"])
    state = tmp_path / "state"
    save_baseline(repo, state, draft)  # no remote yet: stored under the path key
    _origin(repo, "https://github.com/acme/shop.git")
    old = load_baseline(repo, state)
    assert old and old["version"] == 1 and "remote" not in old
    migrated = save_baseline(repo, state, draft)
    assert migrated["version"] == 1 and migrated["remote"] == "github.com/acme/shop"
    assert len(list(state.glob("*.json"))) == 2  # the old file is left untouched
    moved = tmp_path / "elsewhere"
    shutil.copytree(repo, moved)
    assert load_baseline(moved, state)["remote"] == "github.com/acme/shop"


def test_repository_without_a_usable_remote_still_keys_by_path(tmp_path):
    repo = project(tmp_path)
    _origin(repo, "/srv/git/local.git")
    save_baseline(repo, tmp_path / "state", extract_requirements(repo, ["README.md"]))
    assert "remote" not in load_baseline(repo, tmp_path / "state")
    moved = tmp_path / "moved"
    shutil.copytree(repo, moved)
    assert load_baseline(moved, tmp_path / "state") is None


def test_document_done_mark_without_backing_evidence_is_reported_not_trusted(tmp_path):
    repo = project(tmp_path)  # README: "- [x] 로그인 ..." and "- [ ] 요청과 세션 ..."
    draft = extract_requirements(repo, ["README.md"])
    assert [i.get("doc_marked_done") for i in draft["requirements"]] == [True, False]
    draft = save_baseline(repo, tmp_path / "state", draft)
    report = inspect_progress(repo, tmp_path / "state")
    assert [i.get("doc_claim") for i in report["items"]] == ["unbacked", None]
    assert report["doc_claims_unbacked"] == 1
    assert report["counts"]["implemented"] == 0  # the checkmark counts for nothing

    draft["requirements"][0]["implementation_status"] = "implemented"
    draft["requirements"][0]["evidence"] = {"path": "src/login.py", "line": 1, "note": "함수 정의 확인"}
    save_baseline(repo, tmp_path / "state", draft)
    backed = inspect_progress(repo, tmp_path / "state")
    assert backed["doc_claims_unbacked"] == 0
    (repo / "src/login.py").write_text("def login():\n    pass\n# changed\n", encoding="utf-8")
    stale = inspect_progress(repo, tmp_path / "state")
    assert stale["items"][0]["doc_claim"] == "unbacked"  # evidence became stale


def test_invalid_document_mark_is_rejected(tmp_path):
    repo = project(tmp_path)
    draft = extract_requirements(repo, ["README.md"])
    draft["requirements"][0]["doc_marked_done"] = "yes"
    with pytest.raises(BaselineError):
        save_baseline(repo, tmp_path / "state", draft)


def test_evidence_becomes_stale_when_its_file_changes_shrinks_or_disappears(tmp_path):
    repo = project(tmp_path)
    (repo / "src/other.py").write_text("a = 1\nb = 2\n", encoding="utf-8")
    draft = extract_requirements(repo, ["README.md"])
    for item, name, line in zip(draft["requirements"], ("login.py", "login.py"), (1, 2)):
        item["implementation_status"] = "implemented"
        item["evidence"] = {"path": f"src/{name}", "line": line, "note": "확인"}
    save_baseline(repo, tmp_path / "state", draft)
    state = tmp_path / "state"
    assert [i["stale_evidence"] for i in inspect_progress(repo, state)["items"]] == [False, False]
    (repo / "src/login.py").write_text("def login():\n", encoding="utf-8")  # shrinks past line 2
    assert [i["stale_evidence"] for i in inspect_progress(repo, state)["items"]] == [True, True]
    (repo / "src/login.py").unlink()
    assert [i["stale_evidence"] for i in inspect_progress(repo, state)["items"]] == [True, True]


def test_service_runs_few_git_commands(tmp_path, monkeypatch):
    from drift_gate.desktop import progress_service as service

    repo = project(tmp_path)
    _origin(repo, "https://github.com/acme/shop.git")
    calls = []
    real = subprocess.run
    monkeypatch.setattr(service.subprocess, "run", lambda *a, **k: (calls.append(a[0][3:5]), real(*a, **k))[1])
    draft = extract_requirements(repo, ["README.md"])
    assert len(calls) <= 3  # toplevel + two ls-files
    calls.clear()
    save_baseline(repo, tmp_path / "state", draft)
    assert len(calls) <= 4  # + origin URL
    calls.clear()
    inspect_progress(repo, tmp_path / "state")
    assert len(calls) <= 3  # toplevel + origin URL + HEAD


def test_malformed_evidence_paths_are_reported_not_crashed(tmp_path):
    repo = project(tmp_path)
    draft = extract_requirements(repo, ["README.md"])
    draft["requirements"][0]["implementation_status"] = "implemented"
    draft["requirements"][0]["evidence"] = {"path": ["src/login.py"], "line": 1, "note": "x"}
    with pytest.raises(BaselineError) as raised:
        save_baseline(repo, tmp_path / "state", draft)
    assert raised.value.errors[0]["field"] == "evidence.path"


def _baseline_with_evidence(tmp_path):
    repo = project(tmp_path)
    (repo / "src/other.py").write_text("x = 1\n", encoding="utf-8")
    draft = extract_requirements(repo, ["README.md"])
    for item, name in zip(draft["requirements"], ("login.py", "other.py")):
        item["implementation_status"] = "implemented"
        item["evidence"] = {"path": f"src/{name}", "line": 1, "note": "확인"}
    save_baseline(repo, tmp_path / "state", draft)
    return repo, tmp_path / "state"


def test_scan_impact_lists_items_whose_evidence_file_is_in_the_change_set(tmp_path):
    repo, state = _baseline_with_evidence(tmp_path)
    (repo / "src/login.py").write_text("def login():\n    return 1\n", encoding="utf-8")
    impact = scan_impact(repo, state, [{"path": "src/login.py", "previous_path": None, "status": "modified"}])
    assert impact["version"] == 1 and impact["documents"] == []
    assert [(i["path"], i["change"], i["invalidated"]) for i in impact["items"]] == [
        ("src/login.py", "modified", True)
    ]
    assert impact["items"][0]["title"].startswith("로그인")


def test_scan_impact_distinguishes_unchanged_content_renames_and_deletions(tmp_path):
    repo, state = _baseline_with_evidence(tmp_path)
    same = scan_impact(repo, state, [{"path": "src/other.py", "previous_path": None, "status": "modified"}])
    assert [i["invalidated"] for i in same["items"]] == [False]  # file still matches the evidence
    (repo / "src/other.py").rename(repo / "src/renamed.py")
    moved = scan_impact(repo, state, [{"path": "src/renamed.py", "previous_path": "src/other.py", "status": "renamed"}])
    assert [(i["path"], i["change"], i["invalidated"]) for i in moved["items"]] == [("src/other.py", "renamed", True)]
    assert scan_impact(repo, state, [{"path": "src/unrelated.py", "previous_path": None, "status": "added"}])["items"] == []


def test_scan_impact_reports_changed_baseline_documents_and_ignores_excluded_items(tmp_path):
    repo, state = _baseline_with_evidence(tmp_path)
    baseline = load_baseline(repo, state)
    baseline["requirements"][0]["included"] = False
    save_baseline(repo, state, baseline)
    (repo / "README.md").write_text("# Service\n새 계획\n", encoding="utf-8")
    impact = scan_impact(repo, state, [
        {"path": "README.md", "previous_path": None, "status": "modified"},
        {"path": "src/login.py", "previous_path": None, "status": "modified"},
    ])
    assert impact["documents"] == [{"path": "README.md", "invalidated": True}]
    assert impact["items"] == []  # the login item is excluded from this scope


def test_scan_impact_is_none_without_a_saved_baseline(tmp_path):
    assert scan_impact(project(tmp_path), tmp_path / "state", []) is None


def _save_and_record(repo, state, draft):
    save_baseline(repo, state, draft)
    return record_snapshot(repo, state, inspect_progress(repo, state))


def test_history_records_each_save_and_shows_change_since_the_last_one(tmp_path):
    repo = project(tmp_path)
    state = tmp_path / "state"
    draft = extract_requirements(repo, ["README.md"])
    first = _save_and_record(repo, state, draft)
    assert [r["version"] for r in first["snapshots"]] == [1] and first["since_save"] is None
    draft = load_baseline(repo, state)

    draft["requirements"][0]["implementation_status"] = "implemented"
    draft["requirements"][0]["evidence"] = {"path": "src/login.py", "line": 1, "note": "확인"}
    second = _save_and_record(repo, state, draft)
    assert [r["version"] for r in second["snapshots"]] == [2, 1]
    assert second["snapshots"][0]["changes"]["gained"] == 1
    assert second["snapshots"][0]["counts"]["implemented"] == 1
    assert _save_and_record(repo, state, draft)["snapshots"] == second["snapshots"]  # unchanged: no new row

    (repo / "src/login.py").write_text("def login():\n    raise SystemExit\n", encoding="utf-8")
    view = progress_history_view(repo, state, inspect_progress(repo, state))
    since = view["since_save"]
    assert since["counts"]["regressed"] == 1 and since["regressed"][0]["title"].startswith("로그인")
    assert len(view["snapshots"]) == 2  # viewing never records


def test_history_survives_a_folder_move_and_ignores_a_damaged_file(tmp_path):
    repo = project(tmp_path)
    _origin(repo, "https://github.com/acme/shop.git")
    state = tmp_path / "state"
    _save_and_record(repo, state, extract_requirements(repo, ["README.md"]))
    moved = tmp_path / "moved"
    shutil.copytree(repo, moved)
    assert len(progress_history_view(moved, state)["snapshots"]) == 1
    history = next(state.glob("*.history.json"))
    history.write_text("{not json", encoding="utf-8")
    view = progress_history_view(moved, state)
    assert view["snapshots"] == [] and view["since_save"] is None
    assert view["warning"]


def test_history_kept_under_the_old_path_key_is_still_read_after_a_remote_is_added(tmp_path):
    repo = project(tmp_path)
    state = tmp_path / "state"
    _save_and_record(repo, state, extract_requirements(repo, ["README.md"]))  # no remote: path key
    _origin(repo, "https://github.com/acme/shop.git")
    assert len(progress_history_view(repo, state)["snapshots"]) == 1
    draft = load_baseline(repo, state)
    draft["requirements"][0]["included"] = False
    record = _save_and_record(repo, state, draft)
    assert [r["version"] for r in record["snapshots"]] == [2, 1]  # appended, then stored under the remote key
    assert len(list(state.glob("*.history.json"))) == 2


def test_report_flags_test_names_missing_from_the_repository_test_files(tmp_path):
    repo = project(tmp_path)
    (repo / "tests").mkdir()
    (repo / "tests/test_login.py").write_text("def test_login_flow():\n    pass\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "tests"], check=True)
    state = tmp_path / "state"
    draft = extract_requirements(repo, ["README.md"])
    draft = save_baseline(repo, state, draft)
    assert inspect_progress(repo, state)["test_pattern_hints"] == {}  # no patterns, nothing to check
    draft["requirements"][0]["test_patterns"] = ["test_login_flow", "test_logn_flow"]
    saved = save_baseline(repo, state, draft)
    hints = inspect_progress(repo, state)["test_pattern_hints"]
    assert hints == {saved["requirements"][0]["id"]: ["test_logn_flow"]}


def test_document_roles_extract_only_current_and_context_changes_keep_counts(tmp_path):
    repo = project(tmp_path)
    for name in ("future", "past", "reference"):
        (repo / f"{name}.md").write_text(f"- [x] {name} 전용 기능\n", encoding="utf-8")
    selected = [{"path": "README.md", "kind": "current"}] + [
        {"path": f"{kind}.md", "kind": kind} for kind in ("future", "past", "reference")
    ]
    draft = extract_requirements(repo, selected)
    assert len(draft["documents"]) == 4
    assert len(draft["requirements"]) == 2
    assert draft["document_kinds"]["past.md"] == "past"
    item = draft["requirements"][0]
    item.update(implementation_status="implemented", evidence={"path": "src/login.py", "line": 1, "note": "로그인 정의 확인"})
    state = tmp_path / "state"
    save_baseline(repo, state, draft)
    (repo / "past.md").write_text("- [x] 수정된 결과\n", encoding="utf-8")
    report = inspect_progress(repo, state)
    assert report["stale_documents"] == []
    assert report["stale_context_documents"] == ["past.md"]
    assert report["counts"]["implemented"] == 1 and report["total"] == 2
    (repo / "README.md").write_text("- [ ] 목표 변경\n", encoding="utf-8")
    assert inspect_progress(repo, state)["counts"]["implemented"] == 0


def test_role_changes_preserve_evidence_version_and_history(tmp_path):
    repo = project(tmp_path)
    state = tmp_path / "state"
    draft = extract_requirements(repo, ["README.md"])
    draft["requirements"][0].update(implementation_status="implemented", evidence={"path": "src/login.py", "line": 1, "note": "정의 확인"})
    saved = save_baseline(repo, state, draft)
    evidence = dict(saved["requirements"][0]["evidence"])
    record_snapshot(repo, state, inspect_progress(repo, state))
    saved["document_kinds"] = {"README.md": "past"}
    excluded = save_baseline(repo, state, saved)
    assert excluded["version"] == 2
    assert excluded["requirements"][0]["evidence"] == evidence
    report = inspect_progress(repo, state)
    assert report["total"] == 0 and report["counts"]["excluded"] == 2
    assert report["counts"]["implemented"] == 0
    history = record_snapshot(repo, state, report)
    assert history["snapshots"][0]["changes"]["excluded"] == 2
    assert history["snapshots"][0]["changes"]["regressed"] == 0
    assert save_baseline(repo, state, excluded)["version"] == 2
    excluded["document_kinds"]["README.md"] = "current"
    restored = save_baseline(repo, state, excluded)
    assert restored["version"] == 3
    assert inspect_progress(repo, state)["counts"]["implemented"] == 1


def test_legacy_baseline_defaults_to_current_without_version_bump(tmp_path):
    import json
    repo = project(tmp_path)
    state = tmp_path / "state"
    saved = save_baseline(repo, state, extract_requirements(repo, ["README.md"]))
    target = next(state.glob("*.json"))
    saved.pop("document_kinds")
    target.write_text(json.dumps(saved), encoding="utf-8")
    assert inspect_progress(repo, state)["total"] == 2
    saved["document_kinds"] = {"README.md": "current"}
    assert save_baseline(repo, state, saved)["version"] == 1


def test_only_context_selection_is_valid_and_has_no_current_goals(tmp_path):
    repo = project(tmp_path)
    draft = extract_requirements(repo, [{"path": "README.md", "kind": "reference"}])
    assert draft["requirements"] == []
    save_baseline(repo, tmp_path / "state", draft)
    report = inspect_progress(repo, tmp_path / "state")
    assert report["total"] == 0
    assert sum(report["counts"].values()) == 0


@pytest.mark.parametrize("selected", [
    [{"path": "README.md", "kind": "guess"}],
    [{"path": ["README.md"], "kind": "current"}],
    [{"path": "README.md", "kind": []}],
    ["README.md", {"path": "README.md", "kind": "past"}],
])
def test_invalid_document_roles_are_rejected_cleanly(tmp_path, selected):
    with pytest.raises(ValueError):
        extract_requirements(project(tmp_path), selected)


def test_remaining_current_duplicate_keeps_goal_in_scope(tmp_path):
    repo = project(tmp_path)
    (repo / "goals.md").write_text((repo / "README.md").read_text(encoding="utf-8"), encoding="utf-8")
    draft = extract_requirements(repo, ["README.md", "goals.md"])
    assert len(draft["requirements"]) == 2
    draft["document_kinds"]["README.md"] = "past"
    save_baseline(repo, tmp_path / "state", draft)
    assert inspect_progress(repo, tmp_path / "state")["total"] == 2


def test_save_rejects_unknown_or_unselected_document_roles(tmp_path):
    repo = project(tmp_path)
    draft = extract_requirements(repo, ["README.md"])
    for kinds in ({"README.md": "wrong"}, {"missing.md": "past"}, []):
        draft["document_kinds"] = kinds
        with pytest.raises(ValueError):
            save_baseline(repo, tmp_path / "state", draft)


def test_review_impact_does_not_claim_context_evidence_changes_affect_counts(tmp_path):
    repo, state = _baseline_with_evidence(tmp_path)
    baseline = load_baseline(repo, state)
    baseline['document_kinds'] = {'README.md': 'past'}
    save_baseline(repo, state, baseline)
    (repo / 'README.md').write_text('# 과거 결과 변경\n', encoding='utf-8')
    (repo / 'src/login.py').write_text('def login():\n    return False\n', encoding='utf-8')
    impact = scan_impact(repo, state, [
        {'path': 'README.md', 'status': 'modified'}, {'path': 'src/login.py', 'status': 'modified'},
    ])
    assert impact['items'] == []
    assert impact['documents'] == [{'path': 'README.md', 'invalidated': True, 'kind': 'past'}]


def test_merged_reextraction_adds_past_goals_without_losing_evidence_or_history(tmp_path):
    repo = project(tmp_path)
    state = tmp_path / "state"
    (repo / "past.md").write_text("- [ ] 알림 기능\n", encoding="utf-8")
    draft = extract_requirements(repo, ["README.md", {"path": "past.md", "kind": "past"}])
    item = draft["requirements"][0]
    item.update(implementation_status="implemented",
                evidence={"path": "src/login.py", "line": 1, "note": "확인"},
                verification_status="verified", verification_note="직접 검증")
    saved = save_baseline(repo, state, draft)
    record_snapshot(repo, state, inspect_progress(repo, state))
    old = deepcopy(saved["requirements"])
    preview = extract_requirements(repo, ["README.md", "past.md"])
    preview["requirements"] = old + [entry for entry in preview["requirements"]
                                    if entry["id"] not in {i["id"] for i in old}]
    preview["version"] = saved["version"]
    preview["baseline_id"] = saved["baseline_id"]
    merged = save_baseline(repo, state, preview)
    assert merged["requirements"][:2] == old
    assert merged["version"] == 2
    report = inspect_progress(repo, state)
    assert report["total"] == 3 and report["counts"]["complete"] == 1
    changes = record_snapshot(repo, state, report)["snapshots"][0]["changes"]
    assert changes["added"] == 1 and changes.get("regressed", 0) == 0
    assert save_baseline(repo, state, deepcopy(merged))["version"] == 2


def test_saving_retained_evidence_does_not_refresh_changed_code_without_review(tmp_path):
    repo = project(tmp_path)
    state = tmp_path / "state"
    draft = extract_requirements(repo, ["README.md"])
    draft["requirements"][0].update(implementation_status="implemented",
        evidence={"path": "src/login.py", "line": 1, "note": "확인"},
        verification_status="verified", verification_note="직접 검증")
    saved = save_baseline(repo, state, draft)
    old_evidence = deepcopy(saved["requirements"][0]["evidence"])
    (repo / "src/login.py").write_text("def login():\n    return False\n", encoding="utf-8")
    saved["requirements"][1]["title"] = "편집된 제목"
    retained = save_baseline(repo, state, saved)
    assert retained["requirements"][0]["evidence"] == old_evidence
    report = inspect_progress(repo, state)
    assert report["counts"]["complete"] == 0
    assert report["items"][0]["stale_evidence"]
    # Editing/reviewing evidence explicitly requests a fresh snapshot.
    retained["requirements"][0]["evidence"].pop("sha256")
    refreshed = save_baseline(repo, state, retained)
    assert refreshed["requirements"][0]["evidence"]["sha256"] != old_evidence["sha256"]


def test_reextracted_document_preserves_review_but_requires_explicit_reconfirmation(tmp_path):
    repo = project(tmp_path)
    state = tmp_path / "state"
    draft = extract_requirements(repo, ["README.md"])
    draft["requirements"][0].update(implementation_status="implemented",
        evidence={"path": "src/login.py", "line": 1, "note": "확인"},
        verification_status="verified", verification_note="검증 기록")
    saved = save_baseline(repo, state, draft)
    (repo / "README.md").write_text((repo / "README.md").read_text(encoding="utf-8") + "설명 변경\n", encoding="utf-8")
    preview = extract_requirements(repo, ["README.md"])
    fresh = {item["id"]: item for item in preview["requirements"]}
    preview["requirements"] = deepcopy(saved["requirements"])
    for item in preview["requirements"]:
        item["source"] = fresh[item["id"]]["source"]
        item["reviewed_documents"] = saved["documents"]
    preview["version"] = saved["version"]
    preview["baseline_id"] = saved["baseline_id"]
    merged = save_baseline(repo, state, preview)
    assert merged["requirements"][0]["verification_note"] == "검증 기록"
    assert inspect_progress(repo, state)["counts"]["complete"] == 0
    assert inspect_progress(repo, state)["items"][0]["stale_requirement"]
    from drift_gate.desktop.progress_report import render_markdown
    assert "재확인 필요" in render_markdown(inspect_progress(repo, state))
    merged["requirements"][0]["reviewed_documents"] = merged["documents"]
    save_baseline(repo, state, merged)
    assert inspect_progress(repo, state)["counts"]["complete"] == 1


def test_retained_removed_source_is_not_dropped_or_counted_as_reviewed(tmp_path):
    repo = project(tmp_path)
    state = tmp_path / "state"
    draft = extract_requirements(repo, ["README.md"])
    draft["requirements"][0].update(implementation_status="not_implemented", implementation_note="확인 기록")
    saved = save_baseline(repo, state, draft)
    (repo / "README.md").write_text("# 새 계획\n- [ ] 새 기능\n", encoding="utf-8")
    preview = extract_requirements(repo, ["README.md"])
    preview["requirements"] = deepcopy(saved["requirements"]) + preview["requirements"]
    preview["version"] = saved["version"]
    preview["baseline_id"] = saved["baseline_id"]
    merged = save_baseline(repo, state, preview)
    report = inspect_progress(repo, state)
    assert len(merged["requirements"]) == 3
    assert report["items"][0]["implementation_note"] == "확인 기록"
    assert report["items"][0]["stale_requirement"]
    assert report["counts"]["not_implemented"] == 0
    # A forged/stale source on a new item is still rejected.
    merged["requirements"][-1]["source"]["line"] = 999
    with pytest.raises(BaselineError):
        save_baseline(repo, state, merged)


def test_document_marker_keeps_identity_across_line_and_title_changes(tmp_path):
    repo = project(tmp_path)
    (repo / "README.md").write_text("- [ ] 로그인 <!-- progress-id: login -->\n", encoding="utf-8")
    first = extract_requirements(repo, ["README.md"])["requirements"][0]
    assert first["title"] == "로그인"
    assert first["source_key"] == "README.md:login"
    (repo / "README.md").write_text("# 새 제목\n\n- [ ] 회원 로그인 <!-- progress-id: login -->\n", encoding="utf-8")
    second = extract_requirements(repo, ["README.md"])["requirements"][0]
    assert first["id"] == second["id"]
    assert second["title"] == "회원 로그인"
    assert second["source"]["line"] == 3
    assert save_baseline(repo, tmp_path / "data", extract_requirements(repo, ["README.md"]))["requirements"][0]["source_key"] == second["source_key"]


@pytest.mark.parametrize("content", [
    "- [ ] 첫 기능 <!-- progress-id: duplicate -->\n- [ ] 다른 기능 <!-- progress-id: duplicate -->\n",
    "- [ ] 기능 <!-- progress-id: first --> <!-- progress-id: second -->\n",
])
def test_duplicate_or_multiple_document_markers_are_rejected(tmp_path, content):
    repo = project(tmp_path)
    (repo / "README.md").write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="progress-id"):
        extract_requirements(repo, ["README.md"])


def test_document_marker_cannot_be_changed_without_its_source(tmp_path):
    repo = project(tmp_path)
    (repo / "README.md").write_text("- [ ] 로그인 <!-- progress-id: login -->\n", encoding="utf-8")
    draft = extract_requirements(repo, ["README.md"])
    draft["requirements"][0]["source_key"] = "README.md:different"
    with pytest.raises(BaselineError, match="고유 표시"):
        save_baseline(repo, tmp_path / "data", draft)


def test_document_withdrawal_preserves_evidence_and_unblocks_renamed_document(tmp_path):
    repo = project(tmp_path)
    data = tmp_path / 'data'
    draft = extract_requirements(repo, ['README.md'])
    draft['requirements'][0].update(implementation_status='implemented',
        evidence={'path':'src/login.py','line':1,'note':'확인'}, verification_status='verified', verification_note='검증')
    saved = save_baseline(repo, data, draft)
    original = deepcopy(saved['requirements'])
    (repo / 'README.md').rename(repo / 'PLAN.md')
    with pytest.raises(ValueError, match='문서가 변경'):
        save_baseline(repo, data, saved)
    withdrawn = deepcopy(saved)
    withdrawn['archived_documents'] = ['README.md']
    withdrawn['requirements'][1]['title'] = '다른 편집 계속'
    kept = save_baseline(repo, data, withdrawn)
    assert kept['requirements'][0] == original[0]
    assert kept['document_kinds']['README.md'] == 'reference'
    assert inspect_progress(repo, data)['counts']['excluded'] == 2
    preview = extract_requirements(repo, ['PLAN.md'])
    merged = {**kept, 'documents':{**kept['documents'], **preview['documents']},
        'document_kinds':{**kept['document_kinds'], **preview['document_kinds']},
        'requirements':kept['requirements'] + preview['requirements']}
    latest = save_baseline(repo, data, merged)
    report = inspect_progress(repo, data)
    assert latest['version'] == 3 and report['total'] == 2
    assert report['counts']['excluded'] == 2 and not report['stale_documents']
    assert latest['requirements'][0]['evidence'] == original[0]['evidence']


def test_archive_requires_retained_original_hash_and_can_be_reactivated(tmp_path):
    repo = project(tmp_path)
    data = tmp_path / 'data'
    saved = save_baseline(repo, data, extract_requirements(repo, ['README.md']))
    invalid = deepcopy(saved)
    invalid.update(archived_documents=['README.md'], documents={'README.md':'forged'})
    with pytest.raises(ValueError, match='원본 정보'):
        save_baseline(repo, data, invalid)
    saved['archived_documents'] = ['README.md']
    archived = save_baseline(repo, data, saved)
    archived['archived_documents'] = []
    archived['document_kinds']['README.md'] = 'current'
    latest = save_baseline(repo, data, archived)
    assert latest['version'] == 3 and inspect_progress(repo, data)['total'] == 2


def test_recreated_same_version_baseline_rejects_old_editor_and_preserves_new_edits(tmp_path):
    from drift_gate.desktop.progress_service import BaselineConflict
    repo = project(tmp_path)
    data = tmp_path / 'data'
    old = save_baseline(repo, data, extract_requirements(repo, ['README.md']))
    next(data.glob('*.json')).unlink()
    replacement = extract_requirements(repo, ['README.md'])
    replacement['requirements'][1]['title'] = '새 기준의 독립 편집'
    current = save_baseline(repo, data, replacement)
    old['requirements'][0]['title'] = '오래된 창의 편집'
    assert old['version'] == current['version'] == 1
    with pytest.raises(BaselineConflict):
        save_baseline(repo, data, old)
    assert load_baseline(repo, data) == current
    assert save_baseline(repo, data, deepcopy(current)) == current


def test_missing_baseline_and_legacy_numeric_only_edit_never_overwrite(tmp_path):
    from drift_gate.desktop.progress_service import BaselineConflict
    repo = project(tmp_path)
    data = tmp_path / 'data'
    saved = save_baseline(repo, data, extract_requirements(repo, ['README.md']))
    legacy = deepcopy(saved)
    legacy.pop('baseline_id')
    legacy['requirements'][0]['title'] = '복구 편집'
    with pytest.raises(BaselineConflict): save_baseline(repo, data, legacy)
    legacy['edit_base'] = deepcopy(saved)
    assert save_baseline(repo, data, legacy)['version'] == 2
    next(data.glob('*.json')).unlink()
    with pytest.raises(ValueError, match='사라졌습니다'):
        save_baseline(repo, data, legacy)
    assert load_baseline(repo, data) is None


@pytest.mark.parametrize('content', ['{not json', '[]', 'null', '{"schema":1,"snapshots":[{}]}',
    '{"schema":1,"snapshots":[{"at":null}]}'])
def test_bad_optional_history_is_visible_and_never_overwritten(tmp_path, content):
    from drift_gate.desktop.progress_history import HistoryError
    repo = project(tmp_path)
    data = tmp_path / 'data'
    save_baseline(repo, data, extract_requirements(repo, ['README.md']))
    report = inspect_progress(repo, data)
    history = next(data.glob('*.json')).with_suffix('.history.json')
    history.write_text(content, encoding='utf-8')
    view = progress_history_view(repo, data, report)
    assert view['warning'] and view['snapshots'] == [] and view['since_save'] is None
    with pytest.raises(HistoryError): record_snapshot(repo, data, report)
    assert history.read_text(encoding='utf-8') == content


def test_history_anchor_is_immutable_across_same_version_concurrent_write(tmp_path):
    from drift_gate.desktop.progress_service import capture_progress_history
    repo = project(tmp_path)
    data = tmp_path / 'data'
    save_baseline(repo, data, extract_requirements(repo, ['README.md']))
    before = inspect_progress(repo, data)
    record_snapshot(repo, data, before)
    anchor = capture_progress_history(repo, data)
    future = deepcopy(before)
    future['at'] = '2099-01-01T00:00:00Z'
    future['items'][0]['effective_status'] = 'implemented'
    future['counts']['implemented'] = 1
    future['counts']['unknown'] -= 1
    record_snapshot(repo, data, future)
    result = progress_history_view(repo, data, before, anchor=anchor)
    assert len(result['snapshots']) == 1 and result['since_save'] is None
    assert len(progress_history_view(repo, data)['snapshots']) == 2
    assert progress_history_view(repo, data, before)['since_save'] is None


def test_archived_document_does_not_consume_an_active_binding_slot(tmp_path):
    repo = project(tmp_path)
    data = tmp_path / 'data'
    paths = ['README.md']
    for n in range(9):
        path = f'plan{n}.md'
        paths.append(path)
        (repo / path).write_text(f'- [ ] 기능 {n}\n', encoding='utf-8')
    saved = save_baseline(repo, data, extract_requirements(repo, paths))
    (repo / 'README.md').rename(repo / 'RENAMED.md')
    preview = extract_requirements(repo, ['RENAMED.md'])
    candidate = {**saved, 'archived_documents':['README.md'],
        'documents':{**saved['documents'], **preview['documents']},
        'document_kinds':{**saved['document_kinds'], **preview['document_kinds']},
        'requirements':saved['requirements'] + preview['requirements']}
    latest = save_baseline(repo, data, candidate)
    assert len(latest['documents']) == 11 and latest['archived_documents'] == ['README.md']
    assert inspect_progress(repo, data)['total'] == len(saved['requirements'])
