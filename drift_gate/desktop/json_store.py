"""Atomic local JSON persistence shared by baselines, history and recovery."""
import json
from pathlib import Path
import tempfile


def write_json(target: Path, data: dict) -> None:
    """Atomic replace, so a crash never leaves a half-written file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=target.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
