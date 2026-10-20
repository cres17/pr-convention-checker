"""Content identity of supplied observations; no file reads or authenticity claim."""
import json
from dataclasses import asdict
from hashlib import sha256


def source_identity(files):
    files = tuple(files)
    if len({file.path for file in files}) != len(files):
        raise ValueError('duplicate source paths')
    payload = [asdict(file) for file in sorted(files, key=lambda file: file.path)]
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True, allow_nan=False,
                             separators=(',', ':')).encode()).hexdigest()
