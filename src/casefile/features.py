"""Sequence features computed in code. Missing data is never turned into 'no signals'."""
from dataclasses import dataclass
from datetime import datetime

from .models import Contradiction, EvidenceRecord, EvidenceStatus

REQUIRED = ("device_history", "transactions")
TEST_CHARGE_MAX = 2.0


class IncompleteEvidence(Exception):
    """A required source is not `ok`, so features cannot be computed."""


@dataclass(frozen=True)
class Features:
    new_device_foreign: bool
    mfa_reset_after_new_device: bool
    test_charge_count: int
    new_beneficiary: bool
    largest_transfer: float
    payroll_seen: bool
    shared_device_accounts: int = 0          # from the device_sharing source when policy p2 requires it


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _ok(evidence, source):
    return [r for r in evidence if r.source == source and r.status == EvidenceStatus.OK]


def _transactions(evidence) -> list[dict]:
    return [t for r in _ok(evidence, "transactions") for t in r.data.get("transactions", [])]


def compute_sequence_features(evidence) -> Features:
    for src in REQUIRED:
        if not _ok(evidence, src):
            statuses = sorted({r.status.value for r in evidence if r.source == src}) or ["missing"]
            raise IncompleteEvidence(f"{src} status={'/'.join(statuses)}")
    devices, resets, home = [], [], None
    for r in _ok(evidence, "device_history"):
        home = home or r.data.get("home_country")
        devices += r.data.get("devices", [])
        resets += r.data.get("mfa_resets", [])
    foreign = [d for d in devices if not d.get("known") and d.get("country") != home]
    first_foreign = min((_ts(d["first_seen"]) for d in foreign), default=None)
    tx = _transactions(evidence)
    return Features(
        new_device_foreign=bool(foreign),
        mfa_reset_after_new_device=bool(first_foreign and any(_ts(x) >= first_foreign for x in resets)),
        test_charge_count=sum(1 for t in tx if t["kind"] == "charge" and t["amount"] <= TEST_CHARGE_MAX),
        new_beneficiary=any(t.get("beneficiary_new") for t in tx),
        largest_transfer=max((t["amount"] for t in tx if t["kind"] == "transfer"), default=0.0),
        payroll_seen=any(t["kind"] == "payroll" for t in tx),
        shared_device_accounts=max((r.data.get("shared_accounts", 0) for r in _ok(evidence, "device_sharing")), default=0),
    )


def recompute(metric: str, evidence) -> float:
    tx = _transactions(evidence)
    if metric == "largest_transfer":
        return max((t["amount"] for t in tx if t["kind"] == "transfer"), default=0.0)
    if metric == "test_charge_count":
        return float(sum(1 for t in tx if t["kind"] == "charge" and t["amount"] <= TEST_CHARGE_MAX))
    if metric == "transaction_count":
        return float(len(tx))
    raise ValueError(f"unknown metric {metric}")


def detect_contradictions(evidence) -> list[Contradiction]:
    """Same device reported with different first_seen in different records."""
    seen: dict[str, dict[str, str]] = {}
    for r in evidence:
        if r.source != "device_history" or r.status == EvidenceStatus.ERROR:
            continue
        for d in r.data.get("devices", []):
            seen.setdefault(d["id"], {})[r.id] = d["first_seen"]
    return [
        Contradiction(id=f"x_{dev}", evidence_ids=sorted(by_rec))
        for dev, by_rec in sorted(seen.items())
        if len(set(by_rec.values())) > 1
    ]
