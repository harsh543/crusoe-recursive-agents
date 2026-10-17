"""L2: the full loop against a scripted model. Proves the control flow, not the model."""
import pytest

from casefile import oracle
from casefile.bench.cases import build_case, make_faults
from casefile.cost import CostLedger
from casefile.models import Outcome
from casefile.orchestrator import run_casefile, run_critic, run_single
from casefile.trace import Trace
from tests.fakes import FakeLLM

CASE = build_case("A-104", 0)
ACCT = CASE.account_id
BIG = next(t["amount"] for t in CASE.raw["transactions"]["transactions"] if t["kind"] == "transfer")


def tool(name, **args):
    return {"action": "tool", "tool": name, "args": args}


def final(outcome, *claims):
    return {"action": "final", "outcome": outcome, "claims": list(claims)}


BENIGN_ON_ERROR = final("closed_benign", {"text": "No new devices found; benign.", "evidence_ids": ["ev_dev"]})
GOOD = final("escalated",
             {"text": "New device abroad then MFA reset", "evidence_ids": ["ev_dev"]},
             {"text": "Large transfer", "evidence_ids": ["ev_tx"],
              "numeric": {"metric": "largest_transfer", "value": BIG}})
PLAN = {"planner_checks": ["window_covered"], "planner_sources": []}


def setup():
    return Trace(), CostLedger({})


def test_wrong_identifier_is_refused_attributed_and_repaired():
    trace, ledger = setup()
    llm = FakeLLM({
        "planner": [PLAN],
        "investigator": [
            tool("resolve_account", email=CASE.email), tool("get_device_history", account_id=ACCT),
            BENIGN_ON_ERROR,                                                   # fluent but unsupported
            tool("get_device_history", account_id=ACCT), tool("get_transactions", account_id=ACCT), GOOD,
        ],
        # steps: s001 contract, s002 resolve, s003 device lookup (the email was swapped in here)
        "attributor": [{"agent": "investigator", "step": "s003", "category": "task_verification"}],
    })
    run = run_casefile(CASE, make_faults("wrong_identifier"), llm, ledger, trace)
    assert run.outcome == Outcome.ESCALATED and run.claimed_complete
    assert run.replans == 1 and run.receipt.written
    assert len(run.refusals) == 1 and "device_history" in run.refusals[0]
    assert (run.attributions[0].agent, run.attributions[0].step) == ("investigator", "s003")
    first_lookup = next(s for s in trace.steps if s["kind"] == "tool" and s["tool"] == "get_device_history")
    assert first_lookup["step"] == "s003" and first_lookup["status"] == "error"


def test_persistent_missing_evidence_never_closes_benign():
    trace, ledger = setup()
    give_up = final("insufficient_evidence")
    llm = FakeLLM({
        "planner": [PLAN],
        "investigator": [tool("resolve_account", email=CASE.email), tool("get_device_history", account_id=ACCT),
                         tool("get_transactions", account_id=ACCT), BENIGN_ON_ERROR, give_up, give_up],
        "attributor": [{"agent": "investigator", "step": "s002", "category": "task_verification"}] * 3,
    })
    run = run_casefile(CASE, make_faults("device_empty"), llm, ledger, trace)
    assert run.outcome == Outcome.INSUFFICIENT_EVIDENCE and not run.claimed_complete
    assert run.receipt.outcome == Outcome.INSUFFICIENT_EVIDENCE
    assert run.replans == 2


def test_persistent_error_is_collection_failed():
    trace, ledger = setup()
    give_up = final("insufficient_evidence")
    llm = FakeLLM({
        "planner": [PLAN],
        "investigator": [tool("resolve_account", email=CASE.email), tool("get_device_history", account_id=ACCT),
                         tool("get_transactions", account_id=ACCT), give_up, give_up, give_up],
        "attributor": [{"agent": "investigator", "step": "s002", "category": "task_verification"}] * 3,
    })
    run = run_casefile(CASE, make_faults("none") if False else make_faults("device_error_once"), llm, ledger, trace)
    # device_error_once recovers on retry only if the agent retries; here it never does
    assert run.outcome == Outcome.COLLECTION_FAILED


