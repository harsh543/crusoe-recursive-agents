"""Shared fixtures: synthetic A-104 (account takeover) and A-105 (benign lookalike) evidence."""
from datetime import datetime, timezone

import pytest

from casefile.contract import build_contract
from casefile.models import Claim, NumericClaim, Outcome, Recommendation
from casefile.models import EvidenceRecord
from casefile.policy import Policy

UTC = timezone.utc
W0 = datetime(2026, 9, 1, tzinfo=UTC)
W1 = datetime(2026, 10, 1, tzinfo=UTC)


def ev(id, source, *, status="ok", account="acct_104", tenant="t1", start=W0, end=W1, data=None):
    return EvidenceRecord(
        id=id, source=source, account_id=account, tenant_id=tenant, status=status,
        covers_from=start, covers_to=end, retrieved_at=W1, data=data or {},
    )


def a104_device(**kw):
    return ev("ev_dev", "device_history", data={
        "home_country": "US",
        "devices": [
            {"id": "d1", "country": "US", "first_seen": "2026-03-01T00:00:00Z", "known": True},
            {"id": "d2", "country": "RO", "first_seen": "2026-09-20T10:00:00Z", "known": False},
        ],
        "mfa_resets": ["2026-09-20T10:05:00Z"],
    }, **kw)


def a104_tx(**kw):
    return ev("ev_tx", "transactions", data={"transactions": [
        {"id": "t1", "kind": "charge", "amount": 1.0, "ts": "2026-09-20T10:10:00Z"},
        {"id": "t2", "kind": "charge", "amount": 2.0, "ts": "2026-09-20T10:11:00Z"},
        {"id": "t3", "kind": "charge", "amount": 1.0, "ts": "2026-09-20T10:12:00Z"},
        {"id": "t4", "kind": "transfer", "amount": 4800.0, "beneficiary": "Velo Holdings",
         "beneficiary_new": True, "ts": "2026-09-20T10:30:00Z"},
    ]}, **kw)


def a105_device(**kw):
    return ev("ev_dev", "device_history", account="acct_105", data={
        "home_country": "US",
        "devices": [
            {"id": "d1", "country": "US", "first_seen": "2026-01-01T00:00:00Z", "known": True},
            {"id": "d2", "country": "US", "first_seen": "2026-09-15T09:00:00Z", "known": False},
        ],
        "mfa_resets": [],
    }, **kw)


def a105_tx(**kw):
    return ev("ev_tx", "transactions", account="acct_105", data={"transactions": [
        {"id": "t1", "kind": "payroll", "amount": 3200.0, "ts": "2026-09-14T08:00:00Z"},
        {"id": "t2", "kind": "transfer", "amount": 1500.0, "beneficiary": "New Landlord LLC",
         "beneficiary_new": True, "ts": "2026-09-16T12:00:00Z"},
    ]}, **kw)


@pytest.fixture
def policy():
    return Policy()


@pytest.fixture
def contract(policy):
    return build_contract(
        case_id="A-104", account_id="acct_104", tenant_id="t1",
        window_start=W0, window_end=W1,
        planner_checks=["window_covered", "contradictions_addressed"], policy=policy,
    )


@pytest.fixture
def good_claims():
    return [
        Claim(id="c1", text="New device in RO after months on a US device", evidence_ids=["ev_dev"]),
        Claim(id="c2", text="Largest transfer was 4,800", evidence_ids=["ev_tx"],
              numeric=NumericClaim(metric="largest_transfer", value=4800.0)),
    ]


@pytest.fixture
def good(contract, policy, good_claims):
    """Keyword arguments for a verify() call that should pass pre_commit on A-104."""
    return dict(
        contract=contract, policy=policy,
        evidence=[a104_device(), a104_tx()],
        recommendation=Recommendation(outcome=Outcome.ESCALATED, claims=good_claims),
        contradictions=[], receipt=None, phase="pre_commit",
    )
