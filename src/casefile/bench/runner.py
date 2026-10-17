"""Run configurations C1/C2/C3 over a case split with identical cases, tools, models and budgets."""
import json
import time
import traceback
from pathlib import Path

from .. import oracle
from ..cost import CostLedger
from ..llm import LLM
from ..metrics import (RunResult, cost_per_correct_case, false_completion_rate, percentile,
                       unnecessary_escalation_rate)
from ..models import Outcome
from ..orchestrator import run_casefile, run_critic, run_single
from ..trace import Trace
from .cases import RECOVERABLE, expected_for, make_faults, split_cases, write_labels

CONFIGS = {"C1": "single investigator", "C2": "investigator + LLM critic", "C3": "Casefile"}


def _truth_step(trace: Trace):
    for s in trace.steps:
        if s["kind"] == "tool" and s.get("tool") == "get_device_history" and s.get("status") != "ok":
            return s["step"]
    return None


def run_one(config, case, fault, crusoe, models, prices, out_dir: Path, labels, min_interval_s=0.0, thinking=None, sink=None):
    trace = Trace(out_dir / config / f"{case.id}-{fault}.jsonl")
    ledger = CostLedger(prices)
    llm = LLM(crusoe, ledger, trace, models, min_interval_s=min_interval_s, thinking=thinking)
    faults, error, rec = make_faults(fault), None, None
    case_uuid = sink.start(config, case, fault) if sink else None
    ds = {"data_source": sink.data_source} if sink else {}
    t0 = time.monotonic()
    try:
        if config == "C1":
            rec = run_single(case, faults, llm, ledger, trace, **ds)
        elif config == "C2":
            rec = run_critic(case, faults, llm, ledger, trace, **ds)
        else:
            rec = run_casefile(case, faults, llm, ledger, trace, **ds)
    except Exception as e:                                   # a crashed run is a failed run, not a skipped one
        error = f"{type(e).__name__}: {e}"
        trace.add("runner", "error", error=error, tb=traceback.format_exc()[-600:])
    persisted = sink.finish(config, case_uuid, rec, trace) if sink else None
    outcome = rec.outcome.value if rec else Outcome.INSUFFICIENT_EVIDENCE.value
    claimed = rec.claimed_complete if rec else False
    evidence = rec.evidence if rec else []
    truth = _truth_step(trace)
    first_att = rec.attributions[0] if rec and rec.attributions else None
    key = f"{case.id}:{fault}"
    return {
        "config": config, "case": case.id, "fault": fault, "expected": expected_for(case, fault),
        "outcome": outcome, "claimed_complete": claimed,
        "oracle_complete": oracle.judge(key, outcome, evidence, labels),
        "cost_usd": rec.cost_usd if rec else ledger.total_usd,
        "latency_s": rec.latency_s if rec else time.monotonic() - t0,
        "replans": rec.replans if rec else 0, "refusals": rec.refusals if rec else [],
        "attribution": ({"agent": first_att.agent, "step": first_att.step, "category": first_att.category.value}
                        if first_att else None),
        "attribution_truth": {"agent": "investigator", "step": truth} if truth else None,
        "attribution_correct": (first_att.agent == "investigator" and first_att.step == truth) if first_att and truth else None,
        "recoverable": fault in RECOVERABLE and fault != "none", "error": error,
        "case_uuid": case_uuid, "persisted": persisted,
    }


def summarize(rows):
    out = {}
    for cfg in sorted({r["config"] for r in rows}):
        rs = [r for r in rows if r["config"] == cfg]
        runs = [RunResult(r["claimed_complete"], r["oracle_complete"], r["cost_usd"], r["latency_s"],
                          r["expected"], r["outcome"]) for r in rs]
        rec = [r for r in rs if r["recoverable"]]
        att = [r["attribution_correct"] for r in rs if r["attribution_correct"] is not None]
        out[cfg] = {
            "name": CONFIGS[cfg], "runs": len(rs), "errors": sum(1 for r in rs if r["error"]),
            "false_completion_rate": false_completion_rate(runs),
            "claimed_completions": sum(r.claimed_complete for r in runs),
            "correct_disposition_rate": sum(r["oracle_complete"] for r in rs) / len(rs),
            "recovery_rate": (sum(r["oracle_complete"] for r in rec) / len(rec)) if rec else None,
            "unnecessary_escalation_rate": unnecessary_escalation_rate(runs),
            "attribution_accuracy": (sum(att) / len(att)) if att else None, "attributions_scored": len(att),
            "cost_per_correct_usd": cost_per_correct_case(runs), "total_cost_usd": sum(r["cost_usd"] for r in rs),
            "latency_p50_s": percentile([r["latency_s"] for r in rs], 50),
            "latency_p95_s": percentile([r["latency_s"] for r in rs], 95),
        }
    return out


def run_bench(split, configs, crusoe, models, prices, out_dir: Path, limit=None, min_interval_s=0.0,
              thinking=None, on_row=None, sink=None):
    labels = write_labels()
    cases = split_cases(split)[:limit] if limit else split_cases(split)
    rows = []
    for case, fault in cases:
        for cfg in configs:
            row = run_one(cfg, case, fault, crusoe, models, prices, out_dir, labels, min_interval_s, thinking, sink)
            rows.append(row)
            if on_row:
                on_row(row)
    result = {"split": split, "models": models, "summary": summarize(rows), "rows": rows}
    if sink:
        sink.close(result["summary"])
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(result, indent=1, default=str))
    return result
