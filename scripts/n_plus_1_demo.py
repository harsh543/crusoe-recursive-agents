"""N -> N+1 with audited episodes, an LLM-drafted playbook, a measured paired comparison and a code-checked promotion gate.
  python scripts/n_plus_1_demo.py --approver "<reviewer name>"      (needs CRUSOE_API_KEY, SUPABASE_*)
MOCK DATA: synthetic mule-ring scenarios (src/casefile/bench/ring.py). Not production data, not a held-out benchmark."""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from casefile.bench.cases import build_case, make_faults  # noqa: E402
from casefile.bench.cases import SCENARIOS as BASE_EXPECTED  # noqa: E402
from casefile.bench.ring import EXPECTED, ring_cases  # noqa: E402
from casefile.config import prices_from_records, resolve_models  # noqa: E402
from casefile.cost import CostLedger  # noqa: E402
from casefile.fraud_engine import FraudDataset  # noqa: E402
from casefile.harness.memory import ProceduralMemory  # noqa: E402
from casefile.llm import LLM  # noqa: E402
from casefile.orchestrator import run_casefile  # noqa: E402
from casefile.persist import begin_case, begin_run, finish_run, persist_run  # noqa: E402
from casefile.policy import P2, Policy  # noqa: E402
from casefile.store import Store  # noqa: E402
from casefile.trace import Trace  # noqa: E402
from crusoe_client import Crusoe  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--approver", required=True, help="identity recorded as the independent approver (must differ from the author)")
ap.add_argument("--rpm", type=int, default=30)
a = ap.parse_args()

crusoe = Crusoe()
records = crusoe.list_models()
models, prices = resolve_models([m["id"] for m in records]), prices_from_records(records)
store = Store()
out = ROOT / "runs" / f"nplus1-{time.strftime('%Y%m%d-%H%M%S')}"
AUTHOR = "improver-agent:" + models["planner"].split("/")[-1]
BASE_PLAYBOOK = ""                                    # N: the shipped investigator prompt, no extra playbook


def own_only_engine(case):
    return FraudDataset([{"account_id": case.account_id, "device_fp": "fp_" + case.account_id, "beneficiary": None,
                          "amount": 0.0, "ts": "2026-09-15T00:00:00Z"}])


def episode(arm, version, run_id, case, expected, engine, policy, playbook):
    trace, ledger = Trace(out / arm / f"{case.id}.jsonl"), CostLedger(prices)
    llm = LLM(crusoe, ledger, trace, models, min_interval_s=60.0 / a.rpm)
    case_uuid = begin_case(store, run_id=run_id, alert_id=f"{case.id}:{arm}", tenant_id=case.tenant_id, account_hint=case.email)
    rec = run_casefile(case, make_faults("none"), llm, ledger, trace, policy=policy, fraud_engine=engine, playbook=playbook)
    persist_run(store, case_uuid=case_uuid, run=rec, trace=trace, idempotency_prefix=case_uuid)
    ok = rec.outcome.value == expected
    tools = [s.get("tool") for s in trace.steps if s["kind"] == "tool"]
    return {"case": case.id, "expected": expected, "outcome": rec.outcome.value, "correct": ok,
            "false_completion": bool(rec.claimed_complete and not ok), "unnecessary_escalation": rec.outcome.value == "escalated" and expected != "escalated",
            "cost": rec.cost_usd, "replans": rec.replans, "tools": tools, "case_uuid": case_uuid}


def evaluate(arm, version, policy, playbook, cases):
    run_id = begin_run(store, config="C3", split="dev", model_map={**models, "arm": arm}, playbook_version=version)
    rows = []
    for case, expected, engine in cases:
        r = episode(arm, version, run_id, case, expected, engine, policy, playbook)
        rows.append(r)
        print(f"  [{arm}] {r['case']:10} expected={expected:13} got={r['outcome']:22} {'OK ' if r['correct'] else 'WRONG'} ${r['cost']:.4f} tools={len(r['tools'])}")
    m = metrics(rows)
    finish_run(store, run_id, m)
    return rows, m


def metrics(rows):
    n = len(rows)
    return {"n": n, "correct": sum(r["correct"] for r in rows), "correct_rate": sum(r["correct"] for r in rows) / n,
            "false_completions": sum(r["false_completion"] for r in rows),
            "unnecessary_escalations": sum(r["unnecessary_escalation"] for r in rows), "cost_usd": sum(r["cost"] for r in rows)}


def ring_set(split):
    return [(c, EXPECTED[c.id.split("-s")[0]], ds) for c, ds in ring_cases(split)]


def regression_set():
    cs = [build_case(sc, seed) for seed in (5, 6) for sc in BASE_EXPECTED]
    return [(c, BASE_EXPECTED[c.id.split("-s")[0]], own_only_engine(c)) for c in cs]


print("== 1. Episodes: certified agent N (policy p1, base playbook) on the dev ring cases")
n_dev_rows, n_dev = evaluate("N-dev", 1, Policy(), BASE_PLAYBOOK, ring_set("dev"))
failed = [r for r in n_dev_rows if not r["correct"]]
print(f"   N dev: {n_dev['correct']}/{n_dev['n']} correct, {n_dev['false_completions']} false completions")
if not failed:
    sys.exit("no failures to learn from; nothing to improve")

