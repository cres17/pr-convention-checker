"""init·install·setup 명령과 저장소 기반 정책 추천."""
import json
import sys
from pathlib import Path

from drift_gate.adapters.cli.common import _read_json_file
from drift_gate.adapters.cli.output import write_stdout as _write_stdout
from drift_gate.adapters.cli.presets import POLICY_PRESETS
from drift_gate.utils.glob_matcher import match_glob


def _run_init(args) -> None:
    recommendations = _repo_recommendations(Path.cwd())
    if args.recommend:
        _write_stdout(_format_recommendations(recommendations))
        sys.exit(0)

    path = Path(args.policy)
    if path.exists() and not args.force:
        _write_stdout(f"Policy already exists: {path}")
        _write_stdout("Use --force to overwrite it.")
        sys.exit(1)

    preset = _select_init_preset(args.preset, recommendations)
    path.write_text(POLICY_PRESETS[preset], encoding="utf-8")
    _write_stdout(f"Created starter policy: {path}")
    _write_stdout(f"Preset: {preset}")
    _write_stdout("")
    _write_stdout(_format_recommendations(recommendations))
    _write_stdout("")
    _write_stdout("Next steps:")
    _write_stdout("  py main.py doctor")
    _write_stdout("  py main.py check --explain")
    sys.exit(0)


def _run_install(args) -> None:
    repo = Path(args.repo).expanduser().resolve()
    if not repo.exists() or not repo.is_dir():
        print(f"ERROR: repo path not found: {repo}", file=sys.stderr)
        sys.exit(2)

    outcome = _install_mcp_config(
        repo=repo,
        platform=args.platform,
        config_path=Path(args.config) if args.config else None,
        force=args.force,
    )
    if outcome["kind"] == "file":
        _write_stdout(f"Installed Drift Gate MCP config: {outcome['path']}")
        _write_stdout("Restart your AI tool, then ask it to run Drift Gate on this repo.")
    else:
        _write_stdout("Add this MCP server entry to your Claude Code config:")
        _write_stdout(json.dumps(outcome["entry"], ensure_ascii=False, indent=2))
    sys.exit(0)


def _run_setup(args) -> None:
    repo = Path(args.repo).expanduser().resolve()
    if not repo.exists() or not repo.is_dir():
        print(f"ERROR: repo path not found: {repo}", file=sys.stderr)
        sys.exit(2)

    policy_path = Path(args.policy)
    if not policy_path.is_absolute():
        policy_path = repo / policy_path

    created_policy = False
    if not policy_path.exists():
        recommendations = _repo_recommendations(repo)
        preset = _select_init_preset(args.preset, recommendations)
        policy_path.write_text(POLICY_PRESETS[preset], encoding="utf-8")
        created_policy = True
    else:
        preset = "existing"

    outcome = _install_mcp_config(
        repo=repo,
        platform=args.platform,
        config_path=Path(args.config) if args.config else None,
        force=True,
    )

    lines = [
        "Drift Gate setup complete.",
        f"Policy: {policy_path} ({'created ' + preset if created_policy else 'kept existing'})",
    ]
    if outcome["kind"] == "file":
        lines.append(f"MCP config: {outcome['path']}")
        lines.append("Restart your AI tool so it reloads the MCP server.")
    else:
        lines.append("Claude Code MCP entry:")
        lines.append(json.dumps(outcome["entry"], ensure_ascii=False, indent=2))
    lines += [
        "",
        "Daily commands:",
        "  py -m drift_gate          # local pre-push contract check",
        "  py -m drift_gate review   # deterministic code-quality preflight",
    ]
    _write_stdout("\n".join(lines))
    sys.exit(0)


def _install_mcp_config(
    *,
    repo: Path,
    platform: str,
    config_path: Path | None,
    force: bool,
) -> dict:
    entry = {
        "command": sys.executable,
        "args": ["-m", "drift_gate", "serve", "--repo", str(repo)],
        "env": {"PYTHONUTF8": "1"},
    }

    if platform in ("codex", "local"):
        config_path = config_path or repo / ".mcp.json"
        config = _read_json_file(config_path)
        servers = config.setdefault("mcpServers", {})
        if "drift-gate" in servers and not force:
            _write_stdout(f"Drift Gate MCP entry already exists: {config_path}")
            _write_stdout("Use --force to replace it.")
            sys.exit(1)
        servers["drift-gate"] = entry
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return {"kind": "file", "path": config_path, "entry": entry}

    if platform == "claude-code":
        return {"kind": "snippet", "entry": {"drift-gate": entry}}

    print(f"ERROR: unsupported platform: {platform}", file=sys.stderr)
    sys.exit(2)


def _select_init_preset(requested: str, recommendations: dict) -> str:
    if requested != "auto":
        return requested
    presets = recommendations["presets"]
    if len(presets) == 1 and presets[0] in POLICY_PRESETS:
        return presets[0]
    return "fullstack"


