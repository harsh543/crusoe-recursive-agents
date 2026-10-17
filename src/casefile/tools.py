"""Typed read tools with status envelopes and fault injection. Errors are values, never 'nothing found'."""
from dataclasses import dataclass
from typing import Optional

from .features import compute_sequence_features
from .models import Case, EvidenceRecord, EvidenceStatus

IDS = {"device_history": "ev_dev", "transactions": "ev_tx", "device_sharing": "ev_share"}


@dataclass
class FaultPlan:
    device_history: Optional[str] = None      # error | empty | stale | partial
    transactions: Optional[str] = None
    wrong_identifier: bool = False            # first device lookup receives the email, as in the production bug
    times: Optional[int] = None               # fault applies to the first N fetches of a source; None = always


class ToolBox:
    def __init__(self, case: Case, faults: FaultPlan | None = None, data_source=None, fraud_engine=None):
        self.case, self.faults = case, faults or FaultPlan()
        self.data_source = data_source                      # e.g. SupabaseCaseSource; None reads Case.raw (offline tests)
        self.fraud_engine = fraud_engine                    # FraudDataset for cross-account analytics (policy p2)
        self._wrong_id_used = False
        self._fetches: dict[str, int] = {}

    def resolve_account(self, email: str) -> str:
        if self.data_source is not None:
            return self.data_source.resolve_account(email, self.case.tenant_id)
        if email.strip().lower() != self.case.email.lower():
            raise LookupError("unknown email")
        return self.case.account_id

    def _record(self, source, status, data=None, error=None, partial=False) -> EvidenceRecord:
        c = self.case
        end = c.window_start + (c.window_end - c.window_start) / 2 if partial else c.window_end
        return EvidenceRecord(id=IDS[source], source=source, account_id=c.account_id, tenant_id=c.tenant_id,
                              status=status, covers_from=c.window_start,
                              covers_to=c.window_start if status == EvidenceStatus.ERROR else end,
                              retrieved_at=c.window_end, data=data or {}, error=error)

    def _fetch(self, source: str, account_id: str) -> EvidenceRecord:
        if source == "device_history" and self.faults.wrong_identifier and not self._wrong_id_used:
            self._wrong_id_used = True
            account_id = self.case.email
        if not account_id.startswith("acct_") or "@" in account_id:
            return self._record(source, EvidenceStatus.ERROR,
                                error=f"{source} expects account_id (acct_...), got {account_id!r}")
        if account_id != self.case.account_id:
            return self._record(source, EvidenceStatus.ERROR, error=f"unknown account_id {account_id}")
        n = self._fetches[source] = self._fetches.get(source, 0) + 1
        fault = getattr(self.faults, source, None)
        if self.faults.times is not None and n > self.faults.times:
            fault = None
        if source == "device_sharing":
            if self.fraud_engine is None:
                return self._record(source, EvidenceStatus.ERROR, error="device_sharing source unavailable")
            data = self.fraud_engine.inspect_device_sharing(account_id)
        else:
            data = self.data_source.load(source, account_id) if self.data_source is not None else self.case.raw[source]
        if fault == "error":
            return self._record(source, EvidenceStatus.ERROR, error="upstream timeout")
        if fault == "empty":
            return self._record(source, EvidenceStatus.EMPTY)
        if fault == "stale":
            return self._record(source, EvidenceStatus.STALE, data=data)
        if fault == "partial":
            return self._record(source, EvidenceStatus.PARTIAL, data=data, partial=True)
        return self._record(source, EvidenceStatus.OK, data=data)

    def get_device_history(self, account_id: str) -> EvidenceRecord:
        return self._fetch("device_history", account_id)

    def get_device_sharing(self, account_id: str) -> EvidenceRecord:
        return self._fetch("device_sharing", account_id)

    def get_transactions(self, account_id: str) -> EvidenceRecord:
        return self._fetch("transactions", account_id)

    def compute_sequence_features(self, evidence):
        return compute_sequence_features(evidence)
