"""Download and stage the supported native grammars on the build machine."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil

from tree_sitter_language_pack import cache_dir, get_parser, __version__
from collect_parser_hashes import download_libraries

from drift_gate.adapters.grammar_resources import (
    SUPPORTED_GRAMMARS, grammar_library_name, expected_hashes, platform_key, file_sha256,
)


def prepare(output: Path):
    pins = expected_hashes(__version__)
    download_libraries()
    output.mkdir(parents=True, exist_ok=True)
    libraries = []
    for language in SUPPORTED_GRAMMARS:
        source = Path(cache_dir()) / grammar_library_name(language)
        if not source.is_file():
            raise RuntimeError(f"Downloaded grammar library not found: {source}")
        digest = file_sha256(source)
        if digest != pins.get(source.name):
            raise RuntimeError(f"Downloaded grammar checksum mismatch: {source.name}")
        target = output / source.name
        shutil.copy2(source, target)
        if file_sha256(target) != digest:
            raise RuntimeError(f"Staged grammar checksum mismatch: {target.name}")
        # PyInstaller/code signing may rewrite a native library's signature.
        libraries.append({"name": target.name, "source_sha256": digest, "sha256": digest})
    # Only after every downloaded byte has matched reviewed pins may native code load.
    os.environ["TREE_SITTER_LANGUAGE_PACK_LIBS_DIR"] = str(output.resolve())
    for language in SUPPORTED_GRAMMARS:
        get_parser(language).parse(b"\n")
    manifest = {"version": __version__, "platform": platform_key(), "languages": list(SUPPORTED_GRAMMARS), "libraries": libraries}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Staged {len(libraries)} grammars ({__version__}) in {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("build/parser-libraries"))
    prepare(parser.parse_args().output)
