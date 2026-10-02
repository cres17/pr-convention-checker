"""Record post-packaging hashes after native rewriting/signing has finished.

Source pins were checked before PyInstaller. These hashes detect installed-file
corruption; they are not a signature or a new supply-chain trust anchor.
"""
import argparse
import json
from pathlib import Path

from drift_gate.adapters.grammar_resources import file_sha256, validate_grammar_manifest


def seal(directory):
    manifest = validate_grammar_manifest(directory, verify_files=False)
    for library in manifest["libraries"]:
        library["sha256"] = file_sha256(directory / library["name"])
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    validate_grammar_manifest(directory)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    directories = list(parser.parse_args().bundle.rglob("drift_gate/grammars"))
    if not directories:
        raise SystemExit("No bundled grammars found")
    for directory in directories:
        seal(directory)
