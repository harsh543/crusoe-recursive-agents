"""Durable case record. Writes the run, case, frozen contract, every evidence receipt, claims, verifier checks,
attributions, trace events and the idempotent disposition to Supabase (or the JSONL fallback).
The Gate stays the only decision-maker; this module records what happened and never changes an outcome."""
import hashlib
import json
from datetime import datetime, timezone

from .models import EvidenceStatus
from .store import Store

SOURCE_OF_EV = {"ev_dev": "device_history", "ev_tx": "transactions"}


def _step_no(step_id) -> int:
    digits = "".join(c for c in str(step_id) if c.isdigit())
    return int(digits) if digits else 0


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def begin_run(store: Store, *, config: str, split: str, model_map: dict, playbook_version: int | None = None) -> str:
    return store.insert("runs", {"config": config, "split": split, "model_map": model_map,
                                 "playbook_version": playbook_version})["id"]


def begin_case(store: Store, *, run_id: str, alert_id: str, tenant_id: str, account_hint: str, faults=()) -> str:
    """Create the case row first so You.com requests made during the run can link to its uuid."""
    return store.insert("cases", {"run_id": run_id, "alert_id": alert_id, "tenant_id": tenant_id,
                                  "account_hint": account_hint, "faults": list(faults), "status": "investigating"})["id"]


def finish_run(store: Store, run_id: str, summary: dict) -> None:
    store.update("runs", {"summary": summary, "finished_at": datetime.now(timezone.utc).isoformat()}, id=run_id)


def record_finance_response(store: Store, *, case_id: str, tool: str, args: dict, response, purpose: str | None = None,
                            error: str | None = None) -> dict:
    """Finance MCP calls happen in the agent host, not in youcom.py. Call this with the tool result to link it to a case."""
    return store.insert("grounding_requests", {"endpoint": "finance_mcp", "tool": tool, "request": args, "response": response,
                                                "error": error, "purpose": purpose, "case_id": case_id})


