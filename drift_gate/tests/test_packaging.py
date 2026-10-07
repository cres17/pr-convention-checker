"""Regression checks for package paths and a smoke check that must really scan."""
import importlib.util
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from drift_gate.adapters import grammar_resources as resources
from drift_gate.desktop.resources import WEB_ROOT


def verifier():
    path = Path(__file__).resolve().parents[2] / "packaging" / "verify_package.py"
    spec = importlib.util.spec_from_file_location("package_verifier", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ui_location_is_independent_of_the_entrypoint(monkeypatch):
    import drift_gate.desktop as desktop
    # A frozen entrypoint is at bundle/web_app.py, outside drift_gate/desktop.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert WEB_ROOT == Path(desktop.__file__).parent / "web"
    assert WEB_ROOT != Path(sys.argv[0]).parent / "web"


@pytest.fixture
def bundled(tmp_path, monkeypatch):
    resources.bundled_grammar_directory.cache_clear()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("TREE_SITTER_LANGUAGE_PACK_LIBS_DIR", str(tmp_path / "user-libraries"))
    directory = tmp_path / "drift_gate" / "grammars"
    directory.mkdir(parents=True)
    names = [resources.grammar_library_name(lang) for lang in resources.SUPPORTED_GRAMMARS]
    for name in names:
        (directory / name).write_bytes(b"grammar")
    digest = hashlib.sha256(b"grammar").hexdigest()
    monkeypatch.setattr(resources, "expected_hashes", lambda version: (
        {name: digest for name in names} if version == "1.20.0" else {}))
    manifest = {"languages": list(resources.SUPPORTED_GRAMMARS), "version": "1.20.0",
                "platform": resources.platform_key(),
                "libraries": [{"name": name, "source_sha256": digest, "sha256": digest} for name in names]}
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    yield directory, manifest
    resources.bundled_grammar_directory.cache_clear()


@pytest.mark.parametrize("platform,expected", [("win32", "tree_sitter_python.dll"),
                                               ("darwin", "libtree_sitter_python.dylib"),
                                               ("linux", "libtree_sitter_python.so")])
def test_native_library_names_across_platforms(platform, expected):
    assert resources.grammar_library_name("python", platform) == expected


def test_frozen_parser_configures_bundled_library_before_loading(bundled, monkeypatch):
    import os
    directory, _ = bundled
    seen = []
    def get_parser(language):
        seen.append((language, os.environ["TREE_SITTER_LANGUAGE_PACK_LIBS_DIR"]))
        return "parser"
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack",
                        SimpleNamespace(__version__="1.20.0", get_parser=get_parser))
    assert resources.get_parser("typescript") == "parser"
    assert seen == [("typescript", str(directory))]
    assert os.environ["TREE_SITTER_LANGUAGE_PACK_LIBS_DIR"].endswith("user-libraries")


