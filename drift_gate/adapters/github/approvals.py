"""Verify suppression approvals using base-branch ownership and current reviews.

Supports common CODEOWNERS globs and @user / @org/team owners. Unsupported
syntax and API failures reject the exemption, never weaken the policy.
"""
from dataclasses import replace
import hashlib
import re
from urllib.parse import quote

from drift_gate.utils.glob_matcher import match_glob, matches_any


def _owners(text: str, path: str) -> list[str]:
    owners = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        pattern = parts[0]
        if any(c in pattern for c in ("!", "[", "]", "\\")):
            raise ValueError("unsupported CODEOWNERS syntax")
        if any("**" in part and part != "**" for part in pattern.split("/")):
            raise ValueError("unsupported CODEOWNERS recursive wildcard")
        anchored = pattern.startswith("/")
        pattern = pattern.lstrip("/")
        anywhere = not anchored and "/" not in pattern.rstrip("/")
        match_parents = not any(c in pattern.rstrip("/").split("/")[-1] for c in "*?")
        if pattern.endswith("/"):
            pattern += "**"
        if anywhere:
            pattern = "**/" + pattern
        # Named directories cover descendants; docs/* only covers direct files.
        parents = [path]
        if match_parents:
            parents += [path.rsplit("/", depth)[0] for depth in range(1, path.count("/") + 1)]
        if any(match_glob(candidate, pattern) for candidate in parents):
            owners = parts[1:]
    return owners


def verify_ignores(github, pr_number, directives, policy, files, *, policy_sha256=None):
    if not policy.suppression.require_codeowners_approval or not directives:
        return directives
    # Drop any caller-supplied proof before verifying it ourselves.
    clean = [replace(d, approval_verified=False, approval_commit="", approval_error="",
                     approval_envelope=None, approval_signature=None) for d in directives]
    try:
        pr = github._get(f"{github._base}/repos/{github._repo}/pulls/{pr_number}")
        head = pr["head"]["sha"]
        base = pr["base"]["sha"]
        if not head or not base:
            raise ValueError("missing PR revision")
        if getattr(github, "_snapshot_head", head) != head:
            raise ValueError("PR changed after file collection")
        author = (pr.get("user") or {}).get("login", "").lower()
        codeowners = None
        for path in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
            codeowners = github.get_file_text(path, base)
            if codeowners is not None:
                break
        if not codeowners:
            raise ValueError("base branch CODEOWNERS unavailable")
        reviews = []
        page = 1
        while True:
            batch = github._get(f"{github._base}/repos/{github._repo}/pulls/{pr_number}/reviews?per_page=100&page={page}")
            reviews.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        latest = {}
        for review in sorted(reviews, key=lambda r: (r.get("submitted_at") or "", r.get("id", 0))):
            if review.get("state") in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
                latest[(review.get("user") or {}).get("login", "").lower()] = review
        approved = {login for login, review in latest.items()
                    if login and login != author and review["state"] == "APPROVED" and review.get("commit_id") == head}
        eligible = set()
        for login in approved:
            permission = github._get(f"{github._base}/repos/{github._repo}/collaborators/{quote(login)}/permission")
            if permission.get("permission") in {"admin", "write", "maintain"}:
                eligible.add(login)
        approved = eligible
        team_cache = {}
        team_permissions = {}

        def owner_approved(owner):
            if re.fullmatch(r"@[A-Za-z0-9-]+", owner):
                return owner[1:].lower() if owner[1:].lower() in approved else ""
            if re.fullmatch(r"@[A-Za-z0-9-]+/[A-Za-z0-9_-]+", owner):
                org, team = owner[1:].split("/")
                if owner not in team_permissions:
                    try:
                        data = github._get(f"{github._base}/orgs/{quote(org)}/teams/{quote(team)}/repos/{github._repo}")
                        permissions = data.get("permissions") or {}
                        team_permissions[owner] = any(permissions.get(p) for p in ("push", "maintain", "admin"))
                    except Exception:
                        team_permissions[owner] = False
                if not team_permissions[owner]:
                    return ""
                for login in sorted(approved):
                    key = (owner.lower(), login)
                    if key not in team_cache:
                        try:
                            data = github._get(f"{github._base}/orgs/{quote(org)}/teams/{quote(team)}/memberships/{quote(login)}")
                            team_cache[key] = data.get("state") == "active"
                        except Exception:
                            team_cache[key] = False
                    if team_cache[key]:
                        return login
            return ""

        rules = {rule.id: rule for rule in policy.rules}
        review_by_login = {login: review for login, review in latest.items() if login in approved}
        codeowners_sha256 = hashlib.sha256(codeowners.encode("utf-8")).hexdigest()
        verified = []
        for directive in clean:
            rule = rules.get(directive.rule_id)
            paths = sorted({path for file in files for path in (file.path, file.previous_path)
                            if path and rule and matches_any(path, rule.when.any_changed)
                            and not matches_any(path, policy.ignore_paths)})
            reviewers = set()
            complete = bool(paths)
            for path in paths:
                reviewer = next((login for owner in _owners(codeowners, path)
                                 if (login := owner_approved(owner))), "")
                if not reviewer:
                    complete = False
                    break
                reviewers.add(reviewer)
            envelope = signature = None
            error = "" if complete else "current-commit CODEOWNERS approval could not be verified"
            if complete:
                envelope, signature, error = _envelope(directive, paths, head, policy_sha256, codeowners_sha256,
                                                       [review_by_login[login] for login in sorted(reviewers)])
                complete = envelope is not None
            verified.append(replace(directive, approval_verified=complete,
                                    approved_by=", ".join(sorted(reviewers)) if complete else directive.approved_by,
                                    approval_commit=head if complete else "",
                                    approval_envelope=envelope, approval_signature=signature,
                                    approval_error=error))
        # A new push during verification must not inherit stale proof.
        current = github._get(f"{github._base}/repos/{github._repo}/pulls/{pr_number}")
        if current["head"]["sha"] != head or current["base"]["sha"] != base:
            raise ValueError("PR changed during approval verification")
        return verified
    except Exception as exc:
        # No API payloads, tokens, or PR prose in the audit error.
        return [replace(d, approval_error=f"approval verification unavailable ({type(exc).__name__})") for d in clean]


def _envelope(directive, paths, head, policy_sha256, codeowners_sha256, reviews):
    """Bind the verified approval to rule, paths, head, policy and validity dates."""
    from drift_gate.adapters.approval_signing import sign, signing_key
    from drift_gate.core.trust.approvals import ApprovalEnvelope
    if policy_sha256 is None:
        return None, None, "policy digest unavailable; approval cannot be bound to the policy"
    submitted = max((review.get("submitted_at") or "")[:10] for review in reviews)
    try:
        envelope = ApprovalEnvelope(directive.rule_id, tuple(paths), head, policy_sha256, directive.reason or "",
                                    submitted, directive.expires,
                                    tuple((review.get("user") or {}).get("login", "") for review in reviews),
                                    {"kind": "github-codeowners-review", "codeowners_sha256": codeowners_sha256,
                                     "codeowners_revision": "pull-request-base",
                                     "reviews": [{"id": review.get("id"), "commit_id": review.get("commit_id"),
                                                  "state": review.get("state"),
                                                  "submitted_at": review.get("submitted_at")} for review in reviews],
                                     "permission_check": "collaborator-or-team-write"}).to_dict()
    except ValueError as exc:
        return None, None, f"approval envelope could not be formed ({exc})"
    key = signing_key()
    return envelope, sign(envelope, *key) if key else None, ""
