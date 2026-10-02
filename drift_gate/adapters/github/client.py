"""
GitHub API adapter — PR 변경 파일 수집 (페이지네이션 포함).
core에서 사용 금지.
"""
import json
import base64
import re
import urllib.request
import urllib.error
from pathlib import PurePosixPath
from typing import List, Optional, Tuple
from urllib.parse import quote

from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.result import DriftIgnoreDirective


def _sanitize_path(raw: str) -> Optional[str]:
    """
    Validate and normalize a file path from GitHub API response.

    Rejects paths that:
    - Are empty or whitespace-only
    - Are absolute (start with '/')
    - Contain path traversal sequences ('..') after normalization

    Returns the normalized relative path string, or None if the path is unsafe.
    """
    if not raw or not raw.strip():
        return None

    path = raw.strip()

    # Reject absolute paths
    if path.startswith("/"):
        return None

    # Normalize and check for traversal
    try:
        normalized = PurePosixPath(path)
    except (ValueError, TypeError):
        return None

    if ".." in normalized.parts:
        return None

    clean = "/".join(normalized.parts)
    if not clean:
        return None

    return clean


class GitHubAdapter:
    def __init__(self, token: str, repo: str):
        """
        Args:
            token: GitHub personal access token
            repo:  'owner/repo' 형식
        """
        self._token = token
        self._repo = repo
        self._base = "https://api.github.com"

    # ── Public ────────────────────────────────────────────────────────────

    def get_pr_files(self, pr_number: int) -> List[ChangedFile]:
        """PR 변경 파일 전체 수집 (페이지네이션)."""
        files: List[dict] = []
        page = 1
        while True:
            url = (
                f"{self._base}/repos/{self._repo}/pulls/{pr_number}"
                f"/files?per_page=100&page={page}"
            )
            data = self._get(url)
            if not data:
                break
            files.extend(data)
            if len(data) < 100:
                break
            page += 1

        result = []
        for f in files:
            safe_path = _sanitize_path(f.get("filename", ""))
            if safe_path is None:
                continue
            prev_raw = f.get("previous_filename")
            safe_prev = _sanitize_path(prev_raw) if prev_raw else None
            result.append(ChangedFile(
                path=safe_path,
                status="deleted" if f["status"] == "removed" else f["status"],
                previous_path=safe_prev,
                patch=f.get("patch", ""),
            ))
        return result

    def get_pr_body(self, pr_number: int) -> str:
        """PR description 반환."""
        url = f"{self._base}/repos/{self._repo}/pulls/{pr_number}"
        data = self._get(url)
        return (data or {}).get("body") or ""

    def get_pr_files_and_body(
        self, pr_number: int
    ) -> Tuple[List[ChangedFile], str]:
        """변경 파일 + PR description 동시 반환."""
        url = f"{self._base}/repos/{self._repo}/pulls/{pr_number}"
        before = self._get(url)
        files = self.get_pr_files(pr_number)
        after = self._get(url)
        if before["head"]["sha"] != after["head"]["sha"] or before["base"]["sha"] != after["base"]["sha"]:
            raise RuntimeError("PR changed while collecting files; retry against a stable revision")
        self._snapshot_head = after["head"]["sha"]
        return files, after.get("body") or ""

    def attach_env_documents(self, pr_number, files, policy):
        from drift_gate.adapters.docs.content import attach_env_documents
        if not any(group.content == "env-keys" for rule in policy.rules for group in rule.require.groups):
            return files
        head = getattr(self, "_snapshot_head", None)
        if not head:
            head = self._get(f"{self._base}/repos/{self._repo}/pulls/{pr_number}")["head"]["sha"]
        return attach_env_documents(files, policy, lambda path: self.get_file_text(path, head))

    # ── Internal ──────────────────────────────────────────────────────────

    def get_file_text(self, path: str, ref: str) -> Optional[str]:
        """Read a bounded text blob at an explicit revision; never use a download URL."""
        if _sanitize_path(path) is None:
            raise ValueError("unsafe repository path")
        try:
            data = self._get(f"{self._base}/repos/{self._repo}/contents/{quote(path)}?ref={quote(ref, safe='')}")
        except GitHubAPIError as exc:
            if exc.status == 404:
                return None
            raise
        if data.get("type") != "file" or data.get("encoding") != "base64" or data.get("size", 0) > 1_000_000:
            raise ValueError("unsupported or oversized repository file")
        return base64.b64decode(data["content"]).decode("utf-8")

    def _get(self, url: str):
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise _github_api_error(e, url) from e


_HTTP_HINTS: dict = {
    401: "인증 실패 — GITHUB_TOKEN이 없거나 만료됐습니다.",
    403: "권한 부족 — 토큰에 'repo' 또는 'pull_requests:read' 스코프가 필요합니다.",
    404: "저장소 또는 PR을 찾을 수 없음 — REPO 형식(owner/repo)과 PR 번호를 확인하세요.",
    410: "리소스가 삭제됐습니다 (GitHub 410 Gone).",
    422: "요청 형식 오류 — 요청 파라미터를 확인하세요.",
    429: "GitHub API 요청 한도 초과 — 잠시 후 재시도하세요.",
    500: "GitHub 서버 오류 — https://githubstatus.com 을 확인하세요.",
    502: "GitHub 서버 오류 (502 Bad Gateway) — 잠시 후 재시도하세요.",
    503: "GitHub 서비스 일시 불가 — https://githubstatus.com 을 확인하세요.",
}


class GitHubAPIError(RuntimeError):
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def _github_api_error(e: "urllib.error.HTTPError", url: str) -> RuntimeError:
    hint = _HTTP_HINTS.get(e.code, "")
    try:
        body = e.read().decode(errors="replace")
        gh_msg = json.loads(body).get("message", "")
    except Exception:
        gh_msg = ""
    parts = [f"GitHub API {e.code} 오류: {url}"]
    if gh_msg:
        parts.append(f"  GitHub 메시지: {gh_msg}")
    if hint:
        parts.append(f"  힌트: {hint}")
    return GitHubAPIError("\n".join(parts), e.code)


def parse_drift_ignores(pr_body: str) -> List[DriftIgnoreDirective]:
    """
    PR description에서 drift-ignore 지시문 파싱.
    drift-ignore: <rule-id>
    reason: <이유>   (선택)
    expires: <YYYY-MM-DD>   (선택)
    approved-by: <CODEOWNER>   (선택)
    """
    ignores: List[DriftIgnoreDirective] = []
    matches = list(re.finditer(r"(?m)^\s*drift-ignore:[ \t]*(\S+)[ \t]*$", pr_body))
    for index, m in enumerate(matches):
        rule_id = m.group(1)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(pr_body)
        window = pr_body[m.end():end]
        reason_m = re.search(r"(?m)^[ \t]*reason[ \t]*:[ \t]*(\S[^\r\n]*)", window)
        reason = reason_m.group(1).strip() if reason_m else None
        expires_m = re.search(r"(?m)^[ \t]*expires[ \t]*:[ \t]*(\S[^\r\n]*)", window)
        expires = expires_m.group(1).strip() if expires_m else None
        approved_m = re.search(r"(?mi)^[ \t]*approved-by[ \t]*:[ \t]*(\S[^\r\n]*)", window)
        approved_by = approved_m.group(1).strip() if approved_m else None
        ignores.append(
            DriftIgnoreDirective(
                rule_id=rule_id,
                reason=reason,
                expires=expires,
                approved_by=approved_by,
            )
        )
    return ignores
