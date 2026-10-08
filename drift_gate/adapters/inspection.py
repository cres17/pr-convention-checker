"""Shared inspection boundary; adapters still own Git/network/document reads."""
import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from drift_gate.adapters.ast.analyzer import enrich_semantic_signals
from drift_gate.adapters.ast.express_routes import attach_express_routes
from drift_gate.adapters.execution import digest, identity
from drift_gate.adapters.policy_loader import require_check_policy
from drift_gate.core.engine import run as evaluate
from drift_gate.core.policy.validator import validate
from drift_gate.core.models.evaluation_context import EvaluationContext
from drift_gate.adapters.snapshot import capture_inspection, InspectionSnapshot


def execution_metadata(execution, policy_path, source, policy, files, provenance, context):
    # Internal snapshots affect semantic decisions, but their contents must not
    # enter reports/history. Hashes bind the receipt to the actual inputs.
    inputs = [{**file.to_dict(), "before_sha256": digest(file.before_source) if file.before_source is not None else None,
               "after_sha256": digest(file.after_source) if file.after_source is not None else None,
               **({"document_json_sha256": digest(file.document_json)} if file.document_json is not None else {}),
               **({'route_facts_sha256': digest(json.dumps([file.before_routes, file.after_routes]))}
                  if file.before_routes is not None else {})} for file in files]
    from drift_gate.core.models.policy import policy_identity_dict
    policy_text = source if source is not None else json.dumps(policy_identity_dict(policy), sort_keys=True)
    metadata = {**execution, "status": "success", **provenance,
                "policy_sha256": digest(policy_text), "policy_digest_kind": "source" if source is not None else "policy-object",
                "warnings": policy.load_warnings,
                "evaluation_context": context.to_dict(),
                "input_digest_version": 3,
                "input_sha256": digest(json.dumps({'files': inputs, 'evaluation_context': context.to_dict()},
                                                  sort_keys=True, allow_nan=False))}
    if policy_path is not None:
        metadata["policy_path"] = str(Path(policy_path).resolve())
    if "untracked_skipped" in metadata:
        metadata["untracked_skipped_count"] = len(metadata["untracked_skipped"])
    return metadata


def inspect(*, changed_files, policy, drift_ignores=None, execution=None,
            policy_source=None, policy_path=None, provenance=None, context=None, contract_proofs=False):
    require_check_policy(policy)
    validate(policy).raise_if_errors()
    context = context if context is not None else EvaluationContext(datetime.now(timezone.utc).date())
    snapshot = capture_inspection(changed_files=changed_files, policy=policy,
        drift_ignores=drift_ignores, context=context, policy_source=policy_source,
        policy_path=policy_path, provenance=provenance, contract_proofs=contract_proofs)
    return inspect_snapshot(snapshot, execution=execution)


def inspect_snapshot(snapshot: InspectionSnapshot, *, execution=None):
    """Replay captured inputs with the current engine; no checkout/Git reads.

    Parser and engine artifacts are not pinned by this initial capture protocol.
    """
    if not isinstance(snapshot, InspectionSnapshot):
        raise ValueError('expected a sealed inspection snapshot')
    InspectionSnapshot(snapshot.manifest, snapshot.payload, snapshot.git_evidence)
    inputs = snapshot.materialize()
    policy, context = inputs['policy'], inputs['context']
    require_check_policy(policy)
    validate(policy).raise_if_errors()
    started = time.perf_counter()
    files = enrich_semantic_signals(attach_express_routes(inputs['changed_files']))
    result = evaluate(changed_files=files, policy=policy, drift_ignores=inputs['drift_ignores'], context=context,
                      contract_proofs=inputs['contract_proofs'])
    result.inspected_files = files
    result.input_snapshot = snapshot
    result.scan_metrics.runtime_seconds = time.perf_counter() - started
    result.execution = execution_metadata(execution or identity(), inputs['policy_path'], inputs['policy_source'],
                                          policy, files, inputs['provenance'], context)
    result.execution['input_capture'] = snapshot.to_dict()
    return result
