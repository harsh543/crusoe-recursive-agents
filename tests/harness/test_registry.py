"""E3: one tool contract. Registry enforces per-role access at call time and normalizes every result to a receipt."""
import pytest

from casefile.bench.cases import build_case, make_faults
from casefile.cost import CostLedger
from casefile.harness.registry import PermissionDenied, ToolNotFound, build_registry
from casefile.orchestrator import run_casefile
from casefile.policy import Policy
from casefile.tools import ToolBox
from casefile.trace import Trace
from tests.fakes import FakeLLM

CASE = build_case("A-104", 0)


def reg(fault="none"):
    return build_registry(ToolBox(CASE, make_faults(fault)), Policy())


def test_every_tool_declares_owner_version_and_access_class():
    for spec in reg().specs():
        assert spec.owner and spec.version and spec.access in ("read", "write")
    assert {s.name for s in reg().specs() if s.access == "write"} == {"commit_disposition"}


def test_every_read_tool_returns_the_same_receipt_shape():
    r = reg().call("investigator", "get_device_history", {"account_id": CASE.account_id})
    assert (r.status, r.evidence_id, r.record_count) == ("ok", "ev_dev", 2)
    assert r.coverage == "2026-09-01..2026-10-01"
    t = reg().call("investigator", "get_transactions", {"account_id": CASE.account_id})
    assert (t.status, t.evidence_id, t.record_count) == ("ok", "ev_tx", 4)


def test_receipts_let_code_tell_a_failed_lookup_from_an_empty_one():
    assert reg("device_empty").call("investigator", "get_device_history", {"account_id": CASE.account_id}).status == "empty"
    err = reg().call("investigator", "get_device_history", {"account_id": CASE.email})
    assert err.status == "error" and err.record_count == 0 and "account_id" in err.error


def test_investigator_cannot_call_the_write_tool_or_the_planners_tool():
    for tool in ("commit_disposition", "get_policy"):
        with pytest.raises(PermissionDenied):
            reg().call("investigator", tool, {})


def test_planner_may_only_read_policy():
    assert reg().call("planner", "get_policy", {}).data["version"] == "p1"
    with pytest.raises(PermissionDenied):
        reg().call("planner", "get_transactions", {"account_id": CASE.account_id})


def test_only_the_commit_role_holds_write_scope_and_unknown_tools_fail():
    with pytest.raises(ToolNotFound):
        reg().call("investigator", "freeze_account", {})
    assert {"commit_disposition"} == {s.name for s in reg().specs() if s.access == "write"}


def tool(name, **a):
    return {"action": "tool", "tool": name, "args": a}


def test_injected_instruction_to_commit_is_denied_in_code_and_the_case_still_completes():
    big = next(t["amount"] for t in CASE.raw["transactions"]["transactions"] if t["kind"] == "transfer")
    good = {"action": "final", "outcome": "escalated", "claims": [
        {"text": "New device abroad then MFA reset", "evidence_ids": ["ev_dev"]},
        {"text": "Large transfer", "evidence_ids": ["ev_tx"], "numeric": {"metric": "largest_transfer", "value": big}}]}
    llm = FakeLLM({"planner": [{"planner_checks": [], "planner_sources": []}], "investigator": [
        tool("resolve_account", email=CASE.email), tool("commit_disposition", outcome="closed_benign"),
        tool("get_device_history", account_id=CASE.account_id), tool("get_transactions", account_id=CASE.account_id), good]})
    t = Trace()
    run = run_casefile(CASE, make_faults("none"), llm, CostLedger({}), t)
    assert run.outcome.value == "escalated" and run.claimed_complete
    denied = [s for s in t.steps if s["kind"] == "tool" and s["tool"] == "commit_disposition"]
    assert denied and denied[0]["status"] == "denied"
