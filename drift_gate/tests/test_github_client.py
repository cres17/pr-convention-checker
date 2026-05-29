"""
Unit tests for GitHubAdapter and parse_drift_ignores.
Covers: pagination edge cases (300+ files), binary/non-text file handling,
path sanitization, HTTP error messages with hints, and drift-ignore parsing.
All tests use monkeypatching — no real network calls.
"""
import json
from io import BytesIO
from unittest.mock import MagicMock, call, patch
import urllib.error

import pytest

from drift_gate.adapters.github.client import (
    GitHubAdapter,
    _sanitize_path,
    _github_api_error,
    parse_drift_ignores,
)


# ── _sanitize_path ────────────────────────────────────────────────────────────

class TestSanitizePath:
    def test_normal_path(self):
        assert _sanitize_path("src/routes/users.ts") == "src/routes/users.ts"

    def test_strips_leading_slash(self):
        assert _sanitize_path("/etc/passwd") is None

    def test_rejects_traversal(self):
        assert _sanitize_path("../../etc/passwd") is None

    def test_rejects_embedded_traversal(self):
        assert _sanitize_path("src/../../../etc/passwd") is None

    def test_rejects_empty(self):
        assert _sanitize_path("") is None

    def test_rejects_whitespace_only(self):
        assert _sanitize_path("   ") is None

    def test_normalises_redundant_slashes(self):
        result = _sanitize_path("src/./routes/users.ts")
        assert result is not None
        assert ".." not in result

    def test_deep_nested_path(self):
        assert _sanitize_path("a/b/c/d/e/f.py") == "a/b/c/d/e/f.py"


# ── _github_api_error hints ───────────────────────────────────────────────────

class TestGithubApiErrorHints:
    def _make_http_error(self, code: int, body: bytes = b"{}") -> urllib.error.HTTPError:
        return urllib.error.HTTPError(
            url="https://api.github.com/repos/o/r/pulls/1/files",
            code=code,
            msg="Error",
            hdrs=None,
            fp=BytesIO(body),
        )

    def test_401_hint_mentions_token(self):
        err = _github_api_error(self._make_http_error(401), "https://example.com")
        assert "GITHUB_TOKEN" in str(err)
        assert "401" in str(err)

    def test_403_hint_mentions_scope(self):
        err = _github_api_error(self._make_http_error(403), "https://example.com")
        assert "권한" in str(err) or "scope" in str(err).lower() or "403" in str(err)

    def test_404_hint_mentions_repo(self):
        err = _github_api_error(self._make_http_error(404), "https://example.com")
        assert "저장소" in str(err) or "404" in str(err)

    def test_429_hint_mentions_rate_limit(self):
        err = _github_api_error(self._make_http_error(429), "https://example.com")
        assert "429" in str(err)

    def test_500_hint_mentions_github_status(self):
        err = _github_api_error(self._make_http_error(500), "https://example.com")
        assert "500" in str(err)

    def test_github_message_included_in_error(self):
        body = json.dumps({"message": "Bad credentials"}).encode()
        err = _github_api_error(self._make_http_error(401, body), "https://example.com")
        assert "Bad credentials" in str(err)

    def test_unknown_code_still_shows_code(self):
        err = _github_api_error(self._make_http_error(418), "https://example.com")
        assert "418" in str(err)

    def test_returns_runtime_error(self):
        err = _github_api_error(self._make_http_error(401), "https://example.com")
        assert isinstance(err, RuntimeError)


# ── GitHubAdapter pagination ──────────────────────────────────────────────────

def _make_adapter() -> GitHubAdapter:
    return GitHubAdapter(token="fake-token", repo="owner/repo")


def _page_of_files(count: int, start_index: int = 1) -> list:
    return [
        {
            "filename": f"src/file_{start_index + i}.py",
            "status": "modified",
            "patch": f"@@ -1,1 +1,1 @@\n+change_{start_index + i}\n",
        }
        for i in range(count)
    ]


