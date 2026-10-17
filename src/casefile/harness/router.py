"""One governed path to the model provider: allowlist, per-case budget, PII masking both ways, throttling, audit log."""
import json
import time

from ..cost import CostLedger
from ..errors import BudgetExceeded, ModelNotAllowed  # noqa: F401  (re-exported)
from .masking import PiiVault


def pace_seconds(remaining, limit) -> float:
    """Seconds to wait given the rate-limit headers. Waits only when little headroom is left."""
    if remaining is None or limit is None or remaining > 2:
        return 0.0
    return min(20.0, 60.0 / max(limit, 1) * (3 - remaining))


class ModelRouter:
    supports_roles = True

    def __init__(self, crusoe, *, allowlist, prices, max_usd, case_id, log_path=None, vault=None, sleep=time.sleep, role_models=None):
        self.role_models = role_models
        self.crusoe, self.allowlist, self.max_usd, self.case_id = crusoe, set(allowlist), max_usd, case_id
        self.ledger, self.vault, self.log_path, self._sleep = CostLedger(prices), vault or PiiVault(), log_path, sleep

    @property
    def spent_usd(self) -> float:
        return self.ledger.total_usd

    def list_models(self):
        return self.crusoe.list_models()

    def chat(self, model, messages, max_tokens=1024, role=None, **kw):
        if model not in self.allowlist:
            raise ModelNotAllowed(f"{model!r} is not on the allowlist")
        if self.role_models is not None and model not in self.role_models.get(role, ()):
            raise ModelNotAllowed(f"role {role!r} may not use {model!r}")        # default deny: unmapped roles get nothing
        if self.spent_usd >= self.max_usd:
            raise BudgetExceeded(f"case {self.case_id}: ${self.spent_usd:.4f} spent of ${self.max_usd:.4f}")
        before = self.vault.substitutions
        masked = [{**m, "content": self.vault.mask(m["content"]) if isinstance(m.get("content"), str) else m.get("content")}
                  for m in messages]
        t0 = time.monotonic()
        resp = self.crusoe.chat(model, masked, max_tokens=max_tokens, **kw)
        for ch in resp.choices:                                    # the model sees tokens; our tools get the real values back
            if getattr(ch.message, "content", None):
                ch.message.content = self.vault.unmask(ch.message.content)
        u = resp.usage
        cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        cost = self.ledger.record(model, input_tokens=u.prompt_tokens, cached_tokens=cached, output_tokens=u.completion_tokens)
        if self.log_path:
            with open(self.log_path, "a") as f:
                f.write(json.dumps({"case_id": self.case_id, "model": model, "input_tokens": u.prompt_tokens, "cached_tokens": cached,
                                    "output_tokens": u.completion_tokens, "latency_ms": round((time.monotonic() - t0) * 1000),
                                    "cost_usd": cost, "pii_tokens": self.vault.substitutions - before}) + "\n")
        h = getattr(self.crusoe, "last_headers", None) or {}
        try:
            wait = pace_seconds(int(h["x-ratelimit-remaining-requests"]), int(h["x-ratelimit-limit-requests"]))
        except (KeyError, ValueError):
            wait = 0.0
        if wait:
            self._sleep(wait)
        return resp
