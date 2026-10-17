"""python scripts/run_records_bench.py --split dev [--configs C1,C2,C3] [--limit N] [--rpm 30] [--small ID] [--big ID]"""
import argparse
import html
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from casefile.bench.records_runner import run_bench  # noqa: E402
from casefile.config import prices_from_records, resolve_models  # noqa: E402
from crusoe_client import Crusoe  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--split", default="dev", choices=["dev", "heldout"])
ap.add_argument("--configs", default="C1,C2,C3")
ap.add_argument("--limit", type=int)
ap.add_argument("--rpm", type=int, default=30)
ap.add_argument("--small"), ap.add_argument("--big")
a = ap.parse_args()

crusoe = Crusoe()
recs = crusoe.list_models()
kw = {k: v for k, v in (("small", a.small), ("big", a.big)) if v}
models, prices = resolve_models([m["id"] for m in recs], **kw), prices_from_records(recs)
out = ROOT / "runs" / f"records-{a.split}-{time.strftime('%Y%m%d-%H%M%S')}"
print("models:", {k: v.split("/")[-1] for k, v in models.items()}, flush=True)
res = run_bench(a.split, a.configs.split(","), crusoe, models, prices, out, limit=a.limit, min_interval_s=60.0 / a.rpm,
                on_case=lambda cfg, case, rows: print(f"{cfg} {case.id:26} " + " ".join(
                    f"{r['claim']}:{'ok' if r['correct'] else 'X'}" for r in rows), flush=True))
cols = ["false_verdict_rate", "correct_verdict_rate", "out_of_scope_accuracy", "researched_out_of_scope", "quote_verbatim_rate",
        "neutrality_violations", "recovery_rate", "cache_hit_rate", "cost_per_correct_usd", "latency_p50_s", "latency_p95_s"]
fmt = lambda v: "n/a" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))
body = "".join(f"<tr><td><b>{k}</b> {html.escape(v['name'])}</td>" + "".join(f"<td>{fmt(v[c])}</td>" for c in cols) + "</tr>" for k, v in res["summary"].items())
(out / "report.html").write_text(f"<!doctype html><meta charset=utf-8><title>Casefile records benchmark</title><style>body{{font:14px system-ui;margin:24px}}td,th{{border:1px solid #ccc;padding:6px 10px}}table{{border-collapse:collapse}}</style><h1>Records benchmark ({a.split})</h1><p>Synthetic, fictional case files. All values computed from results.json.</p><table><tr><th>Config</th>{''.join(f'<th>{c}</th>' for c in cols)}</tr>{body}</table>")
for k, v in res["summary"].items():
    print(k, {m: (round(x, 3) if isinstance(x, float) else x) for m, x in v.items() if m != "name"})
print("report:", out / "report.html")
