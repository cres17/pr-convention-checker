"""Holdout command execution; errors are handled by the common CLI boundary."""
import json
from pathlib import Path
import sys

from drift_gate.adapters.cli.output import write_stdout as _write_stdout


def run(args):
    from drift_gate.adapters import holdout as h

    def load(path):
        return json.loads(Path(path).read_text(encoding='utf-8'))

    def lines(path):
        return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]

    pins = {'run': ('frozen_sha256',), 'packet': ('frozen_sha256',), 'adjudicate': ('packet_sha256',),
            'score': ('results_sha256', 'labels_sha256')}
    missing = [name for name in pins.get(args.operation, ()) if not getattr(args, name)]
    if missing:
        raise h.HoldoutError('holdout ' + args.operation + ' requires --' + ', --'.join(n.replace('_', '-') for n in missing)
                             + ': later steps admit earlier artifacts only through their pinned SHA-256')
    if args.operation == 'split':
        held, development = h.split(load(args.input), seed=args.seed, holdout_fraction=args.holdout_fraction,
                                    regression_families=tuple(args.regression_families))
        digest = h.write_once(args.out, held)
        extra = {'development_sha256': h.write_once(args.out_development, development)} if args.out_development else {}
        data = {'holdout_sha256': digest, 'holdout_cases': len(held['cases']),
                'development_cases': len(development['cases']), **extra}
    elif args.operation == 'freeze':
        digest = h.write_once(args.out, h.freeze(load(args.input), protocol=args.protocol))
        data = {'frozen_sha256': digest, 'pin_this_value_before_running': True}
    elif args.operation == 'run':
        frozen, digest = h.read_pinned(args.frozen, args.frozen_sha256, h.FROZEN)
        data = {'results_sha256': h.write_once(args.out, h.run_frozen(frozen, digest))}
    elif args.operation == 'packet':
        frozen, _ = h.read_pinned(args.frozen, args.frozen_sha256, h.FROZEN)
        from drift_gate.adapters.holdout_instructions import REVIEW_INSTRUCTIONS
        data = {'packet_sha256': h.write_once(args.out, h.review_packet(frozen, instructions=REVIEW_INSTRUCTIONS))}
    elif args.operation == 'adjudicate':
        packet, _ = h.read_pinned(args.packet, args.packet_sha256, h.PACKET)
        reviews = [row for path in args.reviews for row in lines(path)]
        resolutions = lines(args.resolutions) if args.resolutions else []
        labels = h.adjudicate(packet, reviews, resolutions)
        data = {'labels_sha256': h.write_once(args.out, labels), 'unresolved': len(labels['unresolved']),
                'agreement': labels['agreement']}
    else:
        results, _ = h.read_pinned(args.results, args.results_sha256, h.RESULTS)
        labels, labels_digest = h.read_pinned(args.labels, args.labels_sha256, h.LABELS)
        report = {**h.score_all(results, labels), 'labels_sha256': labels_digest,
                  'labels_pinned_by_caller': args.labels_sha256 is not None}
        data = {'metrics_sha256': h.write_once(args.out, report)}
    _write_stdout(json.dumps(data, ensure_ascii=False, indent=2))
    sys.exit(0)


