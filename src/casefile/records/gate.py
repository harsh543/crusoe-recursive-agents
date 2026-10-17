"""Writes claim verdicts. Same rules as the transaction Gate: allowlist, idempotency, no unverified closure."""
from pydantic import BaseModel, ConfigDict

from ..gate import GateRefused, WriteInterrupted
from .models import CLOSURE_VERDICTS, Verdict


class RecordsReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    claim_id: str
    verdict: Verdict
    idempotency_key: str
    written: bool


class RecordsGate:
    def __init__(self, fail_next_write: bool = False):
        self.fail_next_write = fail_next_write
        self.writes: list[RecordsReceipt] = []
        self._by_key: dict[str, RecordsReceipt] = {}

    def commit(self, *, verification, claim_id, verdict, idempotency_key) -> RecordsReceipt:
        try:
            verdict = Verdict(verdict)
        except ValueError:
            raise GateRefused(f"verdict {verdict!r} is not allowlisted") from None
        if verdict in CLOSURE_VERDICTS and not verification.passed:
            why = "; ".join(f"{f.check}: {f.reason}" for f in verification.failures)
            raise GateRefused(f"cannot record {verdict.value} for {claim_id}: {why}")
        if idempotency_key in self._by_key:
            return self._by_key[idempotency_key]
        if self.fail_next_write:
            self.fail_next_write = False
            raise WriteInterrupted("ledger write interrupted")
        r = RecordsReceipt(id=f"rr_{len(self.writes) + 1}", claim_id=claim_id, verdict=verdict,
                           idempotency_key=idempotency_key, written=True)
        self.writes.append(r)
        self._by_key[idempotency_key] = r
        return r
