"""Verify a case file with fixtures or live You.com Search -> Contents retrieval."""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from casefile.config import prices_from_records, resolve_models  # noqa: E402
from casefile.cost import CostLedger  # noqa: E402
from casefile.llm import LLM  # noqa: E402
from casefile.records.orchestrator import run_case_file  # noqa: E402
from casefile.records.report import render_markdown  # noqa: E402
from casefile.records.sources import YouComSource, extract_source_urls, load_fixtures  # noqa: E402
from casefile.trace import Trace  # noqa: E402
from crusoe_client import Crusoe  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("casefile")
source_group = ap.add_mutually_exclusive_group(required=True)
source_group.add_argument("--fixtures", help="JSON documents for an offline, reproducible run")
source_group.add_argument("--youcom", action="store_true",
                          help="discover URLs with You.com Search, then extract only the exact URLs with Contents")
ap.add_argument("--include-domain", action="append", default=[],
                help="You.com domain allowlist; repeat for multiple domains")
ap.add_argument("--reveal", action="store_true", help="show original names (default: pseudonymized)")
ap.add_argument("--labels", help="optional expected verdicts {statement_number: verdict} to score the run")
ap.add_argument("--rpm", type=int, default=30)
a = ap.parse_args()
case_path = Path(a.casefile)
case_text = case_path.read_text()

crusoe = Crusoe()
records = crusoe.list_models()
models, prices = resolve_models([m["id"] for m in records]), prices_from_records(records)
out = ROOT / "runs" / f"casefile-{time.strftime('%Y%m%d-%H%M%S')}-{case_path.stem}"
trace, ledger = Trace(out / "trace.jsonl"), None
ledger = CostLedger(prices)
llm = LLM(crusoe, ledger, trace, models, min_interval_s=60.0 / a.rpm)
from casefile.persist import begin_case, begin_run, persist_records  # noqa: E402
from casefile.store import Store  # noqa: E402
store = Store()
run_id = begin_run(store, config="records", split="dev", model_map=models) if store.remote else None
case_uuid = begin_case(store, run_id=run_id, alert_id=case_path.stem, tenant_id="records", account_hint="n/a") if run_id else None
if a.youcom:
    seed_urls, rejected = extract_source_urls(case_text)
    source = YouComSource(seed_urls=seed_urls, include_domains=a.include_domain,
                          purpose=f"records_case:{case_path.stem}", case_id=case_uuid)
    source.rejected_urls.extend(item for item in rejected if item not in source.rejected_urls)
else:
    source = load_fixtures(a.fixtures)
claims, entities, skipped, runs, pseudo, secs = run_case_file(case_text, source, llm, trace)
docs = {d.id: d for d in source.documents}
report = render_markdown(title=f"Case file report: {case_path.stem}", claims=claims,
                         results=[r.result for r in runs], docs=docs, pseudonyms=pseudo, reveal=a.reveal)
(out / "report.md").write_text(report)
def _p(x):                                           # same pseudonymization as the report unless --reveal
    return x if a.reveal else pseudo.apply(x)


def _doc(d):
    return {"id": d.id, "url": d.url, "title": _p(d.title), "publisher": d.publisher, "doc_type": d.doc_type.value,
            "retrieved_at": d.retrieved_at.isoformat(), "sha256": d.sha256}


