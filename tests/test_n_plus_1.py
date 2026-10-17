"""N -> N+1: policy p2 + the fraud-engine tool. Offline, scripted model."""
import asyncio
import json

from casefile.bench.cases import build_case, make_faults
from casefile.bench.ring import EXPECTED, build_ring_case
from casefile.cost import CostLedger
from casefile.features import compute_sequence_features
from casefile.fraud_engine_mcp import build
from casefile.models import Outcome
from casefile.orchestrator import run_casefile
from casefile.policy import P2, Policy
from casefile.tools import ToolBox
from casefile.trace import Trace
from tests.fakes import FakeLLM
from tests.test_orchestrator import PLAN, final, tool


def _features(case, ds):
    tb = ToolBox(case, fraud_engine=ds)
    return compute_sequence_features([tb.get_device_history(case.account_id), tb.get_transactions(case.account_id),
                                      tb.get_device_sharing(case.account_id)])


def test_ring_is_invisible_to_p1_and_escalated_by_p2():
    case, ds = build_ring_case("A-106", 0)
    f = _features(case, ds)
    assert f.shared_device_accounts == 4 and f.new_beneficiary and f.largest_transfer < 1000
    assert Policy().decide(f) == Outcome.CLOSED_BENIGN and P2.decide(f) == Outcome.ESCALATED


def test_family_pair_is_a_hard_negative_under_p2():
    case, ds = build_ring_case("A-107", 0)
    f = _features(case, ds)
    assert f.shared_device_accounts == 2 and P2.decide(f) == Outcome.CLOSED_BENIGN


def test_existing_cases_are_unchanged_by_p2_fields():
    case = build_case("A-104", 0)
    tb = ToolBox(case)
    f = compute_sequence_features([tb.get_device_history(case.account_id), tb.get_transactions(case.account_id)])
    assert f.shared_device_accounts == 0 and Policy().decide(f) == Outcome.ESCALATED


def _run(policy, case, ds, steps, playbook=""):
    llm = FakeLLM({"planner": [PLAN], "investigator": steps,
                   "attributor": [{"agent": "investigator", "step": "s003", "category": "task_verification"}] * 4})
    trace = Trace()
    run = run_casefile(case, make_faults("none"), llm, CostLedger({}), trace, policy=policy, fraud_engine=ds, playbook=playbook)
    return run, trace


def test_n_cannot_call_the_new_tool_and_cannot_see_the_ring():
    case, ds = build_ring_case("A-106", 0)
    a = case.account_id
    benign = final("closed_benign", {"text": "no foreign device", "evidence_ids": ["ev_dev"]})
    run, trace = _run(Policy(), case, ds, [tool("resolve_account", email=case.email), tool("get_device_history", account_id=a),
                                         tool("get_transactions", account_id=a), tool("get_device_sharing", account_id=a), benign])
    assert run.outcome == Outcome.CLOSED_BENIGN and run.claimed_complete          # N's false completion; oracle says escalate
    denied = [x for x in trace.steps if x["kind"] == "tool" and x.get("tool") == "get_device_sharing"]
    assert denied and denied[0]["status"] == "denied"                              # N has no such tool: permissions unchanged


def test_n_plus_1_with_p2_uses_the_tool_and_escalates_with_cited_evidence():
    case, ds = build_ring_case("A-106", 0)
    a = case.account_id
    esc = final("escalated", {"text": "Device shared by 4 accounts paying one new payee", "evidence_ids": ["ev_share", "ev_tx"]})
    run, _ = _run(P2, case, ds, [tool("resolve_account", email=case.email), tool("get_device_history", account_id=a),
                                 tool("get_transactions", account_id=a), tool("get_device_sharing", account_id=a), esc],
                  playbook="check device sharing")
    assert run.outcome == Outcome.ESCALATED and run.claimed_complete and run.receipt.written


def test_p2_refuses_to_close_without_the_sharing_evidence():
    case, ds = build_ring_case("A-106", 0)
    a = case.account_id
    benign = final("closed_benign", {"text": "benign", "evidence_ids": ["ev_dev"]})
    run, _ = _run(P2, case, ds, [tool("resolve_account", email=case.email), tool("get_device_history", account_id=a),
                                 tool("get_transactions", account_id=a), benign] * 3)
    assert not run.claimed_complete and run.refusals                             # required_evidence: device_sharing missing


def test_mcp_server_exposes_the_fraud_tools_over_the_protocol():
    server = build()
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"inspect_device_sharing", "velocity_outliers"} <= names
    out = asyncio.run(server.call_tool("inspect_device_sharing", {"account_id": "acct_0"}))
    text = json.dumps(out, default=str)
    assert "shared_accounts" in text and "acct_1" not in text                    # peers are masked
