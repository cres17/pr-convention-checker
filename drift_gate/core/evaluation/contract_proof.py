"""Plan -> admitted propositions -> independently checked proof DAG.

Family checker outputs are explicit premises. This is a proof of combination
and coverage retention, not a proof of parser correctness or document origin.
"""
from dataclasses import asdict, dataclass
from hashlib import sha256
import json

from drift_gate.core.contracts.planner import PlanEvaluation, Truth
from drift_gate.core.evaluation.propositions import build_proof
from drift_gate.core.evaluation.result_guard import ResultValidationError, validate_proof_evaluation
from drift_gate.core.models.proof import (
    CoverageDomain, EvidenceClaim, NodeSpec, Operator, ProofContext, ProofEvaluation, Proposition,
)


@dataclass(frozen=True)
class ContractProof:
    evaluation: PlanEvaluation
    context: ProofContext
    proof: ProofEvaluation

    def validate(self):
        # Reconstruct the expected context from the plan, not from received IR flags.
        expected = contract_proof_context(self.evaluation)
        if self.context != expected:
            raise ResultValidationError('contract context omitted or substituted')
        validate_proof_evaluation(self.proof, expected)
        root = next(node for node in self.proof.nodes if node.id == self.proof.root_ref)
        if root.truth != self.evaluation.truth or root.coverage.complete != self.evaluation.complete_within_selection:
            raise ResultValidationError('proof contradicts plan truth or coverage')
        return self

    @property
    def root(self):
        return next(node for node in self.proof.nodes if node.id == self.proof.root_ref)

    def to_dict(self):
        self.validate()
        return {**self.evaluation.to_dict(), 'schema': 'contract-proof-result-v1',
                'proof_dag_attached': True, 'decision_proven': self.root.decision_proven,
                'proof_ref': self.root.proof_ref, 'scope_coverage': asdict(self.root.coverage),
                'admitted_context': asdict(self.context), 'proof': self.proof.to_dict()}


def contract_proof_context(evaluation):
    if not isinstance(evaluation, PlanEvaluation):
        raise ResultValidationError('expected a typed plan evaluation')
    plan = evaluation.plan
    if not plan.discovery.source_digest or not evaluation.document_digest:
        raise ResultValidationError('proof requires bound source and document observations')
    # This binds all supplied source/document observations and checker outcomes.
    # It does not authenticate them against a provider or filesystem manifest.
    payload = evaluation.to_dict()
    input_ref = sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True,
                                 separators=(',', ':')).encode()).hexdigest()
    domains, atoms, evidence, specs = [], [], [], []
    assumptions = ('admitted-analyzer-output', 'selected-profile-subsets', 'source-origin-unverified')

    def atom(ref, truth, domain_refs, profile=None, reasons=()):
        claim_refs = ()
        if truth != Truth.UNKNOWN:
            claim_refs = ('evidence:' + ref,)
            evidence.append(EvidenceClaim(claim_refs[0], ref, truth, tuple(domain_refs), profile))
        atoms.append(Proposition(ref, truth, tuple(domain_refs), claim_refs, profile, assumptions, tuple(reasons)))
        specs.append(NodeSpec(ref, Operator.ATOM, proposition_ref=ref))
        return ref

    discovery_refs, partition_refs = [], {}
    for domain in plan.discovery.domains:
        ref = 'discovery:' + domain.source_path + ':' + domain.family.value
        closed = domain.state.value == 'closed'
        reasons = tuple(reason.value for reason in domain.reasons)
        domains.append(CoverageDomain(ref, closed, reasons))
        partition_refs[(domain.source_path, domain.family)] = ref
        # No analyzer is installed for an unsupported profile; that is an open
        # premise, never a known proposition backed by a nonexistent profile.
        profile = domain.profile_ref if closed else None
        discovery_refs.append(atom(ref, Truth.TRUE if closed else Truth.UNKNOWN, (ref,), profile, reasons))
    obligation_refs = []
    for row in evaluation.outcomes:
        obligation = row.obligation; assessment = obligation.assessment; scope = assessment.scope
        profile = scope.profile_ref if scope.profile_ref in {ref.profile_ref for ref in plan.discovery.closed_domains} else None
        analysis_ref = 'applicability:' + obligation.id
        reasons = tuple(reason.value for reason in row.reason_codes)
        domains.append(CoverageDomain(analysis_ref, assessment.applicability != Truth.UNKNOWN,
                                      () if assessment.applicability != Truth.UNKNOWN else ('applicability_open',)))
        source_refs = tuple(partition_refs[(path, scope.family)] for path in scope.source_paths)
        app = atom(analysis_ref, assessment.applicability, (*source_refs, analysis_ref), profile, reasons)
        requirement_ref = 'requirement:' + obligation.id
        # N/A has no document duty. Its skipped R=U is retained as an atom with
        # no document domain; inactive discovery domains still remain at root.
        requirement_domains = ()
        if assessment.applicability != Truth.FALSE:
            domains.append(CoverageDomain(requirement_ref, row.requirement_complete,
                () if row.requirement_complete else ('document_requirement_open',)))
            requirement_domains = (requirement_ref,)
        req = atom(requirement_ref, row.requirement, requirement_domains, profile, reasons)
        specs.append(NodeSpec(obligation.id, Operator.CONDITIONAL, (app, req)))
        obligation_refs.append(obligation.id)
    root = 'plan:' + plan.request.ref
    specs.append(NodeSpec(root, Operator.ALL, tuple(sorted((*discovery_refs, *obligation_refs)))))
    profiles = tuple(sorted({atom.profile_ref for atom in atoms if atom.profile_ref is not None}))
    return ProofContext(plan.request.ref, input_ref, tuple(domains), tuple(atoms), tuple(evidence),
                        profiles, tuple(specs), root)


def prove_contract_evaluation(evaluation):
    context = contract_proof_context(evaluation)
    proof = build_proof(context, context.structure, context.root_ref)
    return ContractProof(evaluation, context, proof).validate()


def inspect_contract_proof(request, source_files, documents=(), *, session=None):
    from drift_gate.core.evaluation.obligations import inspect_contract_plan
    return prove_contract_evaluation(inspect_contract_plan(request, source_files, documents, session=session))
