"""Run a pinned trusted engine beside the candidate engine (design W09).

The trusted engine is materialized from an immutable commit whose manifest is
pinned by SHA-256, executed in a separate ``python -I`` interpreter without
credential variables, and evaluates the candidate head with a separately pinned
policy. The candidate engine runs in this process as a shadow. Only the trusted
verdict is a merge basis. The child shares this machine's filesystem and
network; this is an execution boundary for code identity, not a sandbox.
"""
from hashlib import sha256

from drift_gate.adapters import engine_artifact as engines
from drift_gate.core.trust.validation import EngineRun, decide


def _changed_paths(snapshot):
    files = snapshot.materialize()['changed_files']
    return sorted({path for file in files for path in (file.path, file.previous_path) if path})


def _check_args(*, base, head, policy, trusted_policy_ref, trusted_policy_sha256, comparison_mode):
    return ['check', '--base', base, '--head', head, '--policy', policy, '--trusted-policy-ref', trusted_policy_ref,
            '--trusted-policy-sha256', trusted_policy_sha256, '--comparison-mode', comparison_mode, '--json']


def trusted_check(*, root, base, head, policy, trusted_policy_ref, trusted_policy_sha256, manifest,
                  comparison_mode='commit', execution=None):
    import json
    from drift_gate.adapters.git.immutable import collect_git_snapshot
    from drift_gate.adapters.inspection import inspect_snapshot
    envelope = engines.run_pinned(root, manifest, 'check', _check_args(
        base=base, head=head, policy=policy, trusted_policy_ref=trusted_policy_ref,
        trusted_policy_sha256=trusted_policy_sha256, comparison_mode=comparison_mode), cwd=root)
    attestation = envelope['attestation']
    # Both the engine code and every loaded grammar must match their pins; an unpinned or
    # mismatched parser leaves the trusted verdict without a merge basis (review).
    attested = (attestation['loaded_code_matches_manifest'] and attestation['parsers']['basis'] != 'unavailable'
                and bool(attestation['parsers'].get('matched')))
    trusted_result, trusted_error = None, ''
    try:
        trusted_report = json.loads(envelope['stdout'])
        if envelope['exit_code'] in (0, 1) and trusted_report.get('result') in {'pass', 'warn', 'fail'}:
            trusted_result = trusted_report['result']
        else:
            trusted_error = (trusted_report.get('error') or {}).get('message') or f"exit {envelope['exit_code']}"
    except ValueError:
        trusted_report, trusted_error = None, f"no JSON result (exit {envelope['exit_code']})"
    snapshot = collect_git_snapshot(root=root, base=base, head=head, trusted_policy_ref=trusted_policy_ref,
                                    trusted_policy_sha256=trusted_policy_sha256, policy_path=policy,
                                    comparison_mode=comparison_mode)
    candidate_error, candidate_result = '', None
    try:
        candidate = inspect_snapshot(snapshot, execution=execution)
        candidate_result = candidate.result
    except Exception as exc:  # the shadow must not mask the trusted verdict
        candidate_error = type(exc).__name__
    changed = _changed_paths(snapshot)
    trusted_run = EngineRun('trusted', trusted_result, manifest['commit'], bool(attested), trusted_error)
    candidate_run = EngineRun('candidate', candidate_result, 'current-process', False, candidate_error)
    decision = decide(trusted_run, candidate_run, changed)
    return {'schema': 'trusted-validation-v1', 'subject': snapshot.git_evidence.subject.to_dict(),
            'trusted': {'engine_commit': manifest['commit'], 'manifest_sha256': sha256(engines.manifest_bytes(manifest)).hexdigest(),
                        'gate_result': trusted_result, 'error': trusted_error, 'attestation': attestation,
                        'input_sha256': ((trusted_report or {}).get('execution', {}).get('input_capture') or {})
                                         .get('input_sha256')},
            'candidate': {'engine': 'current-process', 'gate_result': candidate_result, 'error': candidate_error,
                          'role': 'shadow-not-merge-basis',
                          'input_sha256': snapshot.manifest.input_sha256},
            'decision': decision.to_dict(),
            'boundary': 'separate-interpreter-no-credentials; shares host filesystem and network'}


def certified_replay(bundle_path, *, root, manifest, expected_receipt_sha256=None):
    """Replay a stored bundle with the engine that produced it, not the current engine."""
    from drift_gate.adapters.evidence_bundle import load_bundle
    from drift_gate.adapters.bundle_codec import semantic_result
    bundle = load_bundle(bundle_path, expected_receipt_sha256=expected_receipt_sha256)
    producer = bundle.receipt['producer']
    if producer['source_sha256'] != manifest['producer_source_sha256']:
        return {'schema': 'certified-replay-v1', 'certified': False,
                'reason': 'bundle-producer-differs-from-pinned-engine',
                'receipt_producer_source_sha256': producer['source_sha256'],
                'manifest_producer_source_sha256': manifest['producer_source_sha256']}
    import json
    envelope = engines.run_pinned(root, manifest, 'replay', {'path': str(bundle.path),
                                                            'receipt': sha256(bundle.receipt_bytes).hexdigest()},
                                  cwd=str(bundle.path))
    attestation = envelope['attestation']
    try:
        replayed = json.loads(envelope['stdout'])
    except ValueError:
        replayed = None
    matches = replayed is not None and semantic_result(replayed) == semantic_result(bundle.recorded_result)
    loaded_parsers = attestation['parsers']['libraries']
    parsers_ok = attestation['parsers']['matched'] or not loaded_parsers
    certified = bool(matches and attestation['loaded_code_matches_manifest'] and parsers_ok)
    return {'schema': 'certified-replay-v1', 'certified': certified,
            'reason': 'pinned-engine-reproduced-recorded-result' if certified else
                      'recorded-result-differs' if not matches else 'engine-or-parser-attestation-failed',
            'receipt_sha256': sha256(bundle.receipt_bytes).hexdigest(), 'engine_commit': manifest['commit'],
            'recorded_result_matches_pinned_engine': matches, 'attestation': attestation,
            'parsers_loaded': len(loaded_parsers), 'interpreter_attested': False,
            'gate_result': replayed.get('result') if replayed else None}
