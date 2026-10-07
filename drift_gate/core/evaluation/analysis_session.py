"""Bounded memoization owned by one evaluation, never shared across requests."""
from collections import OrderedDict
from hashlib import sha256

from drift_gate.core.evaluation.static_routers import UnsupportedContract


class AnalysisSession:
    def __init__(self, limit=128):
        self.limit = limit
        self._entries = OrderedDict()
        self._contract_plans = OrderedDict()
        self._contract_proofs = OrderedDict()
        self.contract_records_seen = 0

    @property
    def shadow_contract_plans(self):
        """Bounded diagnostic trace, not a certificate of all policy obligations."""
        return tuple(self._contract_plans.values())

    @property
    def shadow_contract_proofs(self):
        """Validated diagnostic proofs; not a complete policy or service ledger."""
        return tuple(self._contract_proofs.values())

    def record_contract_plan(self, evaluation):
        from drift_gate.core.contracts.planner import PlanEvaluation
        if not isinstance(evaluation, PlanEvaluation):
            raise ValueError('expected a typed contract plan evaluation')
        from drift_gate.core.evaluation.contract_proof import prove_contract_evaluation
        proof = prove_contract_evaluation(evaluation)
        self.contract_records_seen += 1
        if self.limit:
            self._contract_plans[evaluation.plan.request.ref] = evaluation
            self._contract_proofs[evaluation.plan.request.ref] = proof
            self._contract_proofs.move_to_end(evaluation.plan.request.ref)
            self._contract_plans.move_to_end(evaluation.plan.request.ref)
            if len(self._contract_plans) > self.limit:
                self._contract_plans.popitem(last=False)
                self._contract_proofs.popitem(last=False)

    def resolve(self, kind, text, compute):
        # Kind separates parser modes; exact content is bound by its digest.
        key = kind, sha256(text.encode('utf-8', errors='surrogatepass')).digest() if text is not None else None
        if key not in self._entries:
            try:
                entry = (True, compute())
            except UnsupportedContract as exc:
                entry = (False, str(exc))
            if self.limit:
                self._entries[key] = entry
                if len(self._entries) > self.limit:
                    self._entries.popitem(last=False)
        else:
            self._entries.move_to_end(key)
            entry = self._entries[key]
        valid, value = entry
        if not valid:
            raise UnsupportedContract(value)
        return value