def persist_run(store: Store, *, case_uuid: str, run, trace, idempotency_prefix: str) -> dict:
    """Persist a finished transaction-mode RunRecord against an existing case row. Returns counts."""
    contract_step = next((s for s in trace.steps if s["kind"] == "contract"), None)
    contract_sha = None
    if contract_step:
        body = {k: contract_step[k] for k in ("version", "checks", "sources") if k in contract_step}
        contract_sha = _sha(body)
        store.insert("contracts", {"case_id": case_uuid, "version": body.get("version", 1), "body": body, "sha256": contract_sha})

    ev_uuid: dict[str, str] = {}
    n_ev = 0
    final = {r.source: r for r in run.evidence}
    for s in trace.steps:                                   # one receipt per tool call, in order
        if s["kind"] != "tool" or s.get("tool") not in ("get_device_history", "get_transactions"):
            continue
        source = "device_history" if s["tool"] == "get_device_history" else "transactions"
        rec = final.get(source)
        ok = s.get("status") == "ok" and rec is not None
        row = {"case_id": case_uuid, "step": _step_no(s["step"]), "tool": s["tool"], "args": s.get("args") or {},
               "status": s.get("status", "error"), "error": s.get("error"),
               "rows": rec.data if ok else [], "account_id": (s.get("args") or {}).get("account_id")}
        if ok:
            row["coverage"] = f"[{rec.covers_from.isoformat()},{rec.covers_to.isoformat()})"
        out = store.insert("evidence", row)
        n_ev += 1
        if ok:
            ev_uuid[source] = out["id"]

    n_claims = 0
    if run.recommendation:
        for c in run.recommendation.claims:
            cites = [ev_uuid[SOURCE_OF_EV[e]] for e in c.evidence_ids if SOURCE_OF_EV.get(e) in ev_uuid]
            store.insert("claims", {"case_id": case_uuid, "attempt": run.replans, "text": c.text, "claim_ref": c.id,
                                    "numeric_value": c.numeric.value if c.numeric else None, "cites": cites})
            n_claims += 1

    n_checks, attempt = 0, 0
    checks = list(contract_step["checks"]) if contract_step else []
    for s in trace.steps:
        if s["kind"] != "verify":
            continue
        failed = {f["check"]: f["reason"] for f in s.get("failures", [])}
        for cid in checks or sorted(failed):
            store.insert("check_results", {"case_id": case_uuid, "attempt": attempt, "check_id": cid,
                                           "passed": cid not in failed, "reason": failed.get(cid)})
            n_checks += 1
        attempt += 1

    for a in run.attributions:
        store.insert("attributions", {"case_id": case_uuid, "attempt": 0, "agent": a.agent, "step": _step_no(a.step),
                                      "category": a.category.value, "model": "nvidia/Nemotron-3.5-Lightning-30B-A3B"})

    for s in trace.steps:
        store.insert("events", {"case_id": case_uuid, "state": s["kind"], "role": s.get("role"), "step": _step_no(s["step"]),
                                "detail": json.loads(json.dumps(s, default=str))})

    write_audit_chain(store, case_uuid, trace.steps, {"outcome": run.outcome.value, "claimed_complete": run.claimed_complete,
                                                      "receipt": getattr(run.receipt, "id", None), "contract_sha256": contract_sha,
                                                      "replans": run.replans, "cost_usd": run.cost_usd})
    disp_written = False
    if run.receipt is not None:
        key = f"{idempotency_prefix}:{run.receipt.idempotency_key}"
        disp_written = store.upsert_ignore("dispositions", {"idempotency_key": key, "case_id": case_uuid,
                                                            "disposition": run.outcome.value, "contract_sha256": contract_sha},
                                           "idempotency_key") is not None
    store.update("cases", {"status": "done", "disposition": run.outcome.value,
                           "evidence_collection": "succeeded" if run.claimed_complete or run.outcome.value != "collection_failed" else "failed",
                           "replans": run.replans, "tool_calls": n_ev, "closed_at": datetime.now(timezone.utc).isoformat()}, id=case_uuid)
    return {"evidence": n_ev, "claims": n_claims, "checks": n_checks, "events": len(trace.steps),
            "attributions": len(run.attributions), "disposition_written": disp_written}


_AUDIT_KEYS = ("step", "role", "kind", "tool", "status", "model", "input_tokens", "cached_tokens", "output_tokens", "latency_ms",
               "cost_usd", "finish_reason", "attempt", "outcome", "receipt", "passed", "agent", "category", "blamed_step",
               "version", "checks", "sources", "approve", "context_id", "task_id")


def _audit_body(seq: int, case_uuid: str, type_: str, data: dict) -> dict:
    return {"seq": seq, "type": type_, "case_id": case_uuid, "data": data}


def _chain_hash(prev: str, body: dict) -> str:
    return hashlib.sha256((prev + json.dumps(body, sort_keys=True, default=str)).encode()).hexdigest()


def write_audit_chain(store: Store, case_uuid: str, steps: list[dict], final: dict) -> int:
    """Observable actions only: no prompts, no chain-of-thought, no raw tool arguments (a hash of them instead)."""
    entries = []
    for s in steps:
        d = {k: s[k] for k in _AUDIT_KEYS if k in s}
        if s.get("args") is not None:
            d["args_sha256"] = _sha(s["args"])
        if s.get("error"):
            d["error"] = str(s["error"])[:200]
        if s.get("failures"):
            d["failed_checks"] = sorted({f["check"] for f in s["failures"]})
        entries.append((s["kind"], json.loads(json.dumps(d, default=str))))
    entries.append(("final", json.loads(json.dumps(final, default=str))))
    prev = "genesis"
    for seq, (type_, data) in enumerate(entries, 1):
        h = _chain_hash(prev, _audit_body(seq, case_uuid, type_, data))
        store.insert("audit_log", {"case_id": case_uuid, "seq": seq, "type": type_, "data": data, "prev": prev, "hash": h})
        prev = h
    return len(entries)


