"""Execution identity and atomic outputs shared by CLI and self-check."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid


def identity():
    return {'schema_version': 2, 'run_id': uuid.uuid4().hex,
            'started_at': datetime.now(timezone.utc).isoformat()}


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def atomic_text(path, text):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                         delete=False) as stream:
            name = stream.name
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
    finally:
        if name and Path(name).exists():
            Path(name).unlink()


def atomic_json(path, data):
    atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
