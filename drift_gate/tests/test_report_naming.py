"""Report filenames follow the selected project, branch and version."""
import subprocess
from datetime import datetime

from drift_gate.adapters.report_naming import (
    ProjectIdentity, default_report_path, detect_project, report_filename, template_from_policy,
)

NOW = datetime(2026, 9, 29, 17, 30, 12)


def _repo(path, name="shop-api"):
    repo = path / name
    repo.mkdir()
    for args in (["init", "-q", "-b", "ver2"], ["config", "user.email", "t@example.com"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    return repo


def _commit(repo):
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)


def test_default_name_contains_project_branch_version_kind_and_time():
    identity = ProjectIdentity("shop-api", "v1.2.0", "ver2", "abc1234")
    assert report_filename(identity, "drift-report", "html", now=NOW) == \
        "shop-api_ver2_v1.2.0_drift-report_20260929-173012.html"


def test_different_projects_and_versions_do_not_collide():
    names = {
        report_filename(ProjectIdentity(p, v, "main"), "drift-report", "json", now=NOW)
        for p in ("shop-api", "admin-web") for v in ("v1.0.0", "v2.0.0")
    }
    assert len(names) == 4


def test_empty_segments_are_dropped_with_their_separator():
    name = report_filename(ProjectIdentity("shop-api"), "drift-report", "json", now=NOW)
    assert name == "shop-api_drift-report_20260929-173012.json"


def test_unsafe_characters_are_replaced_and_korean_is_kept():
    identity = ProjectIdentity('내 프로젝트:<test>', "v1/2", "feature/login")
    name = report_filename(identity, "drift-report", "html", now=NOW)
    assert name == "내-프로젝트-test_feature-login_v1-2_drift-report_20260929-173012.html"
    assert not set('<>:"/\\|?*') & set(name)


def test_custom_template_and_invalid_template_fallback():
    identity = ProjectIdentity("shop-api", "v1.0.0", "main", "abc1234")
    assert report_filename(identity, "drift-report", "md", "{project}-{version}-{commit}", NOW) == \
        "shop-api-v1.0.0-abc1234.md"
    for bad in ("{project.__class__}", "{unknown}", "{project!r}", "{project:>9}", "no-fields", "{"):
        assert report_filename(identity, "drift-report", "md", bad, NOW) == \
            "shop-api_main_v1.0.0_drift-report_20260929-173012.md"


def test_windows_reserved_names_are_prefixed():
    assert report_filename(ProjectIdentity("con"), "x", "json", "{project}", NOW) == "report_con.json"


def test_template_from_policy_reads_report_filename_only():
    assert template_from_policy('rules: []\nreport:\n  filename: "{project}-{kind}"\n') == "{project}-{kind}"
    assert template_from_policy("rules: []\n") is None
    assert template_from_policy("report: [broken") is None
    assert template_from_policy("report:\n  filename: 3\n") is None


def test_detect_project_prefers_exact_tag_over_manifest(tmp_path):
    repo = _repo(tmp_path)
    (repo / "package.json").write_text('{"name": "x", "version": "0.4.1"}', encoding="utf-8")
    _commit(repo)
    identity = detect_project(repo)
    assert (identity.name, identity.branch, identity.version) == ("shop-api", "ver2", "v0.4.1")
    assert identity.commit
    subprocess.run(["git", "-C", str(repo), "tag", "release-7"], check=True)
    assert detect_project(repo).version == "release-7"


def test_detect_project_reads_pyproject_and_tolerates_missing_manifest(tmp_path):
    repo = _repo(tmp_path, "tool")
    (repo / "pyproject.toml").write_text(
        '[build-system]\nversion = "9"\n[project]\nname = "tool"\nversion = "2.3.0"\n', encoding="utf-8")
    _commit(repo)
    assert detect_project(repo).version == "v2.3.0"
    bare = _repo(tmp_path, "bare")
    assert detect_project(bare) == ProjectIdentity("bare", "", "ver2", "")


def test_default_report_path_uses_repository_folder_and_policy_template(tmp_path):
    repo = _repo(tmp_path)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    path = default_report_path(repo, "drift-report", "json", 'report:\n  filename: "{project}-{branch}-{kind}"\n')
    assert path == repo / "shop-api-ver2-drift-report.json"
