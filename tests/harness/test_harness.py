"""E1: enterprise harness. Governance and required-field checks run in code BEFORE any model call."""
import json
from datetime import datetime, timezone

import pytest

from casefile.bench.cases import build_case, make_faults
from casefile.cost import CostLedger
from casefile.harness.audit import AuditLog
from casefile.harness.checkpoint import CheckpointStore
from casefile.harness.gates import GovernanceConfig, governance_gate, required_fields_check
from casefile.harness.review import ReviewQueue
from casefile.harness.runner import run_enterprise
from casefile.harness.state import Alert, CaseState, DataClass
from casefile.trace import Trace
from tests.fakes import FakeLLM

UTC = timezone.utc
W0, W1 = datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)
CFG = GovernanceConfig(supported_alert_types={"account_takeover"}, known_policy_versions={"p1"}, allowed_tenants={"t1"})


def alert(**kw):
    base = dict(alert_id="A-104", alert_type="account_takeover", tenant_id="t1", policy_version="p1",
                email="customer104s0@example.test", account_id="acct_1040", window_start=W0, window_end=W1)
    base.update(kw)
    return Alert(**base)


# ---- governance gate -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kw,why", [({"alert_type": "chargeback"}, "alert_type"), ({"policy_version": "p9"}, "policy_version"),
                                    ({"tenant_id": "t2"}, "tenant")])
def test_governance_gate_denies_unsupported_requests(kw, why):
    d = governance_gate(alert(**kw), CFG)
    assert not d.allowed and why in d.reason


def test_governance_gate_allows_supported_requests():
    assert governance_gate(alert(), CFG).allowed


# ---- required fields: never assume a value -----------------------------------------------------------------------
def test_missing_or_malformed_required_fields_are_reported_not_guessed():
    assert required_fields_check(alert()) == []
    assert required_fields_check(alert(account_id=None)) == ["account_id"]
    assert required_fields_check(alert(account_id="customer104s0@example.test")) == ["account_id"]   # the A-104 failure
    assert required_fields_check(alert(window_start=None)) == ["window"]
    assert required_fields_check(alert(window_start=W1, window_end=W0)) == ["window"]


# ---- typed state with data classes -----------------------------------------------------------------------------
def test_model_view_never_contains_pii_or_payment_fields():
    s = CaseState(case_id="A-104", alert=alert(), account_id="acct_1040")
    view = s.model_view()
    assert "email" not in json.dumps(view) and "customer104" not in json.dumps(view)
    assert view["account_id"] == "acct_1040" and view["policy_version"] == "p1"
    assert s.field_classes["email"] == DataClass.PII


# ---- checkpoints -----------------------------------------------------------------------------------------------
def test_checkpoint_store_returns_latest_state_and_survives_reopen(tmp_path):
    store = CheckpointStore(tmp_path)
    s = CaseState(case_id="A-104", alert=alert())
    store.save(s.model_copy(update={"completed": ["intake"]}))
    store.save(s.model_copy(update={"completed": ["intake", "governance"]}))
    assert CheckpointStore(tmp_path).latest("A-104").completed == ["intake", "governance"]
    assert CheckpointStore(tmp_path).latest("nope") is None


