"""doctor 명령: 정책 파일과 저장소 상태를 점검해 경고를 출력한다."""
import sys
from pathlib import Path

from drift_gate.adapters.cli.output import write_stdout as _write_stdout
from drift_gate.adapters.cli.setup_command import _repo_paths
from drift_gate.adapters.git.client import GitAdapter
from drift_gate.adapters.policy_loader import load_policy
from drift_gate.core.policy.loader import PolicyLoadError
from drift_gate.core.policy.validator import validate
from drift_gate.utils.glob_matcher import match_glob


def _run_doctor(args) -> None:
    checks = []
    errors = []
    warnings = []

    policy_path = Path(args.policy)
    if policy_path.exists():
        checks.append(f"OK policy file found: {policy_path}")
        try:
            policy = load_policy(policy_path)
            # load_warnings are already a subset of validation.warnings — avoid duplication
            validation = validate(policy)
            if validation.ok:
                checks.append(f"OK policy has {len(policy.rules)} rule(s)")
            warnings.extend(validation.warnings)
            errors.extend(validation.errors)
            warnings.extend(_broad_glob_warnings(policy))
            warnings.extend(_dead_rule_warnings(policy, Path.cwd()))
        except PolicyLoadError as exc:
            errors.append(f"policy failed to load: {exc}")
    else:
        errors.append(f"policy file missing: {policy_path}")

    if _git_ok(["git", "rev-parse", "--is-inside-work-tree"]):
        checks.append("OK git repository detected")
        if _git_ok(["git", "rev-parse", "--verify", "--quiet", args.base]):
            checks.append(f"OK git base exists: {args.base}")
        else:
            warnings.append(f"git base was not found locally: {args.base}")
        try:
            changed_files = GitAdapter().get_changed_files(args.base)
            checks.append(f"OK local diff collected: {len(changed_files)} file(s)")
        except Exception as exc:
            errors.append(f"local diff collection failed: {exc}")
    else:
        errors.append("not inside a git repository")

    if Path("action.yml").exists():
        checks.append("OK action.yml found")
    else:
        warnings.append("action.yml not found")

    if Path(".github/workflows").exists():
        checks.append("OK GitHub workflow directory found")
    else:
        warnings.append("GitHub workflow directory not found")

    if _console_entrypoints_ok():
        checks.append("OK console entrypoints import")
    else:
        warnings.append("console entrypoint import failed")

    if Path("drift_gate/tests/fixtures").exists():
        checks.append("OK benchmark fixtures found")
    else:
        warnings.append("benchmark fixtures not found")

    lines = ["# Drift Gate Doctor", ""]
    if checks:
        lines += ["## Checks", ""]
        lines.extend(f"- {item}" for item in checks)
        lines.append("")
    if warnings:
        lines += ["## Warnings", ""]
        lines.extend(f"- {item}" for item in warnings)
        lines.append("")
    if errors:
        lines += ["## Errors", ""]
        lines.extend(f"- {item}" for item in errors)
        lines.append("")
        lines.append("Doctor result: FAIL")
    else:
        lines.append("Doctor result: PASS")

    _write_stdout("\n".join(lines))
    sys.exit(1 if errors else 0)


def _console_entrypoints_ok() -> bool:
    try:
        from drift_gate.adapters.cli.runner import run_cli as _cli
        from drift_gate.adapters.eval.runner import run_eval as _eval
    except Exception:
        return False
    return callable(_cli) and callable(_eval)


def _git_ok(args: list[str]) -> bool:
    import subprocess

    try:
        subprocess.check_output(args, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False


def _broad_glob_warnings(policy) -> list[str]:
    warnings = []
    broad = {"**", "**/*", "src/**", "app/**", "*"}
    for rule in policy.rules:
        for pattern in rule.when.any_changed:
            if pattern in broad:
                warnings.append(
                    f"rule '{rule.id}' uses broad trigger glob '{pattern}'; "
                    "consider a narrower contract boundary"
                )
    return warnings


def _dead_rule_warnings(policy, repo_root: Path) -> list[str]:
    repo_paths = _repo_paths(repo_root)
    if not repo_paths:
        return []

    warnings = []
    for rule in policy.rules:
        matched = any(
            match_glob(path, pattern)
            for path in repo_paths
            for pattern in rule.when.any_changed
        )
        if not matched:
            warnings.append(
                f"rule '{rule.id}' appears inactive: no repository files match "
                f"when.any_changed patterns {rule.when.any_changed}"
            )
    return warnings
