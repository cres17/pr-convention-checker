"""Project- and version-aware default filenames for saved reports.

The default save name used to be the fixed ``drift-gate-report.<ext>``, so
reports from different projects, branches or releases overwrote each other.
Names are now built from the selected repository:

    {project}_{branch}_{version}_{kind}_{timestamp}.{ext}
    e.g. pr-convention-checker_ver2_v1.0.0_drift-report_20260929-173012.html

A repository can override the pattern in ``.drift-gate.yml``::

    report:
      filename: "{project}-{version}-{kind}-{date}"

Only the placeholders in ``FIELDS`` are accepted; anything else falls back to
the default pattern. Empty values (no tag, detached HEAD) are dropped together
with their separator.
"""

from __future__ import annotations

import json
import re
import string
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DEFAULT_TEMPLATE = "{project}_{branch}_{version}_{kind}_{timestamp}"
FIELDS = frozenset({"project", "branch", "version", "commit", "kind", "date", "timestamp"})
_UNSAFE = re.compile(r"[^\w.\-]+")
_REPEATED_SEPARATORS = re.compile(r"([_\-])[_\-]+")
_WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                     *(f"lpt{i}" for i in range(1, 10))}
_MAX_STEM = 150


@dataclass(frozen=True)
class ProjectIdentity:
    name: str
    version: str = ""
    branch: str = ""
    commit: str = ""


def _git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )
    except OSError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _pyproject_version(text: str) -> str:
    section = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            section = stripped
            continue
        if section in {"[project]", "[tool.poetry]"}:
            match = re.match(r"""version\s*=\s*["']([^"']+)["']""", stripped)
            if match:
                return match.group(1)
    return ""


def _manifest_version(repo: Path) -> str:
    """Read the declared version from package.json or pyproject.toml, if any."""
    try:
        package = repo / "package.json"
        if package.is_file():
            value = json.loads(package.read_text(encoding="utf-8")).get("version")
            if isinstance(value, str) and value.strip():
                return value.strip()
        pyproject = repo / "pyproject.toml"
        if pyproject.is_file():
            return _pyproject_version(pyproject.read_text(encoding="utf-8"))
    except (OSError, ValueError, AttributeError):
        pass
    return ""


def detect_project(repository: str | Path) -> ProjectIdentity:
    """Name = repository folder; version = exact tag, else manifest version."""
    repo = Path(repository)
    version = _git(repo, "describe", "--tags", "--exact-match") or _manifest_version(repo)
    if version[:1].isdigit():
        version = f"v{version}"
    return ProjectIdentity(
        name=repo.name,
        version=version,
        # Works before the first commit; empty on a detached HEAD.
        branch=_git(repo, "symbolic-ref", "--short", "-q", "HEAD"),
        commit=_git(repo, "rev-parse", "--short", "HEAD"),
    )


def template_from_policy(policy_source: str) -> str | None:
    """Return ``report.filename`` from the policy text, ignoring malformed input."""
    try:
        import yaml

        data = yaml.safe_load(policy_source or "") or {}
    except Exception:
        return None
    report = data.get("report") if isinstance(data, dict) else None
    value = report.get("filename") if isinstance(report, dict) else None
    return value if isinstance(value, str) and value.strip() else None


def _valid_template(template: str) -> bool:
    try:
        parts = list(string.Formatter().parse(template))
    except ValueError:
        return False
    fields = [(name, spec, conversion) for _, name, spec, conversion in parts if name is not None]
    return bool(fields) and all(
        name in FIELDS and not spec and not conversion for name, spec, conversion in fields
    )


def _slug(value: str) -> str:
    return _UNSAFE.sub("-", value.strip()).strip("-_.")


def report_filename(
    identity: ProjectIdentity,
    kind: str,
    extension: str,
    template: str | None = None,
    now: datetime | None = None,
) -> str:
    """Build a filesystem-safe report filename for the given project and kind."""
    now = now or datetime.now()
    values = {
        "project": identity.name,
        "branch": identity.branch,
        "version": identity.version,
        "commit": identity.commit,
        "kind": kind,
        "date": now.strftime("%Y%m%d"),
        "timestamp": now.strftime("%Y%m%d-%H%M%S"),
    }
    pattern = template if template and _valid_template(template) else DEFAULT_TEMPLATE
    stem = pattern.format_map({key: _slug(value) for key, value in values.items()})
    stem = _slug(_REPEATED_SEPARATORS.sub(r"\1", stem))[:_MAX_STEM].rstrip("-_.")
    if not stem:
        stem = f"report_{values['timestamp']}"
    if stem.split(".")[0].casefold() in _WINDOWS_RESERVED:
        stem = f"report_{stem}"
    return f"{stem}.{extension.lstrip('.')}"


def default_report_path(repository: str | Path, kind: str, extension: str,
                        policy_source: str = "") -> Path:
    repo = Path(repository)
    name = report_filename(detect_project(repo), kind, extension, template_from_policy(policy_source))
    return repo / name