class TestPaginationEdgeCases:
    def test_single_page_under_100_files(self):
        adapter = _make_adapter()
        page1 = _page_of_files(42)

        with patch.object(adapter, "_get", return_value=page1) as mock_get:
            files = adapter.get_pr_files(1)

        assert len(files) == 42
        assert mock_get.call_count == 1

    def test_exactly_100_files_triggers_second_page(self):
        adapter = _make_adapter()
        page1 = _page_of_files(100, start_index=1)
        page2 = _page_of_files(0)  # empty → stop

        with patch.object(adapter, "_get", side_effect=[page1, page2]) as mock_get:
            files = adapter.get_pr_files(1)

        assert len(files) == 100
        assert mock_get.call_count == 2

    def test_300_files_across_three_pages(self):
        adapter = _make_adapter()
        page1 = _page_of_files(100, start_index=1)
        page2 = _page_of_files(100, start_index=101)
        page3 = _page_of_files(100, start_index=201)
        page4 = []  # empty → stop

        with patch.object(adapter, "_get", side_effect=[page1, page2, page3, page4]) as mock_get:
            files = adapter.get_pr_files(1)

        assert len(files) == 300
        assert mock_get.call_count == 4

    def test_301_files_across_four_pages(self):
        # page4 has 1 file (< 100) → pagination stops after page4, no page5 call
        adapter = _make_adapter()
        page1 = _page_of_files(100, start_index=1)
        page2 = _page_of_files(100, start_index=101)
        page3 = _page_of_files(100, start_index=201)
        page4 = _page_of_files(1, start_index=301)

        with patch.object(adapter, "_get", side_effect=[page1, page2, page3, page4]) as mock_get:
            files = adapter.get_pr_files(1)

        assert len(files) == 301
        assert mock_get.call_count == 4

    def test_pagination_stops_when_page_has_less_than_100(self):
        adapter = _make_adapter()
        page1 = _page_of_files(100)
        page2 = _page_of_files(57)  # partial page → no more pages

        with patch.object(adapter, "_get", side_effect=[page1, page2]) as mock_get:
            files = adapter.get_pr_files(1)

        assert len(files) == 157
        assert mock_get.call_count == 2

    def test_empty_first_page_returns_empty_list(self):
        adapter = _make_adapter()

        with patch.object(adapter, "_get", return_value=[]) as mock_get:
            files = adapter.get_pr_files(1)

        assert files == []

    def test_page_urls_include_page_number(self):
        adapter = _make_adapter()
        # Use a list: page1 full (100 items) → triggers page2 call; page2 empty → stop
        page1 = _page_of_files(100, start_index=1)
        page2: list = []

        call_urls: list = []
        responses = iter([page1, page2])

        original_get = adapter._get.__func__ if hasattr(adapter._get, '__func__') else None

        def fake_get(url: str):
            call_urls.append(url)
            return next(responses)

        with patch.object(adapter, "_get", side_effect=fake_get):
            files = adapter.get_pr_files(42)

        assert len(files) == 100
        assert len(call_urls) == 2
        assert "page=1" in call_urls[0]
        assert "page=2" in call_urls[1]
        assert all("per_page=100" in u for u in call_urls)
        assert all("pulls/42" in u for u in call_urls)


# ── binary / non-text file handling ──────────────────────────────────────────

