"""Integration against the real Supabase project with a scripted model (no Crusoe calls). Run: pytest -m supabase
Every test cleans up by deleting its run (cascades to cases and children)."""
import pytest

from casefile.bench.cases import build_case, make_faults, split_cases
from casefile.cost import CostLedger
from casefile.db_source import SupabaseCaseSource, seed_case
from casefile.models import Outcome
from casefile.orchestrator import run_casefile
from casefile.persist import BenchSink, begin_case, begin_run, persist_run, record_finance_response
from casefile.store import Store
from casefile.trace import Trace
from tests.fakes import FakeLLM
from tests.test_orchestrator import BENIGN_ON_ERROR, GOOD, PLAN, tool

pytestmark = pytest.mark.supabase


@pytest.fixture(scope="module")
def store():
    s = Store()
    if not s.remote:
        pytest.skip("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set")
    for split in ("dev", "heldout"):
        for case, _ in split_cases(split):
            seed_case(s, case)
    return s


@pytest.fixture
def run_id(store):
    rid = begin_run(store, config="C3", split="dev", model_map={"test": "scripted"})
    yield rid
    for r in store.select("grounding_requests", purpose=f"test:{rid}"):
        store.delete("grounding_requests", id=r["id"])
    store.delete("runs", id=rid)


@pytest.mark.parametrize("scenario", ["A-104", "A-105"])
@pytest.mark.parametrize("seed", [0, 1])
def test_supabase_rows_round_trip_to_case_raw(store, scenario, seed):
    case = build_case(scenario, seed)
    src = SupabaseCaseSource(store)
    assert src.resolve_account(case.email, case.tenant_id) == case.account_id
    assert src.load("device_history", case.account_id) == case.raw["device_history"]
    assert src.load("transactions", case.account_id) == case.raw["transactions"]


def test_unknown_email_is_a_lookup_error(store):
    with pytest.raises(LookupError):
        SupabaseCaseSource(store).resolve_account("nobody@example.test", "t1")


def test_seeding_is_idempotent(store):
    assert seed_case(store, build_case("A-104", 0)) == 0


def test_full_run_from_supabase_is_persisted_and_idempotent(store, run_id):
    case = build_case("A-104", 0)
    acct = case.account_id
    trace, ledger = Trace(), CostLedger({})
    llm = FakeLLM({"planner": [PLAN], "investigator": [
        tool("resolve_account", email=case.email), tool("get_device_history", account_id=acct), BENIGN_ON_ERROR,
        tool("get_device_history", account_id=acct), tool("get_transactions", account_id=acct), GOOD],
        "attributor": [{"agent": "investigator", "step": "s003", "category": "task_verification"}]})
    case_uuid = begin_case(store, run_id=run_id, alert_id=case.id, tenant_id=case.tenant_id,
                           account_hint=case.email, faults=["wrong_identifier"])
    run = run_casefile(case, make_faults("wrong_identifier"), llm, ledger, trace, data_source=SupabaseCaseSource(store))
    assert run.outcome == Outcome.ESCALATED and run.claimed_complete          # same result as reading Case.raw

    counts = persist_run(store, case_uuid=case_uuid, run=run, trace=trace, idempotency_prefix=run_id)
    assert counts["disposition_written"] and counts["evidence"] >= 3 and counts["claims"] == 2 and counts["attributions"] == 1

    evidence = store.select("evidence", case_id=case_uuid)
    assert {e["status"] for e in evidence} >= {"ok", "error"}                  # the failed lookup is a receipt too
    assert any(e["status"] == "ok" and e["rows"] for e in evidence)
    claims = store.select("claims", case_id=case_uuid)
    assert all(c["cites"] for c in claims)                                    # claims cite evidence row uuids
    checks = store.select("check_results", case_id=case_uuid)
    assert any(not c["passed"] and "device_history" in (c["reason"] or "") for c in checks)   # the refusal is on record
    assert any(c["passed"] for c in checks)
    assert store.select("contracts", case_id=case_uuid)[0]["sha256"]
    assert len(store.select("events", case_id=case_uuid)) == len(trace.steps)
    case_row = store.select("cases", id=case_uuid)[0]
    assert case_row["disposition"] == "escalated" and case_row["status"] == "done"
    disp = store.select("dispositions", case_id=case_uuid)
    assert len(disp) == 1 and disp[0]["disposition"] == "escalated"

    # replaying the same commit is a no-op: one disposition per idempotency key
    key = disp[0]["idempotency_key"]
    assert store.upsert_ignore("dispositions", {"idempotency_key": key, "case_id": case_uuid, "disposition": "escalated",
                                                "contract_sha256": "x"}, "idempotency_key") is None
    assert len(store.select("dispositions", case_id=case_uuid)) == 1


