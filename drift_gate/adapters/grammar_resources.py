"""Use the shipped grammars before a frozen app probes tree-sitter availability."""
from functools import lru_cache
import json
import os
from pathlib import Path
import sys


SUPPORTED_GRAMMARS = ("python", "typescript", "tsx", "javascript", "go", "java", "kotlin", "ruby")


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
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if set(manifest["languages"]) != set(SUPPORTED_GRAMMARS):
        raise RuntimeError("The installed app is missing required grammar declarations")
    required = {grammar_library_name(language) for language in SUPPORTED_GRAMMARS}
    if {library["name"] for library in manifest["libraries"]} != required:
        raise RuntimeError("The installed app is missing required grammar libraries")
    for library in manifest["libraries"]:
        name = library["name"]
        if Path(name).name != name or not (directory / name).is_file():
            raise RuntimeError("The installed app is missing a bundled grammar library")
    # The native package reads this search path on its first grammar lookup.
    # It is deliberately set before importing/probing the package, not after.
    os.environ["TREE_SITTER_LANGUAGE_PACK_LIBS_DIR"] = str(directory)
    from tree_sitter_language_pack import __version__
    if manifest["version"] != __version__:
        raise RuntimeError("The installed grammar version does not match the language pack")
    return directory


def get_parser(language):
    bundled_grammar_directory()
    from tree_sitter_language_pack import get_parser as load_parser

    return load_parser(language)
