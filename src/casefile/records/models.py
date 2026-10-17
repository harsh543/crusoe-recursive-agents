"""Typed records for claim verification. Frozen; documents carry provenance and an integrity hash."""
import hashlib
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Verdict(StrEnum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    COLLECTION_FAILED = "collection_failed"
    OUT_OF_SCOPE = "out_of_scope"


CLOSURE_VERDICTS = frozenset({Verdict.SUPPORTED, Verdict.CONTRADICTED})


class ClaimType(StrEnum):
    DATE_GAP = "date_gap"
    AMOUNT = "amount"
    COMPETITION_STATUS = "competition_status"
    FLOW_THROUGH = "flow_through"
    RULE_TEXT = "rule_text"
    RELATIONSHIP = "relationship"
    POLICY_INTERNAL = "policy_internal"
    LEGAL_CONCLUSION = "legal_conclusion"
    OTHER = "other"


OUT_OF_SCOPE_TYPES = frozenset({ClaimType.LEGAL_CONCLUSION})


class DocType(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    TRANSCRIPT = "transcript"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Document(_Frozen):
    id: str
    url: str
    doc_type: DocType
    title: str
    publisher: str
    retrieved_at: datetime
    sha256: str
    text: str

    @model_validator(mode="after")
    def _integrity(self):
        if hashlib.sha256(self.text.encode()).hexdigest() != self.sha256:
            raise ValueError(f"document {self.id}: sha256 does not match text")
        return self


class Finding(_Frozen):
    model_config = ConfigDict(frozen=True, coerce_numbers_to_str=True)     # models often emit 143000000 instead of "143000000"
    field: str
    value: str
    quote: str
    doc_id: str


class RecordClaim(_Frozen):
    id: str
    text: str
    attributed_to: str = Field(min_length=1)       # every claim is someone's assertion, never ours
    claim_type: ClaimType
    subject_private_individual: bool = False
    params: dict = {}


class ClaimResult(_Frozen):
    claim_id: str
    verdict: Verdict
    findings: list[Finding] = []
    explanation: str = ""
    conflicts: list[str] = []
