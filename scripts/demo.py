"""One case, narrated: python scripts/demo.py [A-104|A-105] [fault]   (default: A-104 wrong_identifier)"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from casefile.bench.cases import build_case, make_faults, write_labels  # noqa: E402
from casefile.config import prices_from_records, resolve_models  # noqa: E402
from casefile.cost import CostLedger  # noqa: E402
from casefile.llm import LLM  # noqa: E402
from casefile.orchestrator import run_casefile, run_critic  # noqa: E402
from casefile.trace import Trace  # noqa: E402
from crusoe_client import Crusoe  # noqa: E402

scenario = sys.argv[1] if len(sys.argv) > 1 else "A-104"
fault = sys.argv[2] if len(sys.argv) > 2 else "wrong_identifier"
crusoe = Crusoe()
records = crusoe.list_models()
models, prices = resolve_models([m["id"] for m in records]), prices_from_records(records)
labels = write_labels()
case = build_case(scenario, 0)
print(f"case {case.id}  fault={fault}  models={models}\n")
for name, fn in (("C2 investigator + LLM critic", run_critic), ("C3 Casefile", run_casefile)):
    trace, ledger = Trace(ROOT / "runs" / f"demo-{name[:2]}-{int(time.time())}.jsonl"), None
    ledger = CostLedger(prices)
    llm = LLM(crusoe, ledger, trace, models)
    rec = fn(case, make_faults(fault), llm, ledger, trace)
    print(f"== {name}: outcome={rec.outcome.value} claimed_complete={rec.claimed_complete} "
          f"cost=${rec.cost_usd:.4f} {rec.latency_s:.1f}s replans={rec.replans}")
    for s in trace.steps:
        if s["kind"] in ("tool", "verify", "refused", "attribution", "commit", "review", "contract"):
            print("  ", {k: v for k, v in s.items() if k not in ("role",) and v is not None})
    print()
