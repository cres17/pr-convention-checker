"""Only definite broken links and paths are reported; examples and URLs are not."""

import subprocess

import pytest

from drift_gate.desktop.doc_links import find_broken_references
from drift_gate.desktop.progress_service import (
    check_references,
    extract_requirements,
    save_baseline,
)


def files_of(*names):
    return set(names)


def check(tmp_path, document, text, *names):
    for name in names:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x\n", encoding="utf-8")
    return find_broken_references(document, text.splitlines(), tmp_path, set(names))


def test_relative_links_resolve_from_the_document_folder(tmp_path):
    checked, issues = check(
        tmp_path, "docs/guide.md",
        "[ok](api.md) [up](../README.md) [root](/src/app.py) [dir](../src) "
        "![img](assets/a.png) [gone](missing.md) [out](../../x.md)",
        "docs/api.md", "README.md", "src/app.py", "docs/assets/a.png",
    )
    assert checked == 7
    assert {i["confidence"] for i in issues} == {"high"}
    assert [(i["target"], i["message"]) for i in issues] == [
        ("missing.md", "대상을 찾을 수 없습니다"),
        ("../../x.md", "저장소 밖을 가리킵니다"),
    ]


def test_urls_anchors_and_mail_links_are_not_checked(tmp_path):
    checked, issues = check(
        tmp_path, "README.md",
        "[a](https://example.com/x.md) [b](#section) [c](mailto:a@b.c) [d](docs/api.md#top) [e](docs/api.md?x=1)",
        "docs/api.md",
    )
    assert issues == [] and checked == 2


def test_code_blocks_and_placeholder_paths_are_ignored(tmp_path):
    text = (
        "```md\n[x](nope.md) `src/nope.py`\n```\n"
        "`src/<name>.py` `src/*.py` `github.com/o/r.git` `not a path` `dist.zip` `--flag/x.py`"
    )
    assert check(tmp_path, "README.md", text) == (0, [])


def test_backtick_path_is_accepted_from_repository_root_or_document_folder(tmp_path):
    checked, issues = check(
        tmp_path, "docs/guide.md",
        "`src/app.py` `sibling/notes.md` `src/missing.py`",
        "src/app.py", "docs/sibling/notes.md",
    )
    assert checked == 3
    assert [(i["target"], i["kind"], i["confidence"]) for i in issues] == [
        ("src/missing.py", "path", "low")
    ]


def test_partial_path_naming_the_tail_of_a_repository_file_is_not_reported(tmp_path):
    _, issues = check(
        tmp_path, "docs/roadmap.md",
        "`core/evaluation/evaluator.py` `evaluation/other.py`",
        "pkg/core/evaluation/evaluator.py",
    )
    assert [i["target"] for i in issues] == ["evaluation/other.py"]


def test_case_mismatch_and_gitignored_files(tmp_path):
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist/out.js").write_text("x", encoding="utf-8")  # exists, not tracked
    _, issues = check(
        tmp_path, "README.md", "[a](Docs/API.md) [b](dist/out.js)", "docs/api.md"
    )
    assert [i["message"] for i in issues] == ["대소문자가 다릅니다: docs/api.md"]


def test_reference_style_links_are_checked(tmp_path):
    _, issues = check(tmp_path, "README.md", "[guide]: docs/guide.md\n[skip]: https://e.com", "docs/other.md")
    assert [i["target"] for i in issues] == ["docs/guide.md"]


def test_check_references_reads_the_saved_baseline_documents(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "README.md").write_text(
        "# S\n- [ ] 로그인 `src/login.py`\n[가이드](docs/gone.md)\n", encoding="utf-8"
    )
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    state = tmp_path / "state"
    with pytest.raises(ValueError):
        check_references(repo, state)
    save_baseline(repo, state, extract_requirements(repo, ["README.md"]))
    result = check_references(repo, state)
    assert result["documents"] == ["README.md"]
    assert {(i["line"], i["target"], i["kind"]) for i in result["issues"]} == {
        (2, "src/login.py", "path"), (3, "docs/gone.md", "link"),
    }
    assert result["checked"] == 2
