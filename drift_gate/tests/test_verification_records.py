import json

import pytest

from drift_gate.desktop import verification_records as vr
from drift_gate.desktop.progress_service import (
    BaselineError,
    extract_requirements,
    link_test_results,
    save_baseline,
)
from drift_gate.tests.test_progress_service import project

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="4">
  <testcase classname="tests.test_auth" name="test_login_ok" time="0.01"/>
  <testcase classname="tests.test_auth" name="test_login_bad_password"><failure message="boom">x</failure></testcase>
  <testcase classname="tests.test_auth" name="test_login_locked"><skipped message="later"/></testcase>
  <testcase classname="tests.test_pay" name="test_charge_req-{marker}"><error message="e"/></testcase>
</testsuite></testsuites>
"""

VITEST = {"testResults": [{"name": "/repo/src/login.test.ts", "assertionResults": [
    {"fullName": "login shows form", "status": "passed"},
    {"fullName": "login rejects empty", "status": "failed"},
    {"fullName": "login todo", "status": "todo"},
]}]}


def write(tmp_path, name, content):
    target = tmp_path / name
    target.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    return target


def test_junit_and_vitest_results_are_normalized(tmp_path):
    parsed = vr.parse_results(write(tmp_path, "r.xml", JUNIT))
    assert parsed["format"] == "junit"
    assert [(t["name"], t["status"]) for t in parsed["tests"]] == [
        ("tests.test_auth::test_login_ok", "passed"),
        ("tests.test_auth::test_login_bad_password", "failed"),
        ("tests.test_auth::test_login_locked", "skipped"),
        ("tests.test_pay::test_charge_req-{marker}", "failed"),
    ]
    parsed = vr.parse_results(write(tmp_path, "r.json", VITEST))
    assert parsed["format"] == "jest"
    assert [t["status"] for t in parsed["tests"]] == ["passed", "failed", "skipped"]
    assert parsed["tests"][0]["name"] == "login.test.ts::login shows form"


def test_unsafe_or_unknown_files_are_rejected(tmp_path):
    for content in ('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><testsuite/>', "<testsuite><broken", "plain text", "{}", "[1]"):
        with pytest.raises(ValueError):
            vr.parse_results(write(tmp_path, "bad.txt", content))
    with pytest.raises(ValueError):
        vr.parse_results(tmp_path / "missing.xml")


def test_patterns_are_cleaned_and_limited():
    assert vr.clean_patterns(None) == []
    assert vr.clean_patterns([" a ", "a", "", "b"]) == ["a", "b"]
    for bad in ("a", [1], ["x" * 201], ["a"] * 6):
        assert vr.clean_patterns(bad) is None


def test_items_link_to_tests_by_pattern_or_req_marker():
    parsed = {"format": "junit", "file": "r.xml", "modified": "t", "tests": [
        {"name": "tests.test_auth::test_login_ok", "status": "passed"},
        {"name": "tests.test_auth::test_login_bad", "status": "failed"},
        {"name": "tests.test_pay::test_charge_req-abcdef12", "status": "passed"},
    ]}
    items = [
        {"id": "1" * 16, "included": True, "test_patterns": ["test_login"]},
        {"id": "abcdef1234567890", "included": True},
        {"id": "2" * 16, "included": True, "test_patterns": ["typo_name"]},
        {"id": "3" * 16, "included": True},
        {"id": "4" * 16, "included": False, "test_patterns": ["test_login"]},
    ]
    linked = vr.link_tests(parsed, items)
    assert linked["total"] == 3
    login = linked["items"]["1" * 16]
    assert (login["matched"], login["passed"], login["failed"]) == (2, 1, 1)
    assert login["failing"] == ["tests.test_auth::test_login_bad"] and not login["no_match"]
    assert linked["items"]["abcdef1234567890"]["passed"] == 1  # matched by the marker alone
    assert linked["items"]["2" * 16]["no_match"] is True  # explicit pattern that matches nothing
    assert "3" * 16 not in linked["items"] and "4" * 16 not in linked["items"]


def test_link_test_results_reads_the_saved_baseline_and_validates_patterns(tmp_path):
    repo = project(tmp_path)
    state = tmp_path / "state"
    draft = extract_requirements(repo, ["README.md"])
    draft["requirements"][0]["test_patterns"] = ["  test_login  ", "test_login"]
    saved = save_baseline(repo, state, draft)
    assert saved["requirements"][0]["test_patterns"] == ["test_login"]
    result = link_test_results(repo, state, write(tmp_path, "r.xml", JUNIT))
    first_id = saved["requirements"][0]["id"]
    assert result["items"][first_id]["failed"] == 1 and result["total"] == 4
    draft["requirements"][1]["test_patterns"] = ["x"] * 9
    with pytest.raises(BaselineError) as raised:
        save_baseline(repo, state, draft)
    assert raised.value.errors[0]["field"] == "test_patterns"


def test_windows_style_suite_paths_are_reduced_to_the_file_name(tmp_path):
    payload = {"testResults": [{"name": "C:\\repo\\src\\login.test.ts",
                                "assertionResults": [{"fullName": "shows form", "status": "passed"}]}]}
    parsed = vr.parse_results(write(tmp_path, "win.json", payload))
    assert parsed["tests"][0]["name"] == "login.test.ts::shows form"


def test_results_older_than_the_evidence_code_are_flagged(tmp_path):
    import os
    code = tmp_path / "src"
    code.mkdir()
    (code / "login.py").write_text("x = 1\n", encoding="utf-8")
    result = write(tmp_path, "r.xml", JUNIT)
    os.utime(result, (1_000_000, 1_000_000))
    os.utime(code / "login.py", (1_000_100, 1_000_100))  # edited after the results were written
    parsed = vr.parse_results(result)
    items = [{"id": "1" * 16, "included": True, "test_patterns": ["test_login"],
              "evidence": {"path": "src/login.py", "line": 1}},
             {"id": "2" * 16, "included": True, "test_patterns": ["test_charge"],
              "evidence": {"path": "src/missing.py", "line": 1}}]
    linked = vr.link_tests(parsed, items, tmp_path)["items"]
    assert linked["1" * 16]["code_newer"] is True
    assert linked["2" * 16]["code_newer"] is False  # a missing file says nothing about the results
    os.utime(code / "login.py", (999_999, 999_999))
    assert vr.link_tests(parsed, items, tmp_path)["items"]["1" * 16]["code_newer"] is False
    assert vr.link_tests(parsed, items)["items"]["1" * 16]["code_newer"] is False  # no root: unknown


def test_test_file_detection_by_name_and_folder():
    for path in ("tests/test_a.py", "pkg/test_b.py", "pkg/b_test.go", "web/login.test.tsx", "web/a.spec.ts",
                 "src/__tests__/x.js", "app/tests/helpers.py", "src/LoginTest.java"):
        assert vr.is_test_source(path), path
    for path in ("src/login.py", "README.md", "tests/data.json", "docs/tests.md", "src/latest.py"):
        assert not vr.is_test_source(path), path


def test_pattern_typos_are_found_without_a_result_file(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_auth.py").write_text("def test_login_ok():\n    pass\n", encoding="utf-8")
    (tmp_path / "web").mkdir()
    (tmp_path / "web/app.test.ts").write_text("describe('checkout flow', () => {})\n", encoding="utf-8")
    (tmp_path / "src.py").write_text("test_secret_name = 1\n", encoding="utf-8")  # not a test file
    files = {"tests/test_auth.py", "web/app.test.ts", "src.py"}
    items = [
        {"id": "a", "included": True, "test_patterns": ["test_login", "test_logni"]},
        {"id": "b", "included": True, "test_patterns": ["checkout flow", "test_secret_name"]},
        {"id": "c", "included": True},
        {"id": "d", "included": False, "test_patterns": ["nothing"]},
    ]
    assert vr.find_unmatched_patterns(tmp_path, files, items) == {"a": ["test_logni"], "b": ["test_secret_name"]}
    assert vr.find_unmatched_patterns(tmp_path, files, [items[2]]) == {}
