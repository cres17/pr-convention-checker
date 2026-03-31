"""
GitHub PR comment adapter — urllib 기반, gh CLI 불필요.
기존 마커 댓글을 찾아 upsert(update or create).
"""
import json
import urllib.request
import urllib.error
from typing import Optional


class PrCommenter:
    """
    PR에 Drift Gate 결과 댓글을 게시/업데이트.
    중복 방지 마커(<!-- drift-gate-v1 -->)로 기존 댓글을 찾아 patch.
    """

    MARKER = "<!-- drift-gate-v1 -->"

    def __init__(self, token: str, repo: str):
        self._token = token
        self._repo = repo
        self._base = "https://api.github.com"

    def upsert(self, pr_number: int, body: str) -> Optional[str]:
        """
        기존 마커 댓글이 있으면 업데이트, 없으면 신규 생성.
        반환: comment HTML URL (실패 시 None)
        """
        try:
            existing_id = self._find_existing(pr_number)
            if existing_id:
                return self._update_comment(existing_id, body)
            else:
                return self._create_comment(pr_number, body)
        except Exception as e:
            import sys
            print(f"[drift-gate] WARNING: PR comment 게시 실패: {e}", file=sys.stderr)
            return None

    # ── Internal ──────────────────────────────────────────────────────────

    def _find_existing(self, pr_number: int) -> Optional[int]:
        """마커가 포함된 첫 번째 댓글 ID 반환. 없으면 None."""
        page = 1
        while True:
            url = (
                f"{self._base}/repos/{self._repo}/issues/{pr_number}"
                f"/comments?per_page=100&page={page}"
            )
            comments = self._request("GET", url)
            if not comments:
                break
            for c in comments:
                if (c.get("body") or "").startswith(self.MARKER):
                    return c["id"]
            if len(comments) < 100:
                break
            page += 1
        return None

    def _create_comment(self, pr_number: int, body: str) -> str:
        url = f"{self._base}/repos/{self._repo}/issues/{pr_number}/comments"
        data = self._request("POST", url, {"body": body})
        return data["html_url"]

    def _update_comment(self, comment_id: int, body: str) -> str:
        url = f"{self._base}/repos/{self._repo}/issues/comments/{comment_id}"
        data = self._request("PATCH", url, {"body": body})
        return data["html_url"]

    def _request(self, method: str, url: str, payload: Optional[dict] = None):
        data = json.dumps(payload).encode() if payload else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github.v3+json",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