def packaging_module(name, monkeypatch):
    directory = Path(__file__).resolve().parents[2] / "packaging"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location(name, directory / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_downloaded_bytes_are_checked_before_any_native_load(tmp_path, monkeypatch):
    module = packaging_module("prepare_parsers", monkeypatch)
    names = [resources.grammar_library_name(lang) for lang in resources.SUPPORTED_GRAMMARS]
    digest = hashlib.sha256(b"reviewed").hexdigest()
    for name in names:
        (tmp_path / name).write_bytes(b"reviewed")
    (tmp_path / names[-1]).write_bytes(b"changed")
    monkeypatch.setattr(module, "download_libraries", lambda: None)
    monkeypatch.setattr(module, "cache_dir", lambda: str(tmp_path))
    monkeypatch.setattr(module, "expected_hashes", lambda version: {name: digest for name in names})
    loaded = []
    monkeypatch.setattr(module, "get_parser", lambda lang: loaded.append(lang))
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        module.prepare(tmp_path / "staged")
    assert loaded == []


def test_post_signing_seal_preserves_reviewed_source_pins(bundled, monkeypatch):
    directory, manifest = bundled
    module = packaging_module("seal_parsers", monkeypatch)
    target = directory / manifest["libraries"][0]["name"]
    target.write_bytes(b"grammar-signature")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        resources.validate_grammar_manifest(directory)
    module.seal(directory)
    sealed = resources.validate_grammar_manifest(directory)
    assert sealed["libraries"][0]["source_sha256"] == manifest["libraries"][0]["source_sha256"]
    assert sealed["libraries"][0]["sha256"] != manifest["libraries"][0]["sha256"]


def test_unknown_version_or_platform_never_accepts_new_downloads():
    with pytest.raises(RuntimeError, match="version"):
        resources.expected_hashes("future-version")
    with pytest.raises(RuntimeError, match="platform"):
        resources.expected_hashes("1.20.0", "unsupported")


def test_checksum_pins_cover_the_supported_native_platforms():
    for key, platform in [("darwin-arm64", "darwin"), ("darwin-x86_64", "darwin"),
                          ("win32-x86_64", "win32"), ("linux-x86_64", "linux")]:
        pins = resources.expected_hashes("1.20.0", key)
        assert set(pins) == {resources.grammar_library_name(lang, platform) for lang in resources.SUPPORTED_GRAMMARS}
        assert all(len(value) == 64 and int(value, 16) >= 0 for value in pins.values())


@pytest.mark.parametrize("damage", ["missing-file", "missing-language", "missing-entry", "wrong-version",
                                   "wrong-source-hash", "wrong-file-hash", "modified-file", "duplicate", "platform"])
def test_broken_bundle_fails_before_any_download(bundled, monkeypatch, damage):
    directory, manifest = bundled
    if damage == "missing-file":
        (directory / manifest["libraries"][0]["name"]).unlink()
    elif damage == "missing-language":
        manifest["languages"].pop()
    elif damage == "missing-entry":
        manifest["libraries"].pop()
    elif damage == "wrong-version":
        manifest["version"] = "wrong"
    elif damage == "wrong-source-hash":
        manifest["libraries"][0]["source_sha256"] = "0" * 64
    elif damage == "wrong-file-hash":
        manifest["libraries"][0]["sha256"] = "0" * 64
    elif damage == "modified-file":
        (directory / manifest["libraries"][0]["name"]).write_bytes(b"grammarX")
    elif damage == "duplicate":
        manifest["libraries"].append(manifest["libraries"][0])
    else:
        manifest["platform"] = "foreign"
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    def forbidden(_):
        pytest.fail("A broken frozen app must not try to download a parser")
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack",
                        SimpleNamespace(__version__="1.20.0", get_parser=forbidden))
    with pytest.raises(RuntimeError):
        resources.get_parser("python")


def valid_result(module):
    def phase(number, changed):
        return {"result": "warn", "execution": {"run_id": f"{number:032x}", "status": "success"},
                "scan_metrics": {"scanned_files": 2},
                "violations": [{"rule_id": "offline-api-docs", "trigger_files": [changed]}]}
    signature = phase(2, {"path": "src/api.py", "status": "modified", "previous_path": None,
                          "patch": "@@ -1,4 +1,6 @@\n def api(a,\n+        *extra,\n         b=1,\n+        **options,\n ):\n     return a\n"})
    rename = phase(3, {"path": "docs/api.py", "status": "renamed", "previous_path": "src/api.py",
                       "patch": "diff --git a/src/api.py b/docs/api.py\nsimilarity index 100%\nrename from src/api.py\nrename to docs/api.py\n"})
    for result, path in ((signature, 'src/api.py'), (rename, 'docs/api.py')):
        result['execution']['input_capture'] = {'artifacts': [
            {'path': path, 'role': 'patch'},
            {'path': 'docs/api.md', 'role': 'patch', 'observed_text_bytes': 0},
            {'path': 'docs/api.md', 'role': 'after-source', 'state': 'absent'}]}
    grammar_capture = {'artifacts': [
        *({'path': 'src/' + name, 'role': 'patch'} for name in module.SOURCES),
        {'path': 'docs/api.md', 'role': 'patch', 'observed_text_bytes': 0},
        {'path': 'docs/api.md', 'role': 'after-source', 'state': 'absent'}]}
    return {"frozen": True, "bridge_ready": True, "ui_text": "검사 완료",
            "verification": {"run_id": "a" * 32, "repository": "/fixture"},
            "network_probes": [{"error": "blocked"}, {"error": "blocked"}],
            "hardening_checks": [{"case": "signature", "result": signature}, {"case": "rename", "result": rename}],
            "scan": {"repository": "/fixture", "result": {"result": "warn",
                     "execution": {"run_id": "1" * 32, "status": "success", 'input_capture': grammar_capture},
                     "violations": [{"rule_id": "offline-api-docs"}],
                     "scan_metrics": {'scanned_files': 9, "analysis_notes": [
                         *({'path': "src/" + name, "method": "grammar+heuristic"} for name in module.SOURCES),
                         {'path': 'docs/api.md', 'method': 'unavailable'}]}}}}


