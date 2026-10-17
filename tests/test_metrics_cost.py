"""FR-16, SPEC section 6: cost accounting and metric definitions."""
import pytest

from casefile.cost import CostLedger, Price, UnknownModelError
from casefile.metrics import (
    RunResult, cost_per_correct_case, false_completion_rate, percentile,
    unnecessary_escalation_rate,
)

# Illustrative prices per 1M tokens (input / cached / output); the real table is read from config.
PRICES = {"light": Price(input=0.05, cached=0.03, output=0.20)}


def run(claimed=True, correct=True, cost=0.1, latency=1.0, oracle="escalated", outcome="escalated"):
    return RunResult(claimed_complete=claimed, oracle_complete=correct, cost_usd=cost,
                     latency_s=latency, oracle_outcome=oracle, outcome=outcome)


def test_cost_splits_cached_from_uncached_input():
    ledger = CostLedger(PRICES)
    ledger.record("light", input_tokens=1_000_000, cached_tokens=400_000, output_tokens=500_000)
    # 600k uncached * 0.05 + 400k cached * 0.03 + 500k out * 0.20, per 1M
    assert ledger.total_usd == pytest.approx(0.6 * 0.05 + 0.4 * 0.03 + 0.5 * 0.20)


def test_cost_accumulates_across_calls():
    ledger = CostLedger(PRICES)
    ledger.record("light", input_tokens=1_000_000, cached_tokens=0, output_tokens=0)
    ledger.record("light", input_tokens=1_000_000, cached_tokens=0, output_tokens=0)
    assert ledger.total_usd == pytest.approx(0.10)


def test_unknown_model_price_raises():
    with pytest.raises(UnknownModelError):
        CostLedger(PRICES).record("mystery", input_tokens=1, cached_tokens=0, output_tokens=1)


def test_cached_tokens_cannot_exceed_input_tokens():
    with pytest.raises(ValueError):
        CostLedger(PRICES).record("light", input_tokens=10, cached_tokens=11, output_tokens=0)


def test_false_completion_rate_counts_only_claimed_completions():
    runs = [run(), run(), run(correct=False), run(), run(claimed=False, correct=False)]
    assert false_completion_rate(runs) == pytest.approx(0.25)


def test_false_completion_rate_is_none_when_nothing_claimed():
    assert false_completion_rate([run(claimed=False, correct=False)]) is None


def test_cost_per_correct_case_includes_failed_attempts():
    runs = [run(correct=True, cost=0.10), run(correct=False, cost=0.30)]
    assert cost_per_correct_case(runs) == pytest.approx(0.40)


def test_cost_per_correct_case_none_when_no_correct_runs():
    assert cost_per_correct_case([run(correct=False)]) is None


def test_unnecessary_escalation_rate_uses_oracle_benign_cases_only():
    runs = [
        run(oracle="closed_benign", outcome="escalated"),
        run(oracle="closed_benign", outcome="closed_benign"),
        run(oracle="escalated", outcome="escalated"),   # not in the denominator
    ]
    assert unnecessary_escalation_rate(runs) == pytest.approx(0.5)


def test_percentile_nearest_rank():
    data = list(range(1, 101))
    assert percentile(data, 50) == 50
    assert percentile(data, 95) == 95
