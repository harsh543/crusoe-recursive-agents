"""Seeded synthetic cases (A-104 takeover, A-105 benign lookalike) x injected faults, plus oracle labels."""
import json
import random
from datetime import datetime, timedelta, timezone

from ..models import Case
from ..oracle import LABELS
from ..tools import FaultPlan

UTC = timezone.utc
W0, W1 = datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)
SCENARIOS = {"A-104": "escalated", "A-105": "closed_benign"}
FAULTS = ["none", "wrong_identifier", "device_error_once", "device_empty", "device_stale"]
RECOVERABLE = {"none", "wrong_identifier", "device_error_once"}
SPLITS = {"dev": [0], "heldout": [1]}


def make_faults(name: str) -> FaultPlan:
    return {
        "none": FaultPlan(),
        "wrong_identifier": FaultPlan(wrong_identifier=True),
        "device_error_once": FaultPlan(device_history="error", times=1),
        "device_empty": FaultPlan(device_history="empty"),
        "device_stale": FaultPlan(device_history="stale"),
    }[name]


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_case(scenario: str, seed: int) -> Case:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; expected one of {sorted(SCENARIOS)}")
    rng = random.Random(f"{scenario}-{seed}")
    acct = f"acct_{scenario[-3:]}{seed}"
    base = W0 + timedelta(days=rng.randint(12, 24), hours=rng.randint(1, 20))
    if scenario == "A-104":
        country = rng.choice(["RO", "NG", "VN", "BR"])
        devices = [{"id": "d1", "country": "US", "first_seen": "2026-03-01T00:00:00Z", "known": True},
                   {"id": "d2", "country": country, "first_seen": _iso(base), "known": False}]
        resets = [_iso(base + timedelta(minutes=5))]
        tx = [{"id": f"t{i}", "kind": "charge", "amount": a, "ts": _iso(base + timedelta(minutes=9 + i))}
              for i, a in enumerate([1.0, 2.0, 1.0], 1)]
        tx.append({"id": "t4", "kind": "transfer", "amount": float(rng.randint(3500, 6000)),
                   "beneficiary": "Velo Holdings", "beneficiary_new": True, "ts": _iso(base + timedelta(minutes=30))})
    else:
        devices = [{"id": "d1", "country": "US", "first_seen": "2026-01-01T00:00:00Z", "known": True},
                   {"id": "d2", "country": "US", "first_seen": _iso(base), "known": False}]
        resets = []
        tx = [{"id": "t1", "kind": "payroll", "amount": float(rng.randint(2800, 4200)), "ts": _iso(base + timedelta(days=1))},
              {"id": "t2", "kind": "transfer", "amount": float(rng.randint(1100, 2200)),
               "beneficiary": "New Landlord LLC", "beneficiary_new": True, "ts": _iso(base + timedelta(days=2))}]
    return Case(id=f"{scenario}-s{seed}", email=f"customer{scenario[-3:]}s{seed}@example.test", account_id=acct,
                tenant_id="t1", window_start=W0, window_end=W1,
                raw={"device_history": {"home_country": "US", "devices": devices, "mfa_resets": resets},
                     "transactions": {"transactions": tx}})


def split_cases(split: str):
    """[(case, fault_name)] for a split."""
    return [(build_case(sc, seed), f) for seed in SPLITS[split] for sc in SCENARIOS for f in FAULTS]


def expected_for(case: Case, fault: str) -> str:
    scenario = case.id.split("-s")[0]
    return SCENARIOS[scenario] if fault in RECOVERABLE else "insufficient_evidence"


def write_labels(path=LABELS) -> dict:
    labels = {f"{c.id}:{f}": expected_for(c, f) for s in SPLITS for c, f in split_cases(s)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(labels, indent=1))
    return labels
