"""Download and stage the supported native grammars on the build machine."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

from tree_sitter_language_pack import DownloadError, cache_dir, download, get_parser, __version__

from drift_gate.adapters.grammar_resources import SUPPORTED_GRAMMARS, grammar_library_name


def prepare(output: Path):
    for attempt in range(3):
        try:
            download(list(SUPPORTED_GRAMMARS))
            for language in SUPPORTED_GRAMMARS:
                get_parser(language).parse(b"\n")
            break
        except DownloadError:
            if attempt == 2:
                raise
            print(f"Grammar download failed; retry {attempt + 1}/2", file=sys.stderr)
            time.sleep(attempt + 1)
    output.mkdir(parents=True, exist_ok=True)
    libraries = []
    for language in SUPPORTED_GRAMMARS:
        source = Path(cache_dir()) / grammar_library_name(language)
        if not source.is_file():
            raise RuntimeError(f"Downloaded grammar library not found: {source}")
        target = output / source.name
        shutil.copy2(source, target)
        # PyInstaller/code signing may rewrite a native library's signature.
        libraries.append({"name": target.name, "source_sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    manifest = {"version": __version__, "languages": list(SUPPORTED_GRAMMARS), "libraries": libraries}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Staged {len(libraries)} grammars ({__version__}) in {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("build/parser-libraries"))
    prepare(parser.parse_args().output)
