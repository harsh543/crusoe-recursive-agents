"""Run the benchmark: python scripts/run_bench.py --split dev --configs C1,C2,C3 [--limit N] [--rpm 30]"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from casefile.bench.report import render  # noqa: E402
from casefile.bench.runner import run_bench  # noqa: E402
from casefile.config import prices_from_records, resolve_models  # noqa: E402
from crusoe_client import Crusoe  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--split", default="dev", choices=["dev", "heldout"])
ap.add_argument("--configs", default="C1,C2,C3")
ap.add_argument("--limit", type=int)
ap.add_argument("--rpm", type=int, default=30, help="per-model requests/minute to pace to (30 without a payment method)")
ap.add_argument("--supabase", action="store_true", help="read evidence from Supabase and persist every run, receipt and disposition")
ap.add_argument("--small", help="override the small model ID (e.g. the Nano arm)")
a = ap.parse_args()

crusoe = Crusoe()
records = crusoe.list_models()
kw = {"small": a.small} if a.small else {}
models = resolve_models([m["id"] for m in records], **kw)
prices = prices_from_records(records)
sink = None
if a.supabase:
    from casefile.bench.cases import split_cases  # noqa: E402
    from casefile.db_source import seed_cases  # noqa: E402
    from casefile.persist import BenchSink  # noqa: E402
    from casefile.store import Store  # noqa: E402
    store = Store()
    print("seeded rows:", seed_cases(store, [c for c, _ in split_cases(a.split)]))
    sink = BenchSink(store, a.split, models)
out = ROOT / "runs" / f"{a.split}-{time.strftime('%Y%m%d-%H%M%S')}"
print("models:", models)
res = run_bench(a.split, a.configs.split(","), crusoe, models, prices, out, limit=a.limit,
                min_interval_s=60.0 / a.rpm, sink=sink,
                on_row=lambda r: print(f"{r['config']} {r['case']:10} {r['fault']:18} -> {r['outcome']:22} "
                                       f"{'OK ' if r['oracle_complete'] else 'WRONG'} ${r['cost_usd']:.4f} {r['error'] or ''}"))
print("report:", render(out / "results.json"))
for k, v in res["summary"].items():
    print(k, {m: (round(x, 3) if isinstance(x, float) else x) for m, x in v.items() if m != "name"})
