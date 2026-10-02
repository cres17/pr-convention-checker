"""Collect candidate hashes without loading downloaded native code.

These are review inputs, never automatically accepted trust anchors.
"""
import hashlib
import json
from pathlib import Path
import platform
import sys
import tarfile
import tempfile
import urllib.request
import time

from tree_sitter_language_pack import __version__, cache_dir
from drift_gate.adapters.grammar_resources import SUPPORTED_GRAMMARS, grammar_library_name


def download_libraries():
    """Read only the eight regular files; never unpack paths or load native code."""
    from zstandard import ZstdDecompressor
    names = {grammar_library_name(lang) for lang in SUPPORTED_GRAMMARS}
    destination = Path(cache_dir())
    if all((destination / name).is_file() for name in names):
        return
    machine = platform.machine().lower()
    machine = {"amd64": "x86_64", "aarch64": "arm64"}.get(machine, machine)
    system = {"darwin": "macos", "win32": "windows", "linux": "linux"}[sys.platform]
    url = f"https://github.com/xberg-io/tree-sitter-language-pack/releases/download/v{__version__}/parsers-{system}-{machine}.tar.zst"
    destination.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        try:
            with tempfile.TemporaryFile() as archive:
                with urllib.request.urlopen(url, timeout=60) as response:
                    size = 0
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > 64 * 1024 * 1024:
                            raise ValueError("Parser archive exceeded 64MB")
                        archive.write(chunk)
                archive.seek(0)
                found = set()
                with ZstdDecompressor().stream_reader(archive) as stream:
                    with tarfile.open(fileobj=stream, mode="r|") as bundle:
                        for member in bundle:
                            name = member.name.removeprefix("./")
                            if name not in names:
                                continue
                            if not member.isfile() or member.size > 32 * 1024 * 1024 or name in found:
                                raise ValueError("Invalid parser archive entry")
                            with bundle.extractfile(member) as source:
                                data = source.read()
                            # Atomic writes never leave a partially downloaded cache file.
                            target = destination / name
                            temporary = target.with_suffix(target.suffix + ".tmp")
                            temporary.write_bytes(data)
                            temporary.replace(target)
                            found.add(name)
                if found != names:
                    raise ValueError("Parser archive is missing required libraries")
                return
        except (OSError, urllib.error.URLError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def collect():
    download_libraries()
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
