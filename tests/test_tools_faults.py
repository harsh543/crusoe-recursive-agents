"""FR-18: typed tools and fault injection, including the production failure (email for account ID)."""
import pytest

from casefile.models import EvidenceStatus
from casefile.tools import FaultPlan, ToolBox
from tests.conftest import a104_device, a104_tx, W0, W1


@pytest.fixture
def case():
    from casefile.models import Case

    return Case(
        id="A-104", email="sam@example.test", account_id="acct_104", tenant_id="t1",
        window_start=W0, window_end=W1,
        raw={"device_history": a104_device().data, "transactions": a104_tx().data},
    )


def test_resolve_account_maps_email_to_account_id(case):
    assert ToolBox(case).resolve_account("sam@example.test") == "acct_104"


def test_device_history_with_email_returns_error_not_ok(case):
    rec = ToolBox(case).get_device_history("sam@example.test")
    assert rec.status == EvidenceStatus.ERROR
    assert "account_id" in (rec.error or "")


def test_device_history_with_account_id_is_ok_and_scoped(case):
    rec = ToolBox(case).get_device_history("acct_104")
    assert rec.status == EvidenceStatus.OK
    assert (rec.account_id, rec.tenant_id) == ("acct_104", "t1")
    assert rec.covers_from == W0 and rec.covers_to == W1


@pytest.mark.parametrize("fault,status", [
    ("error", EvidenceStatus.ERROR),
    ("empty", EvidenceStatus.EMPTY),
    ("stale", EvidenceStatus.STALE),
    ("partial", EvidenceStatus.PARTIAL),
])
def test_injected_device_faults_force_status(case, fault, status):
    rec = ToolBox(case, faults=FaultPlan(device_history=fault)).get_device_history("acct_104")
    assert rec.status == status


def test_faults_do_not_leak_into_other_sources(case):
    tb = ToolBox(case, faults=FaultPlan(device_history="error"))
    assert tb.get_transactions("acct_104").status == EvidenceStatus.OK


def test_tool_results_are_deterministic(case):
    tb = ToolBox(case)
    assert tb.get_transactions("acct_104") == tb.get_transactions("acct_104")
