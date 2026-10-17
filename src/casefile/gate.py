"""The only writer. Allowlisted action, idempotent, refuses unverified closure."""
from pydantic import BaseModel, ConfigDict

from .models import CLOSURE_OUTCOMES, Outcome


class GateRefused(Exception):
    pass


class WriteInterrupted(Exception):
    pass


class Receipt(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    case_id: str
    outcome: Outcome
    idempotency_key: str
    written: bool


class Gate:
    def __init__(self, fail_next_write: bool = False):
        self.fail_next_write = fail_next_write
        self.writes: list[Receipt] = []
        self._by_key: dict[str, Receipt] = {}

    def commit_disposition(self, *, verification, case_id, outcome, contract_version,
                           idempotency_key) -> Receipt:
        try:
            outcome = Outcome(outcome)
        except ValueError:
            raise GateRefused(f"action {outcome!r} is not an allowlisted disposition") from None
        if outcome in CLOSURE_OUTCOMES and not verification.passed:
            reasons = "; ".join(f"{f.check}: {f.reason}" for f in verification.failures)
            raise GateRefused(f"cannot close case {case_id} as {outcome.value}: {reasons}")
        if idempotency_key in self._by_key:
            return self._by_key[idempotency_key]
        if self.fail_next_write:
            self.fail_next_write = False
            raise WriteInterrupted("final write interrupted before it was recorded")
        receipt = Receipt(id=f"rcpt_{len(self.writes) + 1}", case_id=case_id, outcome=outcome,
                          idempotency_key=idempotency_key, written=True)
        self.writes.append(receipt)
        self._by_key[idempotency_key] = receipt
        return receipt
