"""Validated proof projections alongside the unchanged legacy policy result."""
from dataclasses import dataclass
import json

from drift_gate.core.contracts.planner import Truth
from drift_gate.core.evaluation.contract_proof import ContractProof
from drift_gate.core.evaluation.result_guard import ResultValidationError


def _state(truth, complete, *, not_applicable=False):
    if not_applicable:
        return {'decision': 'not-applicable', 'verification': 'not-applicable'}
    return {'decision': {Truth.TRUE:'satisfied', Truth.FALSE:'violated', Truth.UNKNOWN:'undetermined'}[truth],
            'verification': 'unverified' if truth == Truth.UNKNOWN else 'verified' if complete else 'partial'}


def project_contract_proof(proof):
    """No pass/warn/fail inference. Authority and enforcement are separate stages."""
    if not isinstance(proof, ContractProof):
        raise ResultValidationError('projection requires a validated contract proof')
    proof.validate()
    nodes = {node.id: node for node in proof.proof.nodes}
    request = proof.evaluation.plan.request
    inactive = (proof.root.truth == Truth.TRUE and proof.root.coverage.complete and
                all(row.obligation.assessment.applicability == Truth.FALSE for row in proof.evaluation.outcomes))
    return {'schema':'contract-legacy-projection-v1', 'context_ref':proof.context.ref,
            'rule_id':request.rule_id, 'group_id':request.group_id, 'relation_id':request.relation_id,
            **_state(proof.root.truth, proof.root.coverage.complete, not_applicable=inactive),
            'truth':proof.root.truth.value, 'decision_proven':proof.root.decision_proven,
            'proof_ref':proof.root.proof_ref, 'complete_within_selection':proof.root.coverage.complete,
            'source_paths':list(request.source_paths),
            'closed_domains':list(proof.root.coverage.closed_domains),
            'open_domains':list(proof.root.coverage.open_domains),
            'requested_families':[family.value for family in proof.evaluation.plan.discovery.requested_families],
            'obligations':[{'id':row.obligation.id,
                **_state(nodes[row.obligation.id].truth, nodes[row.obligation.id].coverage.complete,
                         not_applicable=row.obligation.assessment.applicability == Truth.FALSE)}
                for row in proof.evaluation.outcomes],
            'gate_action_applied':False, 'service_scope_certified':False,
            'assurance':'logical-consistency-relative-to-admitted-premises'}


@dataclass(frozen=True)
class ContractDiagnostics:
    proofs: tuple[ContractProof, ...]
    records_seen: int
    retention_limit: int

    def __post_init__(self):
        if (not isinstance(self.proofs, (tuple,list)) or any(not isinstance(row,ContractProof) for row in self.proofs) or
            type(self.records_seen) is not int or type(self.retention_limit) is not int or
            self.records_seen < len(self.proofs) or self.retention_limit < len(self.proofs) or self.retention_limit < 0):
            raise ResultValidationError('invalid diagnostic retention metadata')
        refs = [row.evaluation.plan.request.ref for row in self.proofs]
        if len(refs) != len(set(refs)):
            raise ResultValidationError('duplicate diagnostic request')
        object.__setattr__(self,'proofs',tuple(sorted(self.proofs,key=lambda row:row.evaluation.plan.request.ref)))

    def to_dict(self, *, compact=False):
        entries = []
        for proof in self.proofs:
            projection = project_contract_proof(proof)
            entry = {'projection':projection}
            if not compact:
                entry['proof_result'] = json.loads(json.dumps(proof.to_dict(), ensure_ascii=True, allow_nan=False))
            entries.append(entry)
        return {'schema':'contract-diagnostics-v1','role':'legacy-selector-shadow',
                'status':'retained-shadow-records' if self.proofs else 'no-shadow-records',
                'complete_policy_coverage':False,'gate_action_applied':False,
                'records_seen':self.records_seen,'retained_count':len(self.proofs),
                'retention_limit':self.retention_limit,'omitted_record_count':self.records_seen-len(self.proofs),
                'trace_truncated':self.records_seen > len(self.proofs),
                'full_proofs_omitted':compact,'entries':entries}


def project_legacy_result(result):
    payload = result._legacy_dict()
    if result.contract_diagnostics is not None:
        if not isinstance(result.contract_diagnostics,ContractDiagnostics):
            raise ResultValidationError('invalid contract diagnostic result')
        payload['contract_diagnostics'] = result.contract_diagnostics.to_dict()
    return payload


def diagnostic_lines(result):
    """Shared display values; HTML/Markdown escape according to their formats."""
    if result.contract_diagnostics is None:
        return ()
    if not isinstance(result.contract_diagnostics,ContractDiagnostics):
        raise ResultValidationError('invalid contract diagnostic result')
    data = result.contract_diagnostics.to_dict(compact=True)
    lines = ['Contract proof diagnostics (shadow): legacy policy gate is unchanged.',
             f"Retained {data['retained_count']}/{data['records_seen']} records; complete policy coverage: false."]
    for entry in data['entries']:
        row = entry['projection']
        lines.append(f"{row['group_id']}: {row['truth']} / {row['decision']} / {row['verification']}; "
                     f"decision proven: {str(row['decision_proven']).lower()}; "
                     f"scope complete: {str(row['complete_within_selection']).lower()}")
    return tuple(lines)
