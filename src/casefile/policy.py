"""Versioned completion policy. No agent can edit it."""
from dataclasses import dataclass

from .features import Features
from .models import Outcome


@dataclass(frozen=True)
class Policy:
    version: str = "p1"
    transfer_threshold: float = 1000.0
    required_sources: tuple[str, ...] = ("device_history", "transactions")
    share_threshold: int | None = None     # p2: this many accounts on one device + a new beneficiary also escalates

    def decide(self, f: Features) -> Outcome:
        risky = (f.new_device_foreign and f.mfa_reset_after_new_device
                 and f.new_beneficiary and f.largest_transfer >= self.transfer_threshold)
        ring = (self.share_threshold is not None and f.shared_device_accounts >= self.share_threshold and f.new_beneficiary)
        return Outcome.ESCALATED if (risky or ring) else Outcome.CLOSED_BENIGN


P2 = Policy(version="p2", required_sources=("device_history", "transactions", "device_sharing"), share_threshold=3)
