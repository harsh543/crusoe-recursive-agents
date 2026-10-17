"""Thin client for Crusoe Managed Inference (OpenAI-compatible).

Adds what agent loops need: jittered backoff on 429/503, usage and prefix-cache accounting,
and a helper for the DeepSeek thinking toggle.
"""
import os
import random
import time
from pathlib import Path

import httpx
from openai import InternalServerError, OpenAI, RateLimitError

BASE_URL = "https://api.inference.crusoecloud.com/v1"

# Exact, case-sensitive IDs from the hackathon skill file. Confirm with scripts/check_models.py.
MODELS = {
    "cheap": "deepseek-ai/Deepseek-V4-Flash",
    "subagent": "nvidia/Nemotron-3.5-Lightning-30B-A3B",
    "tools": "openai/gpt-oss-120b",
    "planner": "nvidia/NVIDIA-Nemotron-3.5-Super-VL",
    "vision": "google/gemma-4-31b-it",
}


def load_env() -> None:
    """Read KEY=VALUE lines from .env.local and .env.youcom without shell expansion (keys may contain '$')."""
    root = Path(__file__).resolve().parent.parent
    for env in (root / ".env.local", root / ".env.youcom"):
        if not env.is_file():
            continue
        for line in env.read_text().splitlines():
            key, _, val = line.partition("=")
            if key.strip() and val.strip() and not line.lstrip().startswith("#"):
                os.environ.setdefault(key.strip(), val.strip().strip("'\""))


class Crusoe:
    def __init__(self) -> None:
        load_env()
        key = os.environ.get("CRUSOE_API_KEY")
        if not key:
            raise SystemExit("CRUSOE_API_KEY is not set (put it in .env.local, see .env.example)")
        self._key = key
        self.client = OpenAI(base_url=BASE_URL, api_key=key)
        self.prompt_tokens = 0
        self.cached_tokens = 0
        self.completion_tokens = 0
        self.last_headers: dict = {}

    def chat(self, model: str, messages: list[dict], max_tokens: int = 1024,
             thinking: bool | None = None, max_tries: int = 6, **kwargs):
        """Chat completion with backoff. thinking=True/False sets chat_template_kwargs.thinking."""
        if thinking is not None:
            kwargs.setdefault("extra_body", {}).setdefault("chat_template_kwargs", {})["thinking"] = thinking
        for attempt in range(max_tries):
            try:
                raw = self.client.chat.completions.with_raw_response.create(
                    model=model, messages=messages, max_tokens=max_tokens, **kwargs
                )
                self.last_headers = {k.lower(): v for k, v in raw.headers.items()}   # x-ratelimit-* for throttling
                resp = raw.parse()
                self._record(resp.usage)
                return resp
            except (RateLimitError, InternalServerError):  # 429 / 503
                if attempt == max_tries - 1:
                    raise
                time.sleep(min(60.0, 2.0 ** attempt) + random.uniform(0, 0.5))

    def _record(self, usage) -> None:
        if not usage:
            return
        self.prompt_tokens += usage.prompt_tokens or 0
        self.completion_tokens += usage.completion_tokens or 0
        details = getattr(usage, "prompt_tokens_details", None)
        self.cached_tokens += (getattr(details, "cached_tokens", 0) or 0) if details else 0

    @property
    def cache_hit_rate(self) -> float:
        return self.cached_tokens / self.prompt_tokens if self.prompt_tokens else 0.0

    def list_models(self) -> list[dict]:
        """Full /v1/models records (supported_parameters, features, context_length, pricing)."""
        r = httpx.get(f"{BASE_URL}/models", headers={"Authorization": f"Bearer {self._key}"}, timeout=30)
        r.raise_for_status()
        return r.json()["data"]


def reply_text(resp) -> tuple[str, str | None]:
    """(content, reasoning). Reasoning may arrive as reasoning_content or reasoning."""
    msg = resp.choices[0].message.model_dump()
    return msg.get("content") or "", msg.get("reasoning_content") or msg.get("reasoning")