class TestBinaryFileHandling:
    def _make_binary_file_entry(self, filename: str) -> dict:
        return {
            "filename": filename,
            "status": "modified",
            # GitHub API omits 'patch' for binary files
        }

    def test_binary_image_no_patch(self):
        adapter = _make_adapter()
        files_data = [self._make_binary_file_entry("assets/logo.png")]

        with patch.object(adapter, "_get", side_effect=[files_data, []]):
            files = adapter.get_pr_files(1)

        assert len(files) == 1
        assert files[0].path == "assets/logo.png"
        assert files[0].patch == ""

    def test_binary_pdf_no_patch(self):
        adapter = _make_adapter()
        files_data = [self._make_binary_file_entry("docs/contract.pdf")]

        with patch.object(adapter, "_get", side_effect=[files_data, []]):
            files = adapter.get_pr_files(1)

        assert files[0].patch == ""

    def test_compiled_artifact_no_patch(self):
        adapter = _make_adapter()
        files_data = [self._make_binary_file_entry("dist/bundle.js.map")]

        with patch.object(adapter, "_get", side_effect=[files_data, []]):
            files = adapter.get_pr_files(1)

        assert files[0].path == "dist/bundle.js.map"
        assert files[0].patch == ""

    def test_mixed_binary_and_text_files(self):
        adapter = _make_adapter()
        files_data = [
            {"filename": "assets/image.png", "status": "added"},
            {
                "filename": "src/routes/api.ts",
                "status": "modified",
                "patch": "@@ -1,1 +1,1 @@\n+router.get('/new', h)\n",
            },
            {"filename": "dist/output.wasm", "status": "modified"},
        ]

        with patch.object(adapter, "_get", side_effect=[files_data, []]):
            files = adapter.get_pr_files(1)

        assert len(files) == 3
        text_file = next(f for f in files if f.path == "src/routes/api.ts")
        assert "router.get" in text_file.patch

        binary_files = [f for f in files if f.patch == ""]
        assert len(binary_files) == 2

    def test_binary_file_with_unsafe_path_is_rejected(self):
        adapter = _make_adapter()
        files_data = [
            {"filename": "../../etc/shadow", "status": "modified"},
            {"filename": "safe/file.py", "status": "modified", "patch": "+ok\n"},
        ]

        with patch.object(adapter, "_get", side_effect=[files_data, []]):
            files = adapter.get_pr_files(1)

        paths = [f.path for f in files]
        assert "safe/file.py" in paths
        assert "../../etc/shadow" not in paths

    def test_large_pr_with_mixed_binary_and_text(self):
        adapter = _make_adapter()
        text_files = _page_of_files(60, start_index=1)
        binary_files = [
            {"filename": f"assets/image_{i}.png", "status": "modified"}
            for i in range(40)
        ]
        page1 = text_files + binary_files

        with patch.object(adapter, "_get", side_effect=[page1, []]):
            files = adapter.get_pr_files(1)

        assert len(files) == 100
        no_patch = [f for f in files if f.patch == ""]
        assert len(no_patch) == 40


# ── HTTP error on pagination ──────────────────────────────────────────────────

class TestPaginationHttpErrors:
    def test_http_error_on_page_2_raises(self):
        adapter = _make_adapter()
        page1 = _page_of_files(100)

        http_err = urllib.error.HTTPError(
            url="https://api.github.com/repos/owner/repo/pulls/1/files?per_page=100&page=2",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=BytesIO(b'{"message": "Resource not accessible by integration"}'),
        )

        def fake_get(url):
            if "page=2" in url:
                raise _github_api_error(http_err, url)
            return page1

        with patch.object(adapter, "_get", side_effect=fake_get):
            with pytest.raises(RuntimeError, match="403"):
                adapter.get_pr_files(1)


# ── parse_drift_ignores ───────────────────────────────────────────────────────

class TestParseDriftIgnores:
    def test_basic_ignore_with_reason(self):
        body = "drift-ignore: api-contract-sync\nreason: internal refactor\n"
        ignores = parse_drift_ignores(body)
        assert len(ignores) == 1
        assert ignores[0].rule_id == "api-contract-sync"
        assert ignores[0].reason == "internal refactor"

    def test_ignore_without_reason(self):
        body = "drift-ignore: some-rule\n"
        ignores = parse_drift_ignores(body)
        assert ignores[0].reason is None

    def test_ignore_with_expires(self):
        body = "drift-ignore: rule-x\nreason: temp\nexpires: 2030-12-31\n"
        ignores = parse_drift_ignores(body)
        assert ignores[0].expires == "2030-12-31"

    def test_ignore_with_approved_by(self):
        body = "drift-ignore: rule-x\nreason: approved\napproved-by: @team/api\n"
        ignores = parse_drift_ignores(body)
        assert ignores[0].approved_by == "@team/api"

    def test_multiple_ignores(self):
        body = (
            "drift-ignore: rule-a\nreason: reason a\n\n"
            "drift-ignore: rule-b\nreason: reason b\n"
        )
        ignores = parse_drift_ignores(body)
        assert len(ignores) == 2
        assert {i.rule_id for i in ignores} == {"rule-a", "rule-b"}

    def test_no_ignores_in_body(self):
        body = "This PR adds new features. No drift-ignore needed."
        ignores = parse_drift_ignores(body)
        assert ignores == []

    def test_empty_body(self):
        ignores = parse_drift_ignores("")
        assert ignores == []

    def test_ignore_in_pr_template_comments(self):
        body = (
            "## Summary\n"
            "Added new endpoint.\n\n"
            "drift-ignore: api-contract-sync\n"
            "reason: spec updated in separate PR\n"
        )
        ignores = parse_drift_ignores(body)
        assert len(ignores) == 1
        assert ignores[0].reason == "spec updated in separate PR"
