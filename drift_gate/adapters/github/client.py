"""
GitHub API adapter — PR 변경 파일 수집 (페이지네이션 포함).
core에서 사용 금지.
"""
import json
import re
import urllib.request
import urllib.error
from typing import List, Optional, Tuple

from drift_gate.core.models.changed_file import ChangedFile
from drift_gate.core.models.result import DriftIgnoreDirective


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

        return [
            ChangedFile(
                path=f["filename"],
                status=f["status"],
                previous_path=f.get("previous_filename"),
                patch=f.get("patch", ""),
            )
            for f in files
        ]

    def get_pr_body(self, pr_number: int) -> str:
        """PR description 반환."""
        url = f"{self._base}/repos/{self._repo}/pulls/{pr_number}"
        data = self._get(url)
        return (data or {}).get("body") or ""

    def get_pr_files_and_body(
        self, pr_number: int
    ) -> Tuple[List[ChangedFile], str]:
        """변경 파일 + PR description 동시 반환."""
        return self.get_pr_files(pr_number), self.get_pr_body(pr_number)

    # ── Internal ──────────────────────────────────────────────────────────

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
            raise RuntimeError(f"GitHub API 오류 {e.code}: {url}") from e


def parse_drift_ignores(pr_body: str) -> List[DriftIgnoreDirective]:
    """
    PR description에서 drift-ignore 지시문 파싱.
    drift-ignore: <rule-id>
    reason: <이유>   (선택)
    """
    ignores: List[DriftIgnoreDirective] = []
    for m in re.finditer(r"drift-ignore:\s*(\S+)", pr_body):
        rule_id = m.group(1)
        window = pr_body[m.start(): m.start() + 300]
        reason_m = re.search(r"reason\s*:\s*(.+)", window)
        reason = reason_m.group(1).strip() if reason_m else None
        ignores.append(DriftIgnoreDirective(rule_id=rule_id, reason=reason))
    return ignores
