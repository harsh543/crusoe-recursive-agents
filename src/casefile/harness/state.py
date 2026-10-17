"""Typed case state. Every field carries a data class; models only ever see INTERNAL fields."""
from datetime import datetime
from enum import StrEnum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class DataClass(StrEnum):
    PII = "pii"
    PAYMENT = "payment"
    INTERNAL = "internal"


FIELD_CLASSES = {"email": DataClass.PII, "card_number": DataClass.PAYMENT, "account_id": DataClass.INTERNAL,
                 "tenant_id": DataClass.INTERNAL, "alert_id": DataClass.INTERNAL, "alert_type": DataClass.INTERNAL,
                 "policy_version": DataClass.INTERNAL, "window_start": DataClass.INTERNAL, "window_end": DataClass.INTERNAL}


class Alert(BaseModel):
    model_config = ConfigDict(frozen=True)
    alert_id: str
    alert_type: str
    tenant_id: str
    policy_version: str
    email: Optional[str] = None
    account_id: Optional[str] = None
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None


class CaseState(BaseModel):
    case_id: str
    alert: Alert
    completed: list[str] = []
    status: Literal["running", "interrupted", "rejected", "done"] = "running"
    outcome: Optional[str] = None
    receipt_id: Optional[str] = None
    interrupt_reason: Optional[str] = None
    reject_reason: Optional[str] = None
    account_id: Optional[str] = None
    provenance: dict = {}                      # where each value came from ("provided" / "resolved:resolve_account")
    review_task_id: Optional[str] = None
    field_classes: dict[str, DataClass] = FIELD_CLASSES

    def model_view(self) -> dict:
        """The only slice of the case a model prompt may be built from (INTERNAL data class)."""
        a = self.alert
        raw = {"alert_id": a.alert_id, "alert_type": a.alert_type, "tenant_id": a.tenant_id, "policy_version": a.policy_version,
               "account_id": self.account_id, "window_start": a.window_start and a.window_start.isoformat(),
               "window_end": a.window_end and a.window_end.isoformat()}
        return {k: v for k, v in raw.items() if self.field_classes.get(k) == DataClass.INTERNAL}
