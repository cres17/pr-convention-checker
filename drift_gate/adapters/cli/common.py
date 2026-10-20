"""여러 명령이 함께 쓰는 입력 보조 함수."""
import json
import sys
from pathlib import Path


class CLIInputError(ValueError):
    """Invalid CLI input handled by the command boundary."""



def _parse_days(value: str, *, option: str = "--last") -> int:
    normalized = value.strip().lower()
    if normalized.endswith("d"):
        normalized = normalized[:-1]
    try:
        days = int(normalized)
    except ValueError as exc:
        raise CLIInputError(f"invalid {option} value: {value}") from exc
    return max(days, 1)


def _read_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON config {path}: {exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(data, dict):
        print(f"ERROR: JSON config root must be an object: {path}", file=sys.stderr)
        sys.exit(1)
    return data
