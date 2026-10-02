"""Use the shipped grammars before a frozen app probes tree-sitter availability."""
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import sys
import platform as host_platform
from threading import RLock


SUPPORTED_GRAMMARS = ("python", "typescript", "tsx", "javascript", "go", "java", "kotlin", "ruby")
_load_lock = RLock()


def platform_key():
    machine = host_platform.machine().lower()
    machine = {"amd64": "x86_64", "aarch64": "arm64"}.get(machine, machine)
    return f"{sys.platform}-{machine}"


def expected_hashes(version, key=None):
    pins = json.loads(Path(__file__).with_name("parser_hashes.json").read_text(encoding="utf-8"))
    if version != pins["version"]:
        raise RuntimeError("Grammar version has no reviewed checksum pins")
    key = key or platform_key()
    if key not in pins["platforms"]:
        raise RuntimeError(f"Grammar platform has no reviewed checksum pins: {key}")
    return pins["platforms"][key]


def file_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_grammar_manifest(directory, *, verify_files=True):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("platform") != platform_key():
        raise RuntimeError("The installed grammar platform does not match this machine")
    pins = expected_hashes(manifest["version"])
    required = {grammar_library_name(language) for language in SUPPORTED_GRAMMARS}
    entries = manifest["libraries"]
    if (set(manifest["languages"]) != set(SUPPORTED_GRAMMARS)
            or len(entries) != len(required) or {lib["name"] for lib in entries} != required
            or set(pins) != required):
        raise RuntimeError("The installed app is missing required grammar declarations")
    for library in entries:
        name = library["name"]
        target = directory / name
        if Path(name).name != name or not target.is_file():
            raise RuntimeError("The installed app is missing a bundled grammar library")
        if library.get("source_sha256") != pins[name]:
            raise RuntimeError(f"Unreviewed grammar source checksum: {name}")
        if verify_files and library.get("sha256") != file_sha256(target):
            raise RuntimeError(f"Bundled grammar checksum mismatch: {name}")
    return manifest


def grammar_library_name(language, platform=None):
    platform = platform or sys.platform
    if platform == "win32":
        prefix, suffix = "", ".dll"
    elif platform == "darwin":
        prefix, suffix = "lib", ".dylib"
    else:
        prefix, suffix = "lib", ".so"
    return f"{prefix}tree_sitter_{language}{suffix}"


@lru_cache(maxsize=1)
def bundled_grammar_directory():
    if not getattr(sys, "frozen", False):
        return None
    directory = Path(sys._MEIPASS) / "drift_gate" / "grammars"
    manifest = validate_grammar_manifest(directory)
    from tree_sitter_language_pack import __version__
    if manifest["version"] != __version__:
        raise RuntimeError("The installed grammar version does not match the language pack")
    return directory


def get_parser(language):
    directory = bundled_grammar_directory()
    if directory is None:
        from tree_sitter_language_pack import get_parser as load_parser
        return load_parser(language)
    if language not in SUPPORTED_GRAMMARS:
        raise ValueError(f"Grammar is not shipped in this app: {language}")
    # Set the path only during native lookup; do not leave it for child processes.
    with _load_lock:
        key = "TREE_SITTER_LANGUAGE_PACK_LIBS_DIR"
        previous = os.environ.get(key)
        os.environ[key] = str(directory)
        try:
            from tree_sitter_language_pack import get_parser as load_parser
            return load_parser(language)
        finally:
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous
