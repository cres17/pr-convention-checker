"""Run a frozen app's first real scan with a fresh cache and OS network block."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

from drift_gate.desktop.package_check_contract import validate_phases, validate_observation_scope


SOURCES = {
    "api.py": "def api(value: str) -> str:\n    return value\n",
    "api.ts": "export function api(value: string): string { return value; }\n",
    "view.tsx": "export function View() { return <div>ok</div>; }\n",
    "api.js": "export function api(value) { return value; }\n",
    "api.go": "package main\nfunc API(value string) string { return value }\n",
    "Api.java": 'public class Api { public String get() { return "ok"; } }\n',
    "Api.kt": 'class Api {\n  fun get(): String {\n    return "ok"\n  }\n}\n',
    "api.rb": 'class Api\n  def get\n    "ok"\n  end\nend\n',
}


def fixture(directory):
    (directory / "src").mkdir(parents=True)
    (directory / ".drift-gate.yml").write_text(
        "rules:\n  - id: offline-api-docs\n    when:\n      any_changed: ['src/**']\n"
        "    require:\n      groups:\n        - name: API documentation\n"
        "          any_changed: ['docs/api.md']\n    severity: major\n"
        "    message: API changes require documentation\n", encoding="utf-8")
    for name in SOURCES:
        (directory / "src" / name).touch()
    for args in [("init",), ("add", "."),
                 ("-c", "user.name=Package check", "-c", "user.email=package-check@example.invalid",
                  "commit", "-m", "Baseline")]:
        subprocess.run(["git", "-C", str(directory), *args], check=True, capture_output=True)
    for name, content in SOURCES.items():
        (directory / "src" / name).write_text(content, encoding="utf-8")


def powershell(script):
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"Windows network-isolation command failed: {result.stderr}")
    return result


def ps_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


@contextmanager
def network_block(executable, directory):
    if sys.platform == "darwin":
        profile = directory / "offline.sb"
        profile.write_text('(version 1)\n(allow default)\n(deny network-outbound)\n', encoding="utf-8")
        yield ["/usr/bin/sandbox-exec", "-f", str(profile)], "macOS sandbox-exec outbound deny"
    elif sys.platform == "win32":
        if os.environ.get("GITHUB_ACTIONS") != "true":
            raise RuntimeError("Firewall-changing installed-app checks are restricted to GitHub CI")
        name = "DriftGate-package-check-" + uuid.uuid4().hex
        programs = [executable, *executable.parent.rglob("QtWebEngineProcess.exe")]
        try:
            script = "$ErrorActionPreference='Stop'; "
            for index, program in enumerate(programs):
                rule = ps_literal(f"{name}-{index}")
                script += (f"New-NetFirewallRule -Name {rule} -DisplayName {rule} -Direction Outbound "
                           f"-Action Block -Enabled True -Profile Any -Program {ps_literal(program)} | Out-Null; ")
            script += f"Get-NetFirewallRule -Name {ps_literal(name + '-*')} | Select-Object Name,Enabled,Action,Direction | ConvertTo-Json"
            evidence = powershell(script).stdout
            (directory / "firewall.json").write_text(evidence, encoding="utf-8")
            yield [], "Windows Defender Firewall program outbound block"
        finally:
            powershell(f"Get-NetFirewallRule -Name {ps_literal(name + '-*')} -ErrorAction SilentlyContinue | Remove-NetFirewallRule")
    else:
        raise RuntimeError("Installed-app network blocking is supported on macOS and Windows")


def validate(result, *, expected_identity=None):
    if expected_identity is not None:
        if result.get("verification") != expected_identity:
            raise RuntimeError("Package result belongs to a different verification run or fixture")
        if result.get("scan", {}).get("repository") != expected_identity["repository"]:
            raise RuntimeError("Package scan belongs to a different fixture repository")
    if not result.get("frozen") or not result.get("bridge_ready") or not result.get("ui_text"):
        raise RuntimeError("The frozen app did not load its UI and QWebChannel")
    probes = result.get("network_probes", [])
    if len(probes) != 2 or not all(p.get("error") for p in probes):
        raise RuntimeError("External network blocking was not verified inside the app")
    gate = result["scan"]["result"]
    if gate.get("result") != "warn" or not any(v.get("rule_id") == "offline-api-docs" for v in gate.get("violations", [])):
        raise RuntimeError("The actual policy engine did not detect the missing API documentation")
    notes = result["scan"]["result"]["scan_metrics"]["analysis_notes"]
    expected = {f"src/{name}" for name in SOURCES}
    actual = {n["path"]: n for n in notes}
    validate_observation_scope(gate, expected)
    if (len(notes) != len(expected) + 1 or set(actual) != expected | {'docs/api.md'}
        or any(actual[path]['method'] != 'grammar+heuristic' for path in expected)
        or actual['docs/api.md']['method'] != 'unavailable'):
        raise RuntimeError(f"Installed-app grammar analysis failed: {notes}")
    validate_phases(result)


def verify(executable, output):
    executable = executable.resolve(strict=True)
    output.mkdir(parents=True, exist_ok=False)
    output = output.resolve()
    bundle = executable.parent.parent / "Frameworks" if sys.platform == "darwin" else executable.parent / "_internal"
    directory = bundle / "drift_gate" / "grammars"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["libraries"]:
        library = directory / entry["name"]
        if not library.is_file() or not library.stat().st_size:
            raise RuntimeError(f"Packaged grammar missing: {library}")
    (output / "bundled-grammars.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="driftgate-offline-check-") as temporary:
        root = Path(temporary)
        fixture(root / "fixture")
        identity = {"run_id": uuid.uuid4().hex, "repository": str((root / "fixture").resolve())}
        cache = root / "empty-parser-cache"
        cache.mkdir()
        env = {**os.environ, "DRIFT_GATE_PACKAGE_CHECK_ID": identity["run_id"], "TREE_SITTER_LANGUAGE_PACK_CACHE_DIR": str(cache),
               "TREE_SITTER_LANGUAGE_PACK_LIBS_DIR": str(root / "absent-user-libraries"),
               "QT_QPA_PLATFORM": "offscreen", "QTWEBENGINE_CHROMIUM_FLAGS": "--no-sandbox --disable-gpu"}
        report = output / "result.json"
        with network_block(executable, output) as (prefix, isolation):
            with (output / "app.log").open("wb") as log:
                process = subprocess.Popen([*prefix, str(executable), "--verify-package",
                                            str(root / "fixture"), str(report)], env=env,
                                           cwd=str(root), stdout=log, stderr=subprocess.STDOUT)
                try:
                    code = process.wait(timeout=75)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    raise RuntimeError("Packaged app never completed its actual first scan") from None
            if code != 0:
                raise RuntimeError(f"Packaged app failed ({code}); see {output / 'app.log'}")
        result = json.loads(report.read_text(encoding="utf-8"))
        validate(result, expected_identity=identity)
        from drift_gate.desktop.package_git_check import validate_git_controls
        validate_git_controls(result.get('git_object_checks', {}))
        cache_files = [str(p.relative_to(cache)) for p in cache.rglob("*") if p.is_file()]
        if any(Path(p).suffix in {".dll", ".dylib", ".so"} for p in cache_files):
            raise RuntimeError("The installed app populated its supposedly empty parser cache")
        result.update({"isolation": isolation, "fresh_cache_files": cache_files})
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"PASS: rendered packaged UI + native bridge + {len(SOURCES)} offline grammar analyses; {report}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--output", type=Path, default=Path("build/offline-check"))
    args = parser.parse_args()
    verify(args.executable, args.output)