def recommend_preset(repo_root: Path, requested: str = "auto") -> dict:
    """Starter-policy choice and repository recommendations for ``repo_root``.

    Independent of the working directory, so GUIs can preview what ``init`` would write.
    """
    recommendations = _repo_recommendations(repo_root)
    return {
        "preset": _select_init_preset(requested, recommendations),
        "recommendations": recommendations,
    }


def _repo_recommendations(repo_root: Path) -> dict:
    paths = set(_repo_paths(repo_root))
    frameworks = _detect_frameworks(paths, repo_root)
    presets = []

    if _has_any(paths, ["prisma/schema.prisma", "db/**", "database/migrations/**", "alembic/versions/**"]):
        presets.append("db")
    if _has_any(paths, ["src/routes/**", "app/api/**", "openapi/**", "proto/**"]):
        presets.append("api")
    if _has_any(paths, [".github/workflows/**", "Dockerfile", "Dockerfile.*", "infra/**", "terraform/**", "k8s/**", "helm/**"]):
        presets.append("ci")
    if _has_any(paths, [".env.example", ".env", "config/**", "src/config/**", "**/settings.py"]):
        presets.append("env")
    if _has_any(paths, ["src/auth/**", "**/rbac/**", "**/permissions/**", "**/policy/**"]):
        presets.append("auth")

    docs_paths = _recommend_docs_paths(paths, frameworks, presets)
    return {
        "presets": presets or ["fullstack"],
        "frameworks": frameworks or ["unknown"],
        "docs_paths": docs_paths,
    }


def _format_recommendations(recommendations: dict) -> str:
    lines = [
        "Repo recommendations:",
        f"  presets: {', '.join(recommendations['presets'])}",
        f"  frameworks: {', '.join(recommendations['frameworks'])}",
        "  docs paths:",
    ]
    lines.extend(f"    - {path}" for path in recommendations["docs_paths"])
    return "\n".join(lines)


def _detect_frameworks(paths: set[str], repo_root: Path | None = None) -> list[str]:
    frameworks = []
    base = repo_root if repo_root is not None else Path(".")
    package_json = base / "package.json"
    pyproject = base / "pyproject.toml"
    requirements = base / "requirements.txt"

    package_text = package_json.read_text(encoding="utf-8") if package_json.exists() else ""
    pyproject_text = pyproject.read_text(encoding="utf-8") if pyproject.exists() else ""
    requirements_text = requirements.read_text(encoding="utf-8") if requirements.exists() else ""
    python_deps = f"{pyproject_text}\n{requirements_text}".lower()

    if "fastapi" in python_deps or _has_any(paths, ["**/main.py", "**/api.py"]) and "fastapi" in python_deps:
        frameworks.append("FastAPI")
    if "django" in python_deps or _has_any(paths, ["manage.py", "**/settings.py"]):
        frameworks.append("Django")
    if "express" in package_text:
        frameworks.append("Express")
    if "next" in package_text or _has_any(paths, ["next.config.js", "next.config.mjs", "app/**", "pages/**"]):
        frameworks.append("Next.js")
    if "rails" in paths or _has_any(paths, ["Gemfile", "config/routes.rb", "app/controllers/**"]):
        frameworks.append("Rails")
    return sorted(set(frameworks))


def _recommend_docs_paths(
    paths: set[str],
    frameworks: list[str],
    presets: list[str],
) -> list[str]:
    docs = []
    if "api" in presets or any(f in frameworks for f in ("FastAPI", "Express", "Next.js", "Django", "Rails")):
        docs.extend(["docs/api/**", "docs/spec.md", "openapi/**"])
    if "db" in presets:
        docs.extend(["docs/database/**", "docs/runbook/**"])
    if "env" in presets:
        docs.extend([".env.example", "docs/deployment/**"])
    if "ci" in presets:
        docs.extend(["docs/ops/**", "docs/runbook/**"])
    if "auth" in presets:
        docs.extend(["docs/security/**", "SECURITY.md"])
    if _has_any(paths, ["README.md"]):
        docs.append("README.md")
    return sorted(set(docs)) or ["docs/**", "README.md"]


def _has_any(paths: set[str], patterns: list[str]) -> bool:
    return any(match_glob(path, pattern) for path in paths for pattern in patterns)


def _repo_paths(repo_root: Path) -> list[str]:
    ignored_dirs = {
        ".git", ".hg", ".svn", "__pycache__", ".pytest_cache",
        ".mypy_cache", ".ruff_cache", "node_modules", "dist", "build",
        ".venv", "venv",
    }
    paths = []
    for path in repo_root.rglob("*"):
        if any(part in ignored_dirs for part in path.parts):
            continue
        if path.is_file():
            paths.append(path.relative_to(repo_root).as_posix())
    return paths
