"""One-case audit timeline from Supabase: python scripts/audit_report.py <case_uuid>"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from casefile.persist import verify_audit_chain  # noqa: E402
from casefile.store import Store  # noqa: E402

cid = sys.argv[1]
s = Store()
case = s.select("cases", id=cid)[0]
ok, seq = verify_audit_chain(s, cid)
print(f"case {case['alert_id']}  status={case['status']}  disposition={case['disposition']}  replans={case['replans']}")
print(f"audit chain: {'intact' if ok else f'TAMPERED at seq {seq}'}")
for c in s.select("contracts", case_id=cid):
    print(f"contract v{c['version']} sha256={c['sha256'][:16]}  checks={c['body'].get('checks')}")
print("\nevidence receipts:")
for e in s.select("evidence", order="step.asc", case_id=cid):
    print(f"  step {e['step']:>3} {e['tool']:<20} {e['status']:<8} {(e['error'] or '')[:90]}")
print("\nverifier checks (failures):")
for c in s.select("check_results", case_id=cid):
    if not c["passed"]:
        print(f"  attempt {c['attempt']} {c['check_id']}: {(c['reason'] or '')[:110]}")
for a in s.select("attributions", case_id=cid):
    print(f"attribution: {a['agent']} step {a['step']} {a['category']}")
print("\nmodel calls:")
tot = 0.0
for r in s.select("audit_log", order="seq.asc", case_id=cid):
    d = r["data"]
    if r["type"] == "llm":
        tot += float(d.get("cost_usd") or 0)
        print(f"  #{r['seq']:>3} {d.get('role'):<12} {d.get('model','').split('/')[-1]:<34} in={d.get('input_tokens')} cached={d.get('cached_tokens')} out={d.get('output_tokens')} {d.get('latency_ms')}ms ${float(d.get('cost_usd') or 0):.6f}")
print(f"  total model cost ${tot:.6f}")
print("\nYou.com requests linked to this case:", len(s.select("grounding_requests", case_id=cid)))
for d in s.select("dispositions", case_id=cid):
    print(f"disposition: {d['disposition']}  key={d['idempotency_key'][:24]}…")
