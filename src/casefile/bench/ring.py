"""Synthetic mule-ring scenarios for the N -> N+1 demo. MOCK DATA, fictional accounts.
A-106: the target account looks benign on its own (known home-country device, small transfer to a new payee) but its device
       fingerprint is shared by 3 other accounts paying the same payee -> expected escalated under policy p2.
A-107: hard negative; a family pair shares a device and pays different payees -> expected closed_benign."""
import random
from datetime import timedelta

from ..models import Case
from .cases import W0, W1, _iso
from ..fraud_engine import FraudDataset

EXPECTED = {"A-106": "escalated", "A-107": "closed_benign"}
SPLITS = {"dev": [0, 1], "val": [2, 3, 4]}


def build_ring_case(scenario: str, seed: int) -> tuple[Case, FraudDataset]:
    rng = random.Random(f"{scenario}-{seed}")
    acct = f"acct_{scenario[-3:]}{seed}"
    base = W0 + timedelta(days=rng.randint(12, 24), hours=rng.randint(1, 20))
    ring = scenario == "A-106"
    payee = "Velo Holdings" if ring else "New Landlord LLC"
    amount = float(rng.randint(400, 900))
    devices = [{"id": "d1", "country": "US", "first_seen": "2026-01-01T00:00:00Z", "known": True}]
    tx = [{"id": "t1", "kind": "payroll", "amount": float(rng.randint(2800, 4200)), "ts": _iso(base - timedelta(days=3))},
          {"id": "t2", "kind": "transfer", "amount": amount, "beneficiary": payee, "beneficiary_new": True,
           "ts": _iso(base + timedelta(minutes=12))}]
    events = [{"account_id": acct, "device_fp": f"fp_{scenario}_{seed}", "beneficiary": payee, "amount": amount, "ts": _iso(base)}]
    peers = 3 if ring else 1
    for i in range(peers):
        events.append({"account_id": f"acct_{scenario[-3:]}{seed}p{i}", "device_fp": f"fp_{scenario}_{seed}",
                       "beneficiary": payee if ring else f"Other Payee {i}", "amount": float(rng.randint(300, 900)),
                       "ts": _iso(base + timedelta(minutes=3 * (i + 1)))})
    for i in range(6):                                              # unrelated background accounts
        events.append({"account_id": f"acct_bg{seed}_{i}", "device_fp": f"fp_bg_{seed}_{i}", "beneficiary": None,
                       "amount": 25.0, "ts": _iso(base + timedelta(hours=i))})
    case = Case(id=f"{scenario}-s{seed}", email=f"customer{scenario[-3:]}s{seed}@example.test", account_id=acct, tenant_id="t1",
                window_start=W0, window_end=W1,
                raw={"device_history": {"home_country": "US", "devices": devices, "mfa_resets": []},
                     "transactions": {"transactions": tx}})
    return case, FraudDataset(events)


def ring_cases(split: str):
    return [build_ring_case(sc, seed) for seed in SPLITS[split] for sc in EXPECTED]