def _trail(claim_id):
    """Ordered reasoning/grounding chain for one claim, from the trace plus the documents You.com retrieved."""
    def dsum(i):
        d = docs.get(i)
        return {"id": i, "title": _p(d.title), "publisher": d.publisher, "url": d.url, "doc_type": d.doc_type.value,
                "sha256": d.sha256, "retrieved_at": d.retrieved_at.isoformat()} if d else {"id": i}
    inv_model, att_model = models["records_investigator"].split("/")[-1], models["attributor"].split("/")[-1]
    out_ = []
    for t in trace.steps:
        if t.get("claim") != claim_id:
            continue
        k = t["kind"]
        if k == "tool" and t.get("tool") == "search_documents":
            out_.append({"type": "search", "by": inv_model, "query": _p(t["args"].get("query", "")), "hits": [dsum(i) for i in t.get("hits", [])]})
        elif k == "tool" and t.get("tool") == "read_document":
            out_.append({"type": "read", "by": inv_model, "doc": dsum(t["args"].get("doc_id", "")), "status": t.get("status"),
                         "note": t.get("note")})
        elif k == "final":
            out_.append({"type": "propose", "by": inv_model, "verdict": t["verdict"], "explanation": _p(t.get("explanation") or ""),
                         "findings": [{"field": f["field"], "value": _p(str(f["value"])), "quote": _p(f["quote"]), "doc": dsum(f["doc_id"])}
                                      for f in t.get("proposed", [])]})
        elif k == "verify":
            out_.append({"type": "verify", "by": "code (no model)", "passed": t["passed"],
                         "failures": [{"check": f["check"], "reason": _p(f["reason"])} for f in t["failures"]]})
        elif k == "refused":
            out_.append({"type": "gate_refused", "by": "Gate (code)", "verdict": t["verdict"], "reason": _p(t["reason"])})
        elif k == "attribution":
            out_.append({"type": "attribution", "by": att_model, "agent": t["agent"], "category": t["category"]})
        elif k == "commit":
            out_.append({"type": "gate_commit", "by": "Gate (code)", "verdict": t["verdict"]})
        elif k in ("stopped", "invalid_final"):
            out_.append({"type": "note", "by": inv_model, "text": _p(t.get("reason") or t.get("error") or k)})
    return out_


(out / "result.json").write_text(json.dumps({
    "case": case_path.stem, "mode": "live" if a.youcom else "fixture", "seconds": round(secs, 1), "cost_usd": round(ledger.total_usd, 6),
    "models": {k: models[k] for k in ("intake", "records_investigator")}, "run_id": run_id, "case_uuid": case_uuid,
    "claims": [{"id": r.claim.id, "text": _p(r.claim.text), "attributed_to": _p(r.claim.attributed_to),
                "claim_type": r.claim.claim_type.value, "verdict": r.result.verdict.value, "explanation": _p(r.result.explanation),
                "conflicts": r.result.conflicts, "replans": r.replans, "refusals": [_p(x) for x in r.refusals],
                "trail": _trail(r.claim.id), "attributions": [{"agent": x.agent, "step": x.step, "category": x.category.value} for x in r.attributions],
                "findings": [{"field": f.field, "value": _p(f.value), "quote": _p(f.quote), "doc": _doc(docs[f.doc_id])}
                             for f in r.result.findings if f.doc_id in docs]} for r in runs],
    "timeline": [{"step": t["step"], "role": t["role"], "kind": t["kind"]} for t in trace.steps],
    "retrieval": source.audit() if a.youcom else None}, indent=1, default=str))
if case_uuid:
    print("  persisted:", persist_records(store, case_uuid=case_uuid, claim_runs=runs, trace=trace, idempotency_prefix=run_id))
if a.youcom:
    (out / "retrieval_audit.json").write_text(json.dumps(source.audit(), indent=2))
leaks = [] if a.reveal else pseudo.leaks(report)
print(f"{len(claims)} claims, {secs:.0f}s, cost ${ledger.total_usd:.4f}, models {models['intake'].split('/')[-1]} + {models['records_investigator'].split('/')[-1]}")
labels = json.loads(Path(a.labels).read_text()) if a.labels else {}
ok = 0
for i, r in enumerate(runs, 1):
    want = labels.get(str(i))
    mark = "" if want is None else (" OK" if want == r.result.verdict.value else f" WRONG (expected {want})")
    ok += want == r.result.verdict.value
    print(f"  {r.claim.id} [{r.claim.claim_type.value:18}] -> {r.result.verdict.value:22} replans={r.replans} refusals={len(r.refusals)}{mark}")
if labels:
    print(f"  matched labels: {ok}/{len(labels)}")
print(f"  pseudonym leaks in report: {leaks or 'none'}; skipped: {skipped or 'none'}")
if a.youcom and source.rejected_urls:
    print(f"  rejected non-source URL(s): {len(source.rejected_urls)} (see retrieval_audit.json)")
if a.youcom and (source.errors or not source.documents):
    print("  human source input required: You.com did not return extractable evidence for every lookup")
print("report:", out / "report.md")
