"""Per-call cost accounting from Crusoe usage fields (prices are per 1M tokens)."""
from dataclasses import dataclass


class UnknownModelError(KeyError):
    pass


@dataclass(frozen=True)
class Price:
    input: float
    cached: float
    output: float
    verified: bool = True


class CostLedger:
    def __init__(self, prices: dict[str, Price]):
        self.prices = prices
        self.total_usd = 0.0
        self.calls = 0

    def cost_of(self, model, input_tokens, cached_tokens, output_tokens) -> float:
        if model not in self.prices:
            raise UnknownModelError(model)
        if cached_tokens > input_tokens:
            raise ValueError("cached_tokens cannot exceed input_tokens")
        p = self.prices[model]
        return ((input_tokens - cached_tokens) * p.input + cached_tokens * p.cached
                + output_tokens * p.output) / 1_000_000

    def record(self, model, *, input_tokens, cached_tokens, output_tokens) -> float:
        c = self.cost_of(model, input_tokens, cached_tokens, output_tokens)
        self.total_usd += c
        self.calls += 1
        return c
