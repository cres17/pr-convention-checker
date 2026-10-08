"""CI re-admission/replay of a receipt produced by the real immutable check."""
import argparse
import json
from pathlib import Path

from drift_gate.adapters.evidence_bundle import load_bundle
from drift_gate.adapters.execution import atomic_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    data = json.loads(Path(args.report).read_text(encoding='utf-8'))
    reference = data['execution']['evidence_bundle']
    bundle = load_bundle(reference['path'], expected_receipt_sha256=reference['receipt_sha256'])
    replay = bundle.replay()
    matches = replay.execution['bundle_replay']['recorded_result_matches_current']
    atomic_json(args.out, {'bundle': bundle.to_dict(), 'replay': replay.execution['bundle_replay'],
                         'result': replay.to_dict()})
    if not matches:
        raise SystemExit('Stored result differs from current-engine replay')


if __name__ == '__main__':
    main()