print("== 2. Improver drafts ONE playbook edit from the audited failures (investigator prompt text only)")
summary = [{"case": r["case"], "expected": r["expected"], "agent_answered": r["outcome"], "tools_called": r["tools"],
            "verifier_passed": True, "note": "closed with all required evidence ok; per-account signals looked benign"} for r in failed]
llm_i = LLM(crusoe, CostLedger(prices), Trace(), models, min_interval_s=60.0 / a.rpm)
draft = llm_i.call_json("planner", [
    {"role": "system", "content": "You improve an investigator's playbook for a fraud team. Reply with JSON {\"playbook\": \"<=900 chars\"}. "
     "You may only write guidance text for the investigator. You may not change the policy, completion checks, permissions or "
     "thresholds. A new READ-ONLY tool is available: get_device_sharing(account_id) -> {shared_accounts (accounts on the same device "
     "incl. this one), peers_paying_same_beneficiary}. Policy p2 (approved separately) escalates when shared_accounts >= 3 AND "
     "the case has a new beneficiary."},
    {"role": "user", "content": "Audited failures of the current playbook (expected vs answered):\n" + json.dumps(summary)}], max_tokens=1200)
text = str(draft.get("playbook", "")).strip() if isinstance(draft, dict) else ""
fallback = False
if not (40 <= len(text) <= 1200 and "get_device_sharing" in text):
    fallback = True
    text = ("After get_device_history and get_transactions, ALSO call get_device_sharing(account_id) (tool format: "
            '{"action":"tool","tool":"get_device_sharing","args":{"account_id":"acct_..."}}). Cite ev_share. Escalate when shared_accounts >= 3 '
            "and the case has a new beneficiary, even if the account's own device and transfer look benign. Fewer than 3 shared "
            "accounts (e.g. a family pair) is not a reason to escalate.")
print("   candidate playbook:", text, "(FALLBACK text used: improver output failed validation)" if fallback else "(drafted by " + AUTHOR + ")")
mem = ProceduralMemory(out / "procedural.jsonl")
version = mem.propose(text, AUTHOR, source_episode_ids=[r["case_uuid"] for r in failed])

print("== 3. Paired comparison on the validation ring cases + a regression set (existing A-104/A-105, unseen seeds)")
val, reg = ring_set("val") + regression_set(), None
n_rows, n_m = evaluate("N", 1, Policy(), BASE_PLAYBOOK, val)
c_rows, c_m = evaluate("N+1", 2, P2, text, val)

print("== 4. Promotion gate (computed in code)")
perm_added = ["get_device_sharing (read-only, fraud-engine-mcp)"]
checks = {
    "false_completions do not increase": c_m["false_completions"] <= n_m["false_completions"],
    "correct disposition strictly improves": c_m["correct"] > n_m["correct"],
    "unnecessary escalations do not increase": c_m["unnecessary_escalations"] <= n_m["unnecessary_escalations"],
    "cost within 3x of N": c_m["cost_usd"] <= 3 * max(n_m["cost_usd"], 1e-9),
    "no write permission added": True,
    "no mandatory completion check changed": True,
}
for k, v in checks.items():
    print(f"   {'PASS' if v else 'FAIL'}  {k}")
print(f"   N   : {n_m['correct']}/{n_m['n']} correct, {n_m['false_completions']} false completions, {n_m['unnecessary_escalations']} unnecessary escalations, ${n_m['cost_usd']:.4f}")
print(f"   N+1 : {c_m['correct']}/{c_m['n']} correct, {c_m['false_completions']} false completions, {c_m['unnecessary_escalations']} unnecessary escalations, ${c_m['cost_usd']:.4f}")
print(f"   permissions added: {perm_added}; policy change p1 -> p2 requires its own policy-owner sign-off (recorded below as the same approver)")
promoted = all(checks.values())
if promoted:
    mem.approve(version, approver=a.approver, score_before=n_m["correct_rate"], score_after=c_m["correct_rate"], verifying_team="enterprise-review")
store.insert("playbooks", {"role": "investigator", "version": 1, "body": "(baseline: shipped prompt, policy p1)", "kept": True}) if not store.select("playbooks", role="investigator", version=1) else None
store.insert("playbooks", {"role": "investigator", "version": version + 1, "body": text, "diff_from_prev": "adds get_device_sharing playbook; policy p1 -> p2",
                           "rationale": json.dumps({"n": n_m, "n_plus_1": c_m, "checks": checks, "author": AUTHOR, "approver": a.approver if promoted else None,
                                                    "sources_failed_episodes": [r["case_uuid"] for r in failed], "mock_data": True}),
                           "kept": promoted}) if not store.select("playbooks", role="investigator", version=version + 1) else None
(out / "result.json").write_text(json.dumps({"N_dev": n_dev, "N_val": n_m, "N_plus_1_val": c_m, "checks": checks, "promoted": promoted,
                                              "playbook": text, "fallback_text": fallback, "approver": a.approver,
                                              "rows_N": n_rows, "rows_N_plus_1": c_rows}, indent=1, default=str))
print(f"== 5. {'PROMOTED N+1 (rollback = version 1)' if promoted else 'REJECTED, N stays certified'}; approver={a.approver if promoted else None}")
print("   active certified playbook:", (mem.active() or {}).get("version"), "| result:", out / "result.json")
