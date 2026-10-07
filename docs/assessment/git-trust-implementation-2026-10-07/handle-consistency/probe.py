"""Record native path/handle metadata on a fixed temporary text fixture."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from drift_gate.adapters.snapshot import read_bounded_text

FIELDS = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')


def metadata(value):
    return {field: getattr(value, field) for field in FIELDS}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='driftgate-native-read-') as directory:
        path = Path(directory) / 'fixture.txt'
        path.touch()
        path.write_bytes(b'stable\r\n')
        info = path.stat()
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
        with path.open('rb') as stream:
            before = metadata(os.fstat(stream.fileno()))
            raw = stream.read()
            after = metadata(os.fstat(stream.fileno()))
        by_path = metadata(path.stat())
        with path.open('rb') as stream:
            reopened = metadata(os.fstat(stream.fileno()))
        mismatches = [field for field in FIELDS if after[field] != by_path[field]]
        stable = read_bounded_text(path) == raw.decode('utf-8') == 'stable\r\n'
        result = {'schema': 'native-read-metadata-v1', 'platform': sys.platform,
            'python': sys.version, 'first_handle': before, 'after_read_handle': after,
            'path_stat': by_path, 'reopened_handle': reopened,
            'heterogeneous_api_mismatches': mismatches,
            'old_guard_would_accept': before == after == by_path,
            'like_api_guard_accepts': before == after == reopened,
            'bounded_read_preserves_fixture': stable}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open('x', encoding='utf-8', newline='\n') as handle:
            json.dump(result, handle, indent=2)
            handle.write('\n')
        if not stable or before != after or after != reopened:
            raise RuntimeError('Stable native text fixture was rejected or changed')
        print(json.dumps({'native_read': 'pass', 'path_handle_mismatches': mismatches}))


if __name__ == '__main__':
    main()