def test_transient_error_with_interrupted_write_recovers_with_one_write():
    trace, ledger = setup()
    llm = FakeLLM({
        "planner": [PLAN],
        "investigator": [tool("resolve_account", email=CASE.email), tool("get_device_history", account_id=ACCT),
                         tool("get_device_history", account_id=ACCT), tool("get_transactions", account_id=ACCT), GOOD],
    })
    run = run_casefile(CASE, make_faults("device_error_once"), llm, ledger, trace, interrupt_write=True)
    assert run.outcome == Outcome.ESCALATED and run.claimed_complete and run.receipt.written
    assert run.replans == 0


def test_invalid_plan_falls_back_and_is_recorded():
    trace, ledger = setup()
    llm = FakeLLM({
        "planner": [{"planner_checks": ["trust_me"]}, {"planner_checks": ["also_bad"]}],
        "investigator": [tool("resolve_account", email=CASE.email), tool("get_device_history", account_id=ACCT),
                         tool("get_transactions", account_id=ACCT), GOOD],
    })
    run = run_casefile(CASE, make_faults("none"), llm, ledger, trace)
    assert run.outcome == Outcome.ESCALATED
    assert any(s["kind"] == "fallback" for s in trace.steps)


def test_same_call_without_new_evidence_is_cut_off():
    trace, ledger = setup()
    llm = FakeLLM({"investigator": [tool("get_transactions", account_id=ACCT)] * 4})
    run = run_single(CASE, make_faults("none"), llm, ledger, trace)
    assert run.outcome == Outcome.INSUFFICIENT_EVIDENCE and not run.claimed_complete   # looped, stopped


def test_baseline_single_agent_closes_benign_on_failed_lookup_and_oracle_catches_it():
    trace, ledger = setup()
    llm = FakeLLM({"investigator": [tool("resolve_account", email=CASE.email),
                                    tool("get_device_history", account_id=ACCT), BENIGN_ON_ERROR]})
    run = run_single(CASE, make_faults("wrong_identifier"), llm, ledger, trace)
    labels = {"A-104-s0:wrong_identifier": "escalated"}
    assert run.claimed_complete and run.outcome == Outcome.CLOSED_BENIGN
    assert oracle.judge("A-104-s0:wrong_identifier", run.outcome, run.evidence, labels) is False


def test_critic_that_approves_a_fluent_wrong_answer_does_not_fix_it():
    trace, ledger = setup()
    llm = FakeLLM({"investigator": [tool("resolve_account", email=CASE.email),
                                    tool("get_device_history", account_id=ACCT), BENIGN_ON_ERROR],
                   "critic": [{"approve": True, "reason": "reads well"}]})
    run = run_critic(CASE, make_faults("wrong_identifier"), llm, ledger, trace)
    assert run.claimed_complete and run.outcome == Outcome.CLOSED_BENIGN


def test_investigator_prompt_has_no_ground_truth_and_no_account_id_up_front():
    trace, ledger = setup()
    att = {"agent": "investigator", "step": "s001", "category": "task_verification"}   # not a tool step: rejected
    llm = FakeLLM({"planner": [PLAN], "investigator": [final("insufficient_evidence")] * 3,
                   "attributor": [att] * 3, "attributor_escalate": [att] * 3})
    run_casefile(CASE, make_faults("none"), llm, ledger, trace)
    first_prompt = " ".join(m["content"] for m in next(m for r, m in llm.calls if r == "investigator"))
    assert ACCT not in first_prompt                                  # must be resolved through the tool
    assert "label" not in first_prompt.lower() and "oracle" not in first_prompt.lower()


def test_build_case_rejects_unknown_scenarios():
    with pytest.raises(ValueError):
        build_case("A-105 none", 0)