def test_finance_mcp_response_links_to_case(store, run_id):
    case_uuid = begin_case(store, run_id=run_id, alert_id="finance-link", tenant_id="records", account_hint="n/a")
    row = record_finance_response(store, case_id=case_uuid, tool="you-finance", args={"query": "AAPL revenue FY2025"},
                                  response={"data": "fixture"}, purpose=f"test:{run_id}")
    got = store.select("grounding_requests", id=row["id"])[0]
    assert got["case_id"] == case_uuid and got["endpoint"] == "finance_mcp" and got["tool"] == "you-finance"


def test_same_alert_under_two_faults_gets_two_dispositions(store):
    """Regression: the Gate's idempotency key is built from the alert id, so it must be scoped by the case row."""
    case = build_case("A-104", 0)
    acct = case.account_id
    sink = BenchSink(store, "dev", {"test": "scripted"})
    try:
        for fault in ("none", "wrong_identifier"):
            trace, ledger = Trace(), CostLedger({})
            llm = FakeLLM({"planner": [PLAN], "investigator": [
                tool("resolve_account", email=case.email), tool("get_device_history", account_id=acct),
                tool("get_transactions", account_id=acct), GOOD]})
            case_uuid = sink.start("C3", case, fault)
            rec = run_casefile(case, make_faults("none"), llm, ledger, trace, data_source=sink.data_source)
            sink.finish("C3", case_uuid, rec, trace)
        run_id = sink.run_ids["C3"]
        case_ids = [c["id"] for c in store.select("cases", run_id=run_id)]
        disp = [d for cid in case_ids for d in store.select("dispositions", case_id=cid)]
        assert len(case_ids) == 2 and len(disp) == 2
    finally:
        for rid in sink.run_ids.values():
            store.delete("runs", id=rid)


def test_audit_chain_is_written_verifies_and_detects_tampering(store, run_id):
    from casefile.persist import verify_audit_chain
    case = build_case("A-104", 0)
    acct = case.account_id
    trace, ledger = Trace(), CostLedger({})
    llm = FakeLLM({"planner": [PLAN], "investigator": [
        tool("resolve_account", email=case.email), tool("get_device_history", account_id=acct),
        tool("get_transactions", account_id=acct), GOOD]})
    case_uuid = begin_case(store, run_id=run_id, alert_id=case.id, tenant_id=case.tenant_id, account_hint=case.email)
    run = run_casefile(case, make_faults("none"), llm, ledger, trace, data_source=SupabaseCaseSource(store))
    persist_run(store, case_uuid=case_uuid, run=run, trace=trace, idempotency_prefix=case_uuid)
    rows = store.select("audit_log", order="seq.asc", case_id=case_uuid)
    assert len(rows) == len(trace.steps) + 1 and rows[-1]["type"] == "final"
    assert not any("@" in str(r["data"]) for r in rows)                 # no raw email/arguments in the audit trail
    assert verify_audit_chain(store, case_uuid) == (True, None)
    store.update("audit_log", {"data": {**rows[2]["data"], "status": "ok-edited"}}, id=rows[2]["id"])
    ok, bad = verify_audit_chain(store, case_uuid)
    assert not ok and bad == rows[2]["seq"]