@pytest.mark.parametrize("damage", ["not-frozen", "no-ui", "no-bridge", "network", "fallback", "missing-file", "gate", "no-violation"])
def test_package_check_rejects_false_success(damage):
    module = verifier()
    result = valid_result(module)
    if damage == "not-frozen":
        result["frozen"] = False
    elif damage == "no-ui":
        result["ui_text"] = ""
    elif damage == "no-bridge":
        result["bridge_ready"] = False
    elif damage == "network":
        result["network_probes"] = []
    elif damage == "fallback":
        result["scan"]["result"]["scan_metrics"]["analysis_notes"][0]["method"] = "heuristic"
    elif damage == "gate":
        result["scan"]["result"]["result"] = "pass"
    elif damage == "no-violation":
        result["scan"]["result"]["violations"] = []
    else:
        result["scan"]["result"]["scan_metrics"]["analysis_notes"].pop()
    with pytest.raises(RuntimeError):
        module.validate(result)


def test_offline_fixture_checks_every_supported_language(tmp_path):
    from tree_sitter_language_pack import get_parser
    module = verifier()
    module.fixture(tmp_path / "repo")
    assert len(module.SOURCES) == len(resources.SUPPORTED_GRAMMARS)
    for language, source in zip(resources.SUPPORTED_GRAMMARS, module.SOURCES.values()):
        assert not get_parser(language).parse(source.encode()).root_node.has_error, language
    module.validate(valid_result(module))

@pytest.mark.parametrize('damage', ['path-escape', 'symlink', 'oversized'])
def test_candidate_collection_never_extracts_unsafe_archive_entries(tmp_path, monkeypatch, damage):
    import io
    import tarfile
    zstandard = pytest.importorskip('zstandard')
    module = packaging_module('collect_parser_hashes', monkeypatch)
    archive = io.BytesIO()
    name = resources.grammar_library_name('python')
    with tarfile.open(fileobj=archive, mode='w') as bundle:
        entry = tarfile.TarInfo('../' + name if damage == 'path-escape' else name)
        if damage == 'symlink':
            entry.type = tarfile.SYMTYPE
            entry.linkname = str(tmp_path / 'escape')
        elif damage == 'oversized':
            entry.size = 32 * 1024 * 1024 + 1
        bundle.addfile(entry)
    compressed = zstandard.ZstdCompressor().compress(archive.getvalue())
    monkeypatch.setattr(module, 'cache_dir', lambda: str(tmp_path / 'cache'))
    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda *args, **kwargs: io.BytesIO(compressed))
    with pytest.raises(ValueError):
        module.download_libraries()
    assert not (tmp_path / name).exists()
    assert not (tmp_path / 'escape').exists()

@pytest.mark.skipif(sys.platform == 'win32', reason='Unix directory write permissions')
def test_mac_framework_versions_stay_immutable_after_packaging(tmp_path, monkeypatch):
    module = packaging_module('seal_parsers', monkeypatch)
    directory = tmp_path / 'QtWebEngineCore.framework/Versions'
    resources = directory / 'A/Resources'
    resources.mkdir(parents=True)
    (resources / 'resource.pak').write_bytes(b'resource')
    (directory / 'Resources').mkdir()
    monkeypatch.setattr(module.sys, 'platform', 'darwin')
    module.protect_webengine_versions(tmp_path)
    try:
        assert not (directory.stat().st_mode & 0o222)
        assert not (directory / 'Resources').exists()
        assert (resources / 'resource.pak').read_bytes() == b'resource'
    finally:
        directory.chmod(0o755)


def test_mac_framework_cleanup_never_discards_real_resources(tmp_path, monkeypatch):
    module = packaging_module('seal_parsers', monkeypatch)
    directory = tmp_path / 'QtWebEngineCore.framework/Versions/Resources'
    directory.mkdir(parents=True)
    target = directory / 'keep.pak'
    target.write_bytes(b'keep')
    monkeypatch.setattr(module.sys, 'platform', 'darwin')
    with pytest.raises(OSError):
        module.protect_webengine_versions(tmp_path)
    assert target.read_bytes() == b'keep'


@pytest.mark.parametrize("damage", ["old-challenge", "wrong-repository", "reused-initial", "reused-id",
                                     "duplicate-phase", "reordered-phase", "wrong-rename", "wrong-signature",
                                     "extra-change", "missing-id", "failed-execution",
                                     "extra-observation", "missing-document-observation"])