# ---- audit trail ------------------------------------------------------------------------------------------------
def test_audit_log_is_hash_chained_and_detects_tampering(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    for i in range(3):
        log.append("commit", "A-104", {"n": i})
    assert log.verify_chain()
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    lines[1] = lines[1].replace('"n": 1', '"n": 9')
    (tmp_path / "audit.jsonl").write_text("\n".join(lines) + "\n")
    assert not AuditLog(tmp_path / "audit.jsonl").verify_chain()


# ---- review queue ------------------------------------------------------------------------------------------------
def test_review_queue_stores_the_analyst_decision_as_the_label(tmp_path):
    q = ReviewQueue(tmp_path / "review.jsonl")
    tid = q.open_task("A-104", "escalated", {"evidence": ["ev_dev"]})
    assert [t["status"] for t in q.tasks()] == ["open"]
    q.decide(tid, analyst="analyst_1", decision="confirm", note="device and MFA match takeover")
    assert q.labels() == {"A-104": "confirm"}
    with pytest.raises(ValueError):
        q.decide(tid, analyst="analyst_2", decision="overturn")        # decisions are append-only, no silent overwrite


# ---- the enterprise runner ----------------------------------------------------------------------------------------
def tool(name, **a):
    return {"action": "tool", "tool": name, "args": a}


CASE = build_case("A-104", 0)
BIG = next(t["amount"] for t in CASE.raw["transactions"]["transactions"] if t["kind"] == "transfer")
GOOD_FINAL = {"action": "final", "outcome": "escalated", "claims": [
    {"text": "New device abroad then MFA reset", "evidence_ids": ["ev_dev"]},
    {"text": "Large transfer", "evidence_ids": ["ev_tx"], "numeric": {"metric": "largest_transfer", "value": BIG}}]}
SCRIPT = {"planner": [{"planner_checks": ["window_covered"], "planner_sources": []}],
          "investigator": [tool("resolve_account", email=CASE.email), tool("get_device_history", account_id=CASE.account_id),
                           tool("get_transactions", account_id=CASE.account_id), GOOD_FINAL]}


def dirs(tmp_path):
    return dict(checkpoints=CheckpointStore(tmp_path / "ck"), audit=AuditLog(tmp_path / "audit.jsonl"),
                review=ReviewQueue(tmp_path / "review.jsonl"))


IDENT = {CASE.email: CASE.account_id}


def go(a, tmp_path, llm, **kw):
    kw.setdefault("identity", IDENT)
    return run_enterprise(a, CASE.raw, make_faults("none"), llm, CostLedger({}), Trace(), config=CFG, **dirs(tmp_path), **kw)


def test_denied_alert_spends_no_tokens(tmp_path):
    llm = FakeLLM({})
    res = go(alert(alert_type="chargeback"), tmp_path, llm)
    assert res.state.status == "rejected" and llm.calls == []
    assert any(e["type"] == "rejected" for e in AuditLog(tmp_path / "audit.jsonl").events())


def test_missing_account_id_is_resolved_by_the_identity_tool_not_guessed_by_a_model(tmp_path):
    llm = FakeLLM(dict(SCRIPT))
    res = go(alert(account_id=None), tmp_path, llm)
    assert res.state.account_id == "acct_1040" and "resolve_account" in res.state.provenance["account_id"]
    assert res.state.status == "done"


def test_email_passed_as_account_id_interrupts_to_a_human_before_any_model_call(tmp_path):
    llm = FakeLLM({})
    res = go(alert(account_id=CASE.email), tmp_path, llm)
    assert res.state.status == "interrupted" and "account_id" in res.state.interrupt_reason and llm.calls == []


def test_unresolvable_identity_interrupts(tmp_path):
    llm = FakeLLM({})
    res = go(alert(account_id=None, email="stranger@example.test"), tmp_path, llm)
    assert res.state.status == "interrupted" and llm.calls == []


def test_escalation_opens_a_review_task_and_never_moves_money(tmp_path):
    res = go(alert(), tmp_path, FakeLLM(dict(SCRIPT)))
    assert res.state.outcome == "escalated" and res.state.review_task_id
    tasks = ReviewQueue(tmp_path / "review.jsonl").tasks()
    assert len(tasks) == 1 and tasks[0]["packet"]["evidence"]
    assert AuditLog(tmp_path / "audit.jsonl").verify_chain()
    assert not any("freeze" in json.dumps(e) for e in AuditLog(tmp_path / "audit.jsonl").events())


def test_resume_after_completion_makes_no_new_model_calls_and_no_duplicate_writes(tmp_path):
    go(alert(), tmp_path, FakeLLM(dict(SCRIPT)))
    again = FakeLLM({})                                   # any model call would raise
    res = go(alert(), tmp_path, again)
    assert res.state.status == "done" and again.calls == []
    assert len(ReviewQueue(tmp_path / "review.jsonl").tasks()) == 1
