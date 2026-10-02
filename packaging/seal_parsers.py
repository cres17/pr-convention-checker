"""Record post-packaging hashes after native rewriting/signing has finished.

Source pins were checked before PyInstaller. These hashes detect installed-file
corruption; they are not a signature or a new supply-chain trust anchor.
"""
import argparse
import json
from pathlib import Path
import sys

from drift_gate.adapters.grammar_resources import file_sha256, validate_grammar_manifest


def seal(directory):
    manifest = validate_grammar_manifest(directory, verify_files=False)
    for library in manifest["libraries"]:
        library["sha256"] = file_sha256(directory / library["name"])
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    validate_grammar_manifest(directory)


def protect_webengine_versions(bundle):
    """Do not let Qt create a fake framework version during first launch.

    Qt 6.11.2 may create Versions/Resources, which deep signature verification
    treats as another (invalid) framework version. Version contents remain
    readable; application settings/caches belong outside the signed bundle.
    """
    if sys.platform != "darwin":
        return
    for directory in bundle.rglob("QtWebEngineCore.framework/Versions"):
        misplaced = directory / "Resources"
        if misplaced.exists() and not misplaced.is_symlink():
            misplaced.rmdir()  # Fail on nonempty content instead of discarding it.
        directory.chmod(directory.stat().st_mode & ~0o222)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    bundle = parser.parse_args().bundle
    directories = list(bundle.rglob("drift_gate/grammars"))
    if not directories:
        raise SystemExit("No bundled grammars found")
    for directory in directories:
        seal(directory)
    protect_webengine_versions(bundle)