def test_package_check_binds_each_phase_to_fresh_expected_input(damage):
    import copy
    module = verifier()
    result = valid_result(module)
    expected = dict(result["verification"])
    checks = result["hardening_checks"]
    if damage == "old-challenge":
        result["verification"]["run_id"] = "b" * 32
    elif damage == "wrong-repository":
        result["scan"]["repository"] = "/other"
    elif damage == "reused-initial":
        checks[0]["result"] = copy.deepcopy(result["scan"]["result"])
    elif damage == "reused-id":
        checks[1]["result"]["execution"] = dict(checks[0]["result"]["execution"])
    elif damage == "duplicate-phase":
        checks.append(copy.deepcopy(checks[0]))
    elif damage == "reordered-phase":
        checks.reverse()
    elif damage == "wrong-rename":
        checks[1]["result"]["violations"][0]["trigger_files"][0]["previous_path"] = "other.py"
    elif damage == "wrong-signature":
        checks[0]["result"]["violations"][0]["trigger_files"][0]["patch"] = "@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    elif damage == "extra-change":
        checks[0]["result"]["violations"][0]["trigger_files"][0]["patch"] += "+extra = 2\n"
    elif damage == "missing-id":
        checks[0]["result"].pop("execution")
    elif damage == 'extra-observation':
        checks[0]['result']['execution']['input_capture']['artifacts'].append(
            {'path': 'unexpected.py', 'role': 'patch'})
    elif damage == 'missing-document-observation':
        checks[0]['result']['execution']['input_capture']['artifacts'].pop()
    else:
        checks[0]["result"]["execution"]["status"] = "input_error"
    with pytest.raises(RuntimeError):
        module.validate(result, expected_identity=expected)


def test_actual_package_phase_preparation_and_scans_preserve_exact_observation_scope(tmp_path):
    pytest.importorskip('PySide6')
    from drift_gate.desktop.package_check import PackageCheck
    from drift_gate.desktop.package_check_contract import validate_phase
    from drift_gate.desktop.service import scan_repository
    module = verifier()
    module.fixture(tmp_path)
    control = valid_result(module)
    control['scan']['result'] = scan_repository(tmp_path).result.to_dict()
    state = SimpleNamespace(repository=str(tmp_path), phase='grammar',
                            window=SimpleNamespace(bridge=SimpleNamespace(startScan=lambda *args: None)))
    seen = {validate_phase('grammar', control['scan']['result'], set())}
    control['hardening_checks'] = []
    for case in ['signature', 'rename']:
        PackageCheck.prepare_next_scan(state)
        assert state.phase == case
        result = scan_repository(tmp_path).result.to_dict()
        seen.add(validate_phase(case, result, seen))
        assert result['scan_metrics']['scanned_files'] == 2
        control['hardening_checks'].append({'case': case, 'result': result})
    module.validate(control)


def test_package_verifier_preserves_old_output_without_launching(tmp_path, monkeypatch):
    module = verifier()
    executable = tmp_path / "noop"
    executable.write_text("exit 0")
    output = tmp_path / "evidence"
    output.mkdir()
    report = output / "result.json"
    report.write_text(json.dumps(valid_result(module)))
    before = report.read_bytes()
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: pytest.fail("Old evidence must be rejected before launch"))
    with pytest.raises(FileExistsError):
        module.verify(executable, output)
    assert report.read_bytes() == before


@pytest.mark.parametrize("fresh", [False, True])
def test_package_runner_requires_matching_challenge_and_fixture(tmp_path, monkeypatch, fresh):
    from contextlib import contextmanager
    module = verifier()
    from drift_gate.desktop.package_git_check import run_git_controls
    git_controls = run_git_controls() if fresh else None
    monkeypatch.setattr(module.sys, "platform", "darwin")
    executable = tmp_path / "Noop.app/Contents/MacOS/Noop"
    executable.parent.mkdir(parents=True)
    executable.touch()
    grammars = executable.parent.parent / "Frameworks/drift_gate/grammars"
    grammars.mkdir(parents=True)
    (grammars / "manifest.json").write_text('{"libraries": []}')
    @contextmanager
    def isolation(*args):
        yield [], "test-only simulated isolation"
    monkeypatch.setattr(module, "network_block", isolation)
    monkeypatch.setattr(module, "fixture", lambda directory: directory.mkdir())
    class OldResultProcess:
        def __init__(self, args, **kwargs):
            report = valid_result(module)
            if git_controls is not None:
                report['git_object_checks'] = git_controls
            if fresh:
                report["verification"] = {"run_id": kwargs["env"]["DRIFT_GATE_PACKAGE_CHECK_ID"],
                                          "repository": str(Path(args[-2]).resolve())}
                report["scan"]["repository"] = report["verification"]["repository"]
            Path(args[-1]).write_text(json.dumps(report))
        def wait(self, timeout=None):
            return 0
    monkeypatch.setattr(module.subprocess, "Popen", OldResultProcess)
    if fresh:
        module.verify(executable, tmp_path / "fresh-output")
        assert json.loads((tmp_path / "fresh-output/result.json").read_text())["fresh_cache_files"] == []
    else:
        with pytest.raises(RuntimeError, match="different verification run"):
            module.verify(executable, tmp_path / "fresh-output")