def verify_audit_chain(store: Store, case_uuid: str) -> tuple[bool, int | None]:
    """(ok, first_bad_seq). Detects edited, deleted, reordered or inserted rows."""
    prev = "genesis"
    for i, row in enumerate(store.select("audit_log", order="seq.asc", case_id=case_uuid), 1):
        body = _audit_body(row["seq"], case_uuid, row["type"], row["data"])
        if row["seq"] != i or row["prev"] != prev or row["hash"] != _chain_hash(prev, body):
            return False, row["seq"]
        prev = row["hash"]
    return True, None


def persist_records(store: Store, *, case_uuid: str, claim_runs, trace, idempotency_prefix: str) -> dict:
    """Persist records-mode results: one claim row and one idempotent disposition (the verdict) per claim."""
    n_claims = n_disp = 0
    for r in claim_runs:
        c, res = r.claim, r.result
        store.insert("claims", {"case_id": case_uuid, "attempt": r.replans, "text": c.text, "claim_ref": c.id,
                                "claim_type": c.claim_type.value, "verdict": res.verdict.value})
        n_claims += 1
        for i, f in enumerate(getattr(r.verification, "failures", []) or []):
            store.insert("check_results", {"case_id": case_uuid, "attempt": r.replans, "check_id": f"{c.id}:{f.check}",
                                           "passed": False, "reason": f.reason})
        key = f"{idempotency_prefix}:{getattr(r.receipt, 'idempotency_key', c.id)}"
        n_disp += store.upsert_ignore("dispositions", {"idempotency_key": key, "case_id": case_uuid,
                                                       "disposition": res.verdict.value, "claim_ref": c.id},
                                      "idempotency_key") is not None
    for s in trace.steps:
        store.insert("events", {"case_id": case_uuid, "state": s["kind"], "role": s.get("role"), "step": _step_no(s["step"]),
                                "detail": json.loads(json.dumps(s, default=str))})
    store.update("cases", {"status": "done", "closed_at": datetime.now(timezone.utc).isoformat()}, id=case_uuid)
    return {"claims": n_claims, "dispositions": n_disp, "events": len(trace.steps)}


class BenchSink:
    """Persists a benchmark run: one `runs` row per config, one `cases` row per (case, fault), full audit via persist_run."""

    def __init__(self, store: Store, split: str, models: dict, playbook_version: int | None = None):
        from .db_source import SupabaseCaseSource
        self.store, self.split, self.models, self.playbook_version = store, split, models, playbook_version
        self.data_source = SupabaseCaseSource(store)
        self.run_ids: dict[str, str] = {}

    def start(self, config: str, case, fault: str) -> str:
        if config not in self.run_ids:
            self.run_ids[config] = begin_run(self.store, config=config, split=self.split, model_map=self.models,
                                             playbook_version=self.playbook_version)
        return begin_case(self.store, run_id=self.run_ids[config], alert_id=f"{case.id}:{fault}", tenant_id=case.tenant_id,
                          account_hint=case.email, faults=[] if fault == "none" else [fault])

    def finish(self, config: str, case_uuid: str, rec, trace) -> dict:
        if rec is None:                                       # crashed run: keep the trace, mark the case done without a disposition
            for s in trace.steps:
                self.store.insert("events", {"case_id": case_uuid, "state": s["kind"], "role": s.get("role"),
                                             "step": _step_no(s["step"]), "detail": json.loads(json.dumps(s, default=str))})
            self.store.update("cases", {"status": "done"}, id=case_uuid)
            return {}
        return persist_run(self.store, case_uuid=case_uuid, run=rec, trace=trace, idempotency_prefix=case_uuid)   # case uuid, not alert id: one alert runs under several faults

    def close(self, summary: dict) -> None:
        for cfg, rid in self.run_ids.items():
            finish_run(self.store, rid, summary.get(cfg, {}))
