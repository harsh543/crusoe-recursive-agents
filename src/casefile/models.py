"""Typed records shared by every module. Frozen so evidence and contracts cannot be edited in place."""
from datetime import datetime
from enum import StrEnum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class Outcome(StrEnum):
    COLLECTION_FAILED = "collection_failed"
    CLOSED_BENIGN = "closed_benign"
    ESCALATED = "escalated"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


CLOSURE_OUTCOMES = frozenset({Outcome.CLOSED_BENIGN, Outcome.ESCALATED})


class EvidenceStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    EMPTY = "empty"
    PARTIAL = "partial"
    STALE = "stale"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class EvidenceRecord(_Frozen):
    id: str
    source: str
    account_id: str
    tenant_id: str
    status: EvidenceStatus
    covers_from: datetime
    covers_to: datetime
    retrieved_at: datetime
    data: dict = {}
    error: Optional[str] = None


class NumericClaim(_Frozen):
    metric: Literal["largest_transfer", "test_charge_count", "transaction_count"]
    value: float


class Claim(_Frozen):
    id: str
    text: str
    evidence_ids: list[str]
    numeric: Optional[NumericClaim] = None


class Recommendation(_Frozen):
    outcome: Outcome
    claims: list[Claim]


class Contradiction(_Frozen):
    id: str
    evidence_ids: list[str]
    resolution: Optional[Literal["resolved", "escalated"]] = None


class Case(_Frozen):
    id: str
    email: str
    account_id: str
    tenant_id: str
    window_start: datetime
    window_end: datetime
    raw: dict
