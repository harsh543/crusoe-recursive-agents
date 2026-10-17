"""Counterfactual invariance probe: verdicts must not change when who-said-it or the company names change.
python scripts/bias_probe.py  -> runs the example 3 ways (as-is, speakers swapped, companies renamed) and compares to labels."""
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from casefile.config import prices_from_records, resolve_models  # noqa: E402
from casefile.cost import CostLedger  # noqa: E402
from casefile.llm import LLM  # noqa: E402
from casefile.records.models import Document  # noqa: E402
from casefile.records.orchestrator import run_case_file  # noqa: E402
from casefile.records.sources import FixtureSource  # noqa: E402
from casefile.trace import Trace  # noqa: E402
from crusoe_client import Crusoe  # noqa: E402

case_text = (ROOT / "data/casefiles/example_procurement.md").read_text()
raw_docs = json.loads((ROOT / "data/fixtures/example_procurement.json").read_text())
labels = json.loads((ROOT / "labels_records/example_procurement.json").read_text())
RENAME = {"Northwind Signal Media LLC": "Evergreen Harbor Media LLC", "Northwind": "Evergreen",
          "Lakeshore Ads Inc.": "Pinecrest Creative Inc.", "Harbor Strategy Group LLC": "Ridgeway Consulting Group LLC"}


def swap_speakers(t):
    return t.replace("Senator Hale", "@@A").replace("Secretary Rowan", "Senator Hale").replace("@@A", "Secretary Rowan")


def rename(t):
    for k, v in sorted(RENAME.items(), key=lambda kv: -len(kv[0])):
        t = t.replace(k, v)
    return t


def docs_from(transform):
    out = []
    for d in raw_docs:
        text = transform(d["text"])
        out.append(Document(**{**d, "text": text, "title": transform(d["title"]), "sha256": hashlib.sha256(text.encode()).hexdigest()}))
    return FixtureSource(out)


crusoe = Crusoe()
recs = crusoe.list_models()
models, prices = resolve_models([m["id"] for m in recs]), prices_from_records(recs)
REPEATS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
variants = {"as-is": (case_text, docs_from(lambda t: t)), "companies renamed": (rename(case_text), docs_from(rename))}
stamp = time.strftime("%Y%m%d-%H%M%S")
result = {}
for name, (text, source) in variants.items():
    for rep in range(REPEATS):
        ledger, trace = CostLedger(prices), Trace(ROOT / "runs" / f"bias-{stamp}" / f"{name.replace(' ', '_')}-{rep}.jsonl")
        llm = LLM(crusoe, ledger, trace, models, min_interval_s=2.0)
        claims, _, _, runs, _, secs = run_case_file(text, source, llm, trace)
        got = [r.result.verdict.value for r in runs]
        result.setdefault(name, []).append(got)
        match = sum(1 for i, g in enumerate(got, 1) if labels.get(str(i)) == g)
        print(f"{name:18} run {rep}: {match}/{len(labels)} match labels; {got}; ${ledger.total_usd:.4f}; {secs:.0f}s", flush=True)
print("per-claim accuracy over repeats (claim: as-is vs renamed):")
for i in range(len(labels)):
    acc = {n: sum(r[i] == labels[str(i + 1)] for r in runs_) for n, runs_ in result.items()}
    print(f"  c{i + 1} expected {labels[str(i + 1)]:22} " + "  ".join(f"{n}: {a}/{REPEATS}" for n, a in acc.items()), flush=True)
(ROOT / "runs" / f"bias-{stamp}" / "summary.json").write_text(json.dumps(result, indent=1))
