"""Regression checks for package paths and a smoke check that must really scan."""
import importlib.util
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
    manifest = {"languages": list(resources.SUPPORTED_GRAMMARS), "version": "1.20.0",
                "libraries": [{"name": name} for name in names]}
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


@pytest.mark.parametrize("damage", ["missing-file", "missing-language", "missing-entry", "wrong-version"])
def test_broken_bundle_fails_before_any_download(bundled, monkeypatch, damage):
    directory, manifest = bundled
    if damage == "missing-file":
        (directory / manifest["libraries"][0]["name"]).unlink()
    elif damage == "missing-language":
        manifest["languages"].pop()
    elif damage == "missing-entry":
        manifest["libraries"].pop()
    else:
        manifest["version"] = "wrong"
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    def forbidden(_):
        pytest.fail("A broken frozen app must not try to download a parser")
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack",
                        SimpleNamespace(__version__="1.20.0", get_parser=forbidden))
    with pytest.raises(RuntimeError):
        resources.get_parser("python")


def valid_result(module):
    return {"frozen": True, "bridge_ready": True, "ui_text": "검사 완료",
            "network_probes": [{"error": "blocked"}, {"error": "blocked"}],
            "scan": {"result": {"result": "warn", "violations": [{"rule_id": "offline-api-docs"}],
                                "scan_metrics": {"analysis_notes": [
                {"path": "src/" + name, "method": "grammar+heuristic"} for name in module.SOURCES]}}}}


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
