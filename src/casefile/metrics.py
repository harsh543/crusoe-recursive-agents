"""Metric definitions from SPEC section 6."""
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RunResult:
    claimed_complete: bool
    oracle_complete: bool
    cost_usd: float
    latency_s: float
    oracle_outcome: str
    outcome: str


def false_completion_rate(runs):
    claimed = [r for r in runs if r.claimed_complete]
    return None if not claimed else sum(not r.oracle_complete for r in claimed) / len(claimed)


def cost_per_correct_case(runs):
    correct = sum(r.oracle_complete for r in runs)
    return None if not correct else sum(r.cost_usd for r in runs) / correct


def unnecessary_escalation_rate(runs):
    benign = [r for r in runs if r.oracle_outcome == "closed_benign"]
    return None if not benign else sum(r.outcome == "escalated" for r in benign) / len(benign)


def percentile(values, p):
    s = sorted(values)
    return s[max(0, math.ceil(p / 100 * len(s)) - 1)]
