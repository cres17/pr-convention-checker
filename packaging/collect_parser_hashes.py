"""Collect candidate hashes without loading downloaded native code.

These are review inputs, never automatically accepted trust anchors.
"""
import hashlib
import json
from pathlib import Path
import platform
import sys

from tree_sitter_language_pack import __version__, cache_dir, download
from drift_gate.adapters.grammar_resources import SUPPORTED_GRAMMARS, grammar_library_name


def collect():
    download(list(SUPPORTED_GRAMMARS))
    libraries = {grammar_library_name(lang): hashlib.sha256(
        (Path(cache_dir()) / grammar_library_name(lang)).read_bytes()).hexdigest()
        for lang in SUPPORTED_GRAMMARS}
    result = {"version": __version__, "platform": sys.platform,
              "machine": platform.machine(), "libraries": libraries}
    target = Path("build/parser-hash-candidate.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    collect()
