"""Records benchmark: C1 single, C2 critic, C3 Casefile over the same cases, documents, models and budgets."""
import json
import time
from pathlib import Path

from ..cost import CostLedger
from ..llm import LLM
from ..metrics import percentile
from ..records import baselines
from ..records.gate import RecordsGate
from ..records.models import CLOSURE_VERDICTS, ClaimResult, Verdict
from ..records.neutrality import lint
from ..records.orchestrator import verify_one
from ..records.sources import FixtureSource
from ..trace import Trace
from . import records_oracle
from .records_cases import split_cases

CONFIGS = {"C1": "single investigator", "C2": "investigator + LLM critic", "C3": "Casefile"}


def run_case_config(config, case, crusoe, models, prices, out_dir: Path, min_interval_s=0.0):
    trace = Trace(out_dir / config / f"{case.id}.jsonl")
    ledger = CostLedger(prices)
    llm = LLM(crusoe, ledger, trace, models, min_interval_s=min_interval_s)
    source, docs, gate = FixtureSource(case.docs), {d.id: d for d in case.docs}, RecordsGate()
    rows = []
    for claim in case.claims:
        c0, t0, error, replans, refusals = ledger.total_usd, time.monotonic(), None, 0, 0
        try:
            if config == "C3":
                run = verify_one(claim, source, llm, trace, gate)
                res, replans, refusals = run.result, run.replans, len(run.refusals)
            elif config == "C2":
                res, _ = baselines.run_critic_claim(claim, source, llm, trace)
            else:
                res, _ = baselines.run_single_claim(claim, source, llm, trace)
        except Exception as e:                                   # a crashed claim is a failed claim
            res, error = ClaimResult(claim_id=claim.id, verdict=Verdict.INSUFFICIENT_EVIDENCE), f"{type(e).__name__}: {e}"
        exp = case.expected[claim.id]
        rows.append({
            "config": config, "case": case.id, "fault": case.fault, "claim": claim.id, "claim_type": claim.claim_type.value,
            "expected": exp, "verdict": res.verdict.value, "claimed_closure": res.verdict in CLOSURE_VERDICTS,
            "correct": records_oracle.judge(exp, res, docs, claim.id in case.needs_conflict),
            "quotes_ok": records_oracle.quotes_ok(res, docs), "neutrality_violations": len(lint(res.explanation)),
            "researched_out_of_scope": exp == "out_of_scope" and (bool(res.findings) or res.verdict != Verdict.OUT_OF_SCOPE),
            "cost_usd": ledger.total_usd - c0, "latency_s": time.monotonic() - t0, "replans": replans,
            "refusals": refusals, "error": error})
    llm_steps = [s for s in trace.steps if s["kind"] == "llm"]
    tokens = (sum(s["input_tokens"] for s in llm_steps), sum(s["cached_tokens"] for s in llm_steps))
    return rows, tokens


def summarize(rows, tokens_by_config):
    out = {}
    for cfg in sorted({r["config"] for r in rows}):
        rs = [r for r in rows if r["config"] == cfg]
        closed = [r for r in rs if r["claimed_closure"]]
        oos = [r for r in rs if r["expected"] == "out_of_scope"]
        withq = [r for r in rs if r["quotes_ok"] is not None]
        fixed = [r for r in rs if r["replans"] > 0]
        correct = sum(r["correct"] for r in rs)
        inp, cached = tokens_by_config.get(cfg, (0, 0))
        out[cfg] = {
            "name": CONFIGS[cfg], "claims": len(rs), "errors": sum(1 for r in rs if r["error"]), "claimed_verdicts": len(closed),
            "false_verdict_rate": (sum(not r["correct"] for r in closed) / len(closed)) if closed else None,
            "correct_verdict_rate": correct / len(rs),
            "out_of_scope_accuracy": (sum(r["verdict"] == "out_of_scope" for r in oos) / len(oos)) if oos else None,
            "researched_out_of_scope": sum(r["researched_out_of_scope"] for r in rs),
            "quote_verbatim_rate": (sum(bool(r["quotes_ok"]) for r in withq) / len(withq)) if withq else None,
            "neutrality_violations": sum(r["neutrality_violations"] for r in rs),
            "recovery_rate": (sum(r["correct"] for r in fixed) / len(fixed)) if fixed else None, "repaired_claims": len(fixed),
            "gate_refusals": sum(r["refusals"] for r in rs),
            "date_gap_accuracy_by_fault": {f: round(sum(r["correct"] for r in rs if r["claim"] == "c1" and r["fault"] == f), 2)
                                           for f in sorted({r["fault"] for r in rs})},
            "cache_hit_rate": (cached / inp) if inp else None,
            "cost_per_correct_usd": (sum(r["cost_usd"] for r in rs) / correct) if correct else None,
            "total_cost_usd": sum(r["cost_usd"] for r in rs),
            "latency_p50_s": percentile([r["latency_s"] for r in rs], 50), "latency_p95_s": percentile([r["latency_s"] for r in rs], 95)}
    return out


def run_bench(split, configs, crusoe, models, prices, out_dir: Path, limit=None, min_interval_s=0.0, on_case=None):
    cases = split_cases(split)[:limit] if limit else split_cases(split)
    rows, tokens = [], {}
    for case in cases:
        for cfg in configs:
            r, (i, c) = run_case_config(cfg, case, crusoe, models, prices, out_dir, min_interval_s)
            rows += r
            ti, tc = tokens.get(cfg, (0, 0))
            tokens[cfg] = (ti + i, tc + c)
            if on_case:
                on_case(cfg, case, r)
    result = {"split": split, "models": models, "summary": summarize(rows, tokens), "rows": rows}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(result, indent=1, default=str))
    return result
