"""Enterprise harness on live Crusoe: python scripts/enterprise_demo.py
Three alerts: (1) A-104 with the wrong-identifier fault, (2) an unsupported alert type (no tokens spent), (3) an email passed as account_id (interrupt)."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from casefile.bench.cases import build_case, make_faults  # noqa: E402
from casefile.config import prices_from_records, resolve_models  # noqa: E402
from casefile.cost import CostLedger  # noqa: E402
from casefile.harness.agents import DEFAULT_AGENTS, AgentRegistry  # noqa: E402
from casefile.harness.audit import AuditLog  # noqa: E402
from casefile.harness.checkpoint import CheckpointStore  # noqa: E402
from casefile.harness.gates import GovernanceConfig  # noqa: E402
from casefile.harness.review import ReviewQueue  # noqa: E402
from casefile.harness.router import ModelRouter  # noqa: E402
from casefile.harness.runner import run_enterprise  # noqa: E402
from casefile.harness.state import Alert  # noqa: E402
from casefile.llm import LLM  # noqa: E402
from casefile.trace import Trace  # noqa: E402
from crusoe_client import Crusoe  # noqa: E402

crusoe = Crusoe()
recs = crusoe.list_models()
models, prices = resolve_models([m["id"] for m in recs]), prices_from_records(recs)
small, big = models["investigator"], models["planner"]
role_models = {"planner": {big}, "intake": {big}, "attributor_escalate": {big}, "investigator": {small}, "attributor": {small},
               "critic": {small}, "records_investigator": {small}}
out = ROOT / "runs" / f"enterprise-{time.strftime('%Y%m%d-%H%M%S')}"
cfg = GovernanceConfig({"account_takeover"}, {"p1"}, {"t1"})
audit, review, ck = AuditLog(out / "audit.jsonl"), ReviewQueue(out / "review.jsonl"), CheckpointStore(out / "checkpoints")
case = build_case("A-104", 0)
base = dict(alert_type="account_takeover", tenant_id="t1", policy_version="p1", email=case.email,
            window_start=case.window_start, window_end=case.window_end)
scenarios = [("A-104 wrong-identifier fault", Alert(alert_id="A-104", account_id=None, **base), "wrong_identifier"),
             ("unsupported alert type", Alert(alert_id="X-1", **{**base, "alert_type": "chargeback"}), "none"),
             ("email passed as account_id", Alert(alert_id="X-2", account_id=case.email, **base), "none")]
for title, alert, fault in scenarios:
    log = out / f"router-{alert.alert_id}.jsonl"
    router = ModelRouter(crusoe, allowlist={small, big}, prices=prices, max_usd=0.05, case_id=alert.alert_id, log_path=log, role_models=role_models)
    trace, ledger = Trace(out / f"trace-{alert.alert_id}.jsonl"), CostLedger(prices)
    llm = LLM(router, ledger, trace, models, min_interval_s=2.0)
    res = run_enterprise(alert, case.raw, make_faults(fault), llm, ledger, trace, config=cfg, checkpoints=ck, audit=audit, review=review,
                         identity={case.email: case.account_id}, agents=AgentRegistry(DEFAULT_AGENTS))
    calls = [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
    s = res.state
    print(f"== {title}\n   status={s.status} outcome={s.outcome} review_task={s.review_task_id} "
          f"{('reason: ' + (s.reject_reason or s.interrupt_reason)) if (s.reject_reason or s.interrupt_reason) else ''}\n"
          f"   model calls={len(calls)} spent=${router.spent_usd:.4f} pii_tokens_masked={sum(c['pii_tokens'] for c in calls)} "
          f"completed_nodes={s.completed}", flush=True)
print(f"\naudit chain intact: {audit.verify_chain()} ({len(audit.events())} events)")
print("review queue:", [(t['task_id'], t['case_id'], t['outcome'], t['status']) for t in review.tasks()])
raw = "".join(p.read_text() for p in out.glob("router-*.jsonl"))
print(f"raw email present in any router log: {case.email in raw}")
print("artifacts:", out)
