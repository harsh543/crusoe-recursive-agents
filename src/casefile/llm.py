"""Every model call goes through here: Crusoe, JSON parsing, token/cost/latency logging, RPM pacing."""
import json
import time

import openai

from crusoe_client import reply_text

from .cost import CostLedger


class ModelOutputError(Exception):
    pass


def extract_json(text: str):
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == "{":                      # agents speak in JSON objects; a stray [...] must not be mistaken for one
            try:
                return dec.raw_decode(text[i:])[0]
            except json.JSONDecodeError:
                continue
    raise ModelOutputError(f"no JSON in model output: {text[:200]!r}")


class LLM:
    def __init__(self, crusoe, ledger: CostLedger, trace, models: dict[str, str], min_interval_s: float = 0.0,
                 thinking: dict[str, bool] | None = None):
        self.crusoe, self.ledger, self.trace, self.models = crusoe, ledger, trace, models
        self.min_interval_s = min_interval_s
        self.thinking = thinking or {}
        self._schema_off: set[str] = set()      # roles whose schema the API rejected; they fall back to plain JSON         # role -> enable_thinking; default off (measured: 310 -> 19 tokens)
        self._last: dict[str, float] = {}

    def _pace(self, model):
        wait = self._last.get(model, 0) + self.min_interval_s - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last[model] = time.monotonic()

    def call_json(self, role: str, messages: list[dict], max_tokens: int = 2048, model: str | None = None, schema: dict | None = None):
        model = model or self.models[role]
        last_err = None
        for attempt in range(2):            # second attempt doubles the budget (reasoning headroom)
            self._pace(model)
            t0 = time.monotonic()
            extra = {"chat_template_kwargs": {"enable_thinking": self.thinking.get(role, False)}}
            kw = {"role": role} if getattr(self.crusoe, "supports_roles", False) else {}
            schema_kw = {}
            if schema is not None and role not in self._schema_off:
                schema_kw["response_format"] = {"type": "json_schema", "json_schema": {"name": role, "schema": schema, "strict": True}}
            try:
                resp = self.crusoe.chat(model, messages, max_tokens=max_tokens * (2 ** attempt), extra_body=extra, **kw, **schema_kw)
            except openai.APIStatusError as e:
                if not schema_kw or e.status_code not in (400, 403, 422):
                    raise
                self._schema_off.add(role)                 # schema rejected: log once, continue without it
                self.trace.add(role, "schema_fallback", status=e.status_code, error=str(e)[:160])
                resp = self.crusoe.chat(model, messages, max_tokens=max_tokens * (2 ** attempt), extra_body=extra, **kw)
            text, _ = reply_text(resp)
            u = resp.usage
            cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
            cost = self.ledger.record(model, input_tokens=u.prompt_tokens, cached_tokens=cached,
                                      output_tokens=u.completion_tokens)
            finish = resp.choices[0].finish_reason
            self.trace.add(role, "llm", model=model, input_tokens=u.prompt_tokens, cached_tokens=cached,
                           output_tokens=u.completion_tokens, latency_ms=round((time.monotonic() - t0) * 1000),
                           cost_usd=cost, finish_reason=finish, attempt=attempt)
            try:
                return extract_json(text)
            except ModelOutputError as e:
                last_err = e
        raise last_err
