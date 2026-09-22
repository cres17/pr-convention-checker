"""Regression and negative-control checks for the recorded development gaps."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from drift_gate.adapters.ast.analyzer import enrich_semantic_signals
from drift_gate.adapters.docs.content import attach_env_documents, local_document_reader
from drift_gate.adapters.github.approvals import _owners, verify_ignores
from drift_gate.adapters.github.client import GitHubAdapter, parse_drift_ignores
from drift_gate.core.engine import run
from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.policy import Policy
from drift_gate.core.models.result import DriftIgnoreDirective
from drift_gate.core.policy.loader import load_policy_from_dict, PolicyLoadError

ROOT = Path(__file__).resolve().parents[2]
SUITE = json.loads((ROOT / "docs/assessment/challenge-v1.json").read_text())
ENV_SUITE = json.loads((ROOT / "docs/assessment/env-contract-v1.json").read_text())


@pytest.mark.parametrize("case", ENV_SUITE["cases"], ids=lambda c: c["id"])
def test_frozen_environment_content_cases(case):
    result = run([ChangedFile.from_dict(f) for f in case["changed_files"]],
                 policy=Policy.from_dict(ENV_SUITE["policy"]))
    assert result.result == case["expected"]


@pytest.mark.parametrize("case", SUITE["cases"], ids=lambda c: c["id"])
def test_frozen_challenge(case):
    result = run(enrich_semantic_signals([ChangedFile.from_dict(f) for f in case["changed_files"]]),
                 policy=Policy.from_dict(SUITE["policies"][case["policy"]]),
                 drift_ignores=parse_drift_ignores(case.get("pr_body", "")))
    assert result.result == case["expected"]


def api_policy(**suppression):
    return Policy.from_dict({**SUITE["policies"]["api"], "suppression": suppression})


def route_file(**kwargs):
    return ChangedFile(path="src/routes/users.py", status="modified",
                       patch="-@app.get('/users')\n+@app.get('/members')\n", **kwargs)


@pytest.mark.parametrize("patch", ["", "[large file skipped]", "[binary file skipped]"])
def test_unavailable_patch_cannot_be_satisfied_by_unrelated_docs(patch):
    files = [ChangedFile(path="src/routes/users.py", status="modified", patch=patch),
             ChangedFile(path="docs/api/users.md", status="modified", patch="+irrelevant\n")]
    result = run(enrich_semantic_signals(files), policy=api_policy())
    assert result.result == "fail"
    assert any(g.type == "analysis" for g in result.violations[0].unsatisfied_groups)


def test_grammar_failure_is_visible_without_changing_rule_result(monkeypatch):
    import drift_gate.adapters.ast.analyzer as analyzer
    monkeypatch.setattr(analyzer, "parse_sexp", lambda *args: (_ for _ in ()).throw(RuntimeError("offline")))
    file = analyzer.enrich_semantic_signals([route_file()])[0]
    assert file.analysis_method == "heuristic"
    assert "RuntimeError" in file.analysis_reason
    result = run([file], policy=api_policy())
    assert result.result == "fail"
    assert result.to_dict()["scan_metrics"]["analysis_notes"][0]["method"] == "heuristic"


def test_valid_grammar_status_and_unicode():
    file = ChangedFile(path="a.py", status="modified", patch="+def 인사():\n+    return '안녕'\n")
    enriched = enrich_semantic_signals([file])[0]
    assert enriched.analysis_method == "grammar+heuristic"
    assert "function-signature-changed" in enriched.semantic_signals


def test_partial_patch_reports_recovery():
    file = ChangedFile(path="a.py", status="modified", patch="+def invalid(\n")
    assert enrich_semantic_signals([file])[0].analysis_method == "heuristic"


def test_deleted_route_without_enrichment_still_triggers():
    file = ChangedFile(path="src/routes/users.py", status="deleted", patch="-@app.get('/users')\n")
    assert run([file], policy=api_policy()).result == "fail"


def test_comment_containing_route_does_not_trigger():
    file = ChangedFile(path="src/routes/users.py", status="modified", patch="+# @app.get('/fake')\n")
    assert run(enrich_semantic_signals([file]), policy=api_policy()).result == "pass"


def test_endpoint_method_and_removal_must_be_documented():
    files = [route_file(), ChangedFile(path="docs/api/users.md", status="modified", patch="+POST /members\n")]
    assert run(enrich_semantic_signals(files), policy=api_policy()).result == "fail"
    files[1].patch = "+GET /members\n"
    assert run(enrich_semantic_signals(files), policy=api_policy()).result == "fail"
    files[1].patch = "-GET /users\n+GET /members\n"
    assert run(enrich_semantic_signals(files), policy=api_policy()).result == "pass"


def test_path_only_compatibility_mode():
    policy = api_policy()
    policy.rules[0].require.groups[0].content = "paths"
    files = [route_file(), ChangedFile(path="docs/api/payments.md", status="modified", patch="+typo fix\n")]
    assert run(enrich_semantic_signals(files), policy=policy).result == "pass"


def test_ignore_directives_do_not_borrow_reason_or_expiry():
    parsed = parse_drift_ignores("drift-ignore: first\ndrift-ignore: second\nreason: second only\nexpires: not-a-date")
    assert parsed[0].reason is None and parsed[0].expires is None
    assert parsed[1].expires == "not-a-date"
    policy = api_policy()
    parsed[1].rule_id = "api-doc"
    assert run([route_file()], policy=policy, drift_ignores=[parsed[1]]).rejected_ignores


def test_json_cannot_supply_approval_proof():
    directive = DriftIgnoreDirective.from_dict({"rule_id": "api-doc", "reason": "test", "approved_by": "owner",
                                                "approval_verified": True, "approval_commit": "head"})
    assert not directive.approval_verified
    assert run([route_file()], policy=api_policy(require_codeowners_approval=True), drift_ignores=[directive]).result == "fail"


class FakeGitHub:
    _base = "https://api.github.com"
    _repo = "owner/repo"
    _snapshot_head = "head"

    def __init__(self, *, reviews=None, owners="/src/routes/** @reviewer", error=False, move=False):
        self.owners, self.error, self.move, self.reads = owners, error, move, 0
        self.reviews = reviews if reviews is not None else [review("reviewer", "APPROVED")]

    def _get(self, url):
        if self.error:
            raise OSError("network unavailable")
        if "/reviews?" in url:
            return self.reviews
        if "/memberships/" in url:
            return {"state": "active"}
        if "/permission" in url:
            return {"permission": "write"}
        if "/teams/" in url and "/repos/" in url:
            return {"permissions": {"push": True}}
        self.reads += 1
        return {"head": {"sha": "new-head" if self.move and self.reads > 1 else "head"},
                "base": {"sha": "base"}, "user": {"login": "author"}}

    def get_file_text(self, path, ref):
        assert ref == "base"
        return self.owners if path == ".github/CODEOWNERS" else None


def review(login, state, *, commit="head", index=1):
    return {"user": {"login": login}, "state": state, "commit_id": commit,
            "submitted_at": f"2026-09-22T00:00:{index:02d}Z", "id": index}


def verify(fake):
    policy = api_policy(require_codeowners_approval=True)
    directives = parse_drift_ignores("drift-ignore: api-doc\nreason: maintenance\napproved-by: arbitrary-text")
    directives = verify_ignores(fake, 1, directives, policy, [route_file()])
    return run([route_file()], policy=policy, drift_ignores=directives)


def test_current_codeowner_approval_allows_exception():
    result = verify(FakeGitHub())
    assert result.result == "pass"
    assert result.ignore_audit[0].approved_by == "reviewer"
    assert result.ignore_audit[0].approval_commit == "head"


@pytest.mark.parametrize("fake", [
    FakeGitHub(reviews=[]), FakeGitHub(error=True), FakeGitHub(move=True),
    FakeGitHub(owners="/other/** @reviewer"), FakeGitHub(owners="* @reviewer\n/src/routes/**"),
    FakeGitHub(reviews=[review("outsider", "APPROVED")]),
    FakeGitHub(reviews=[review("reviewer", "APPROVED", commit="old-head")]),
    FakeGitHub(reviews=[review("reviewer", "APPROVED"), review("reviewer", "DISMISSED", index=2)]),
    FakeGitHub(reviews=[review("reviewer", "APPROVED"), review("reviewer", "CHANGES_REQUESTED", index=2)]),
    FakeGitHub(owners="* @author", reviews=[review("author", "APPROVED")]),
    FakeGitHub(owners="[invalid] @reviewer"),
])
def test_unverified_or_stale_approvals_do_not_bypass(fake):
    assert verify(fake).result == "fail"


def test_later_comment_does_not_cancel_valid_approval():
    fake = FakeGitHub(reviews=[review("reviewer", "APPROVED"), review("reviewer", "COMMENTED", index=2)])
    assert verify(fake).result == "pass"


def test_team_membership_approval_and_failure():
    fake = FakeGitHub(owners="* @org/team")
    assert verify(fake).result == "pass"
    original = fake._get
    fake._get = lambda url: {"state": "pending"} if "/memberships/" in url else original(url)
    assert verify(fake).result == "fail"


def test_codeowner_last_match_and_directory_rules():
    assert _owners("*.py @python\n/src/routes/ @api", "src/routes/users.py") == ["@api"]
    assert _owners("/docs/ @root", "a/docs/info.md") == []
    assert _owners("*.py @python", "src/main.py") == ["@python"]
    assert _owners("docs/* @docs", "docs/nested/a.md") == []
    assert _owners("docs/* @docs", "docs/a.md") == ["@docs"]
    assert _owners("apps/ @apps", "nested/apps/a.py") == ["@apps"]
    assert _owners("**/logs @logs", "nested/logs/a.txt") == ["@logs"]


def test_codeowner_without_write_access_is_not_eligible():
    fake = FakeGitHub()
    original = fake._get
    fake._get = lambda url: {"permission": "read"} if "/permission" in url else original(url)
    assert verify(fake).result == "fail"


def test_collection_rejects_pr_moving_during_pagination(monkeypatch):
    gh = GitHubAdapter("fake", "owner/repo")
    states = iter([{"head": {"sha": "one"}, "base": {"sha": "base"}},
                   {"head": {"sha": "two"}, "base": {"sha": "base"}}])
    monkeypatch.setattr(gh, "_get", lambda url: next(states))
    monkeypatch.setattr(gh, "get_pr_files", lambda number: [])
    with pytest.raises(RuntimeError, match="changed"):
        gh.get_pr_files_and_body(1)


def env_policy():
    return Policy.from_dict({"rules": [{"id": "env-sync", "when": {"any_changed": ["src/config/**"],
                              "min_change_intensity": "config-key-added"},
             "require": {"groups": [{"name": "sample", "all_changed": [".env.example"], "content": "env-keys"}]},
             "severity": "blocker"}]})


def test_unchanged_sample_is_checked_and_values_are_not_retained(tmp_path):
    (tmp_path / ".env.example").write_text("PAYMENT_TIMEOUT=private-value\n")
    files = [ChangedFile(path="src/config/pay.py", status="modified", patch="+timeout = os.getenv('PAYMENT_TIMEOUT')\n")]
    policy = env_policy()
    enriched = attach_env_documents(files, policy, local_document_reader(tmp_path))
    assert enriched[-1].status == "unchanged"
    assert enriched[-1].documented_env_keys == ["PAYMENT_TIMEOUT"]
    result = run(enrich_semantic_signals(enriched), policy=policy)
    assert result.result == "pass"
    assert "private-value" not in json.dumps(result.to_dict())
    (tmp_path / ".env.example").write_text("OTHER_KEY=value\n")
    assert run(attach_env_documents(files, policy, local_document_reader(tmp_path)), policy=policy).result == "fail"


@pytest.mark.parametrize("path", ["../outside", "/etc/passwd", "config/*.env"])
def test_env_document_policy_requires_safe_explicit_paths(path):
    data = {"rules": [{"id": "env", "when": {"any_changed": ["src/**"]}, "require": {"groups": [
        {"name": "sample", "all_changed": [path], "content": "env-keys"}]}}]}
    with pytest.raises(PolicyLoadError):
        load_policy_from_dict(data)


@pytest.mark.parametrize("sample,expected", [("PAYMENT_TIMEOUT=example\n", "pass"), ("OTHER=example\n", "fail")])
def test_cli_reads_unchanged_sample_from_working_tree(tmp_path, sample, expected):
    (tmp_path / "src/config").mkdir(parents=True)
    (tmp_path / "src/config/pay.py").write_text("timeout = 30\n")
    (tmp_path / ".env.example").write_text(sample)
    (tmp_path / ".drift-gate.yml").write_text(json.dumps(ENV_SUITE["policy"]))
    for args in (["init", "-q"], ["add", "."], ["-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"]):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "src/config/pay.py").write_text("timeout = os.getenv('PAYMENT_TIMEOUT')\n")
    # The CLI writes UTF-8 bytes, regardless of the host's default encoding.
    result = subprocess.run([sys.executable, str(ROOT / "main.py"), "check", "--base", "HEAD", "--json"],
                            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8")
    report = json.loads(result.stdout)
    assert report["result"] == expected
    assert result.returncode == (1 if expected == "fail" else 0)


def test_github_removed_document_is_not_a_requirement_update(monkeypatch):
    gh = GitHubAdapter("fake", "owner/repo")
    monkeypatch.setattr(gh, "_get", lambda url: [{"filename": "docs/api/users.md", "status": "removed", "patch": "-GET /users\n"}])
    deleted = gh.get_pr_files(1)[0]
    assert deleted.status == "deleted"
    assert run([route_file(), deleted], policy=api_policy()).result == "fail"


def test_moving_doc_out_of_required_path_does_not_satisfy_group():
    policy = api_policy()
    policy.rules[0].require.groups[0].content = "paths"
    moved = ChangedFile(path="archive/users.md", previous_path="docs/api/users.md", status="renamed")
    assert run([route_file(), moved], policy=policy).result == "fail"
