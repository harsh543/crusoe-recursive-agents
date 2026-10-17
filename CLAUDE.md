# Crusoe x Cerebral Valley: Recursive Agents Hackathon

Sat Oct 17, 2026, San Francisco. Teams of up to 4. We build an agent team on **Crusoe Managed Inference**; it must run on Crusoe, not another provider. Theme: agents you can walk away from (plan, delegate to sub-agents, check own progress, recover, keep going).

Tracks (pick one, see docs/tracks.md): Done Means Done / Shared Brain / Version N+1.

## Rules for working in this repo
- Crusoe is the only model provider. No OpenAI/Anthropic/other API calls in the agent code.
- Do not rely on memory for Crusoe model names, prices or API behaviour. Run `python scripts/check_models.py` and trust `GET /v1/models`.
- Model IDs are case-sensitive and exact. Copy the `id` from `/v1/models`, never from a web page.
- Event rules, judging criteria, prize split, submission process and credits are NOT published in our sources. Do not guess; ask the organizers (event page: https://cerebralvalley.ai/e/crusoe-recursive-agents-hackathon).

## Endpoint and auth
- Base URL: `https://api.inference.crusoecloud.com/v1` (OpenAI-compatible; chat is `/v1/chat/completions`). Old hosts `api.crusoe.ai` and `managed-inference-api-proxy.crusoecloud.com` are outdated.
- Key: `CRUSOE_API_KEY`. Keys can contain `$`; in a shell use single quotes: `export CRUSOE_API_KEY='...'`. Double quotes corrupt the key and give 401/403.
- Put the key in `.env.local` (gitignored). Never print it or commit it.

## Facts that explain most failures
1. **429**: check the base URL first, then limits. No payment method = 30 RPM / 500K TPM per model; with one = 600 RPM / 2M TPM. Limits are per model, so spreading agent roles across models spreads load. 503 = shared endpoint busy. Retry both with jittered exponential backoff (`src/crusoe_client.py` does this).
2. **Reasoning models eat `max_tokens`**. If `content` is empty and `finish_reason == "length"`, raise `max_tokens` to 1024+ and read `reasoning_content` / `reasoning`.
3. **Wrong model ID** gives 404 `model_not_found`.
4. **Thinking toggle** (DeepSeek V4 Pro): `extra_body={"chat_template_kwargs": {"thinking": True}}`. The DeepSeek-native `"thinking": {...}` parameter returns 403. Check `supported_parameters` per model first.
5. **Tool calling**: append the assistant message containing `tool_calls` before the `role: "tool"` results, or you get a 400.
6. **Images**: only multimodal models (check `architecture.modality`); text-only models silently ignore them.
7. **Prefix caching**: keep system prompt, tool schemas and history byte-identical and append-only; changing content goes last. Measure with `usage.prompt_tokens_details.cached_tokens`.

## Verified deviations from the skill file (Oct 17 2026)
- 200 responses from `api.inference.crusoecloud.com` carry no `x-ratelimit-*` headers (only Cloudflare headers). The router keeps header-based
  pacing for when they appear, but real throttling uses the configured RPM (`--rpm`, 30 without a payment method). Tier cannot be read from headers.

## Model roles (verified against this project's `GET /v1/models`, Oct 17 2026; confirm again with scripts/check_models.py)
| Role | ID (case-sensitive) | Price in / cached / out per 1M | Notes |
|---|---|---|---|
| investigator, attributor, critic | `nvidia/Nemotron-3.5-Lightning-30B-A3B` | $0.05 / $0.03 / $0.20 | small, high volume |
| intake, planner, attributor escalation | `nvidia/NVIDIA-Nemotron-3.5-Super-VL` | $0.10 / $0.08 / $0.40 | multimodal, 262k ctx |
| comparison arms | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` ($0.05/$0.03/$0.20), `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B` ($0.30/$0.15/$2.40) | | |
All Nemotron models list `tools`, `response_format`, `structured_outputs`, `chat_template_kwargs`. Send `chat_template_kwargs: {"enable_thinking": false}` for JSON loops (measured: Lightning 310 -> 19 output tokens, 2.9 s -> 0.4 s). Prices are read from `/v1/models` in code (`config.prices_from_records`), not hardcoded.
Other models present: DeepSeek V4 Flash/Pro/V4.1 Flash, gpt-oss-120b, GLM-5.3 and Flash, Qwen3.8-27B, Gemma 4 31B, Nemotron-3-Nano-Omni-Reasoning. Not present: Nemotron 3 Ultra, VoiceChat.

Deprecated, do not use: Kimi K2.6, GLM-5.1/5.2, DeepSeek V3, Qwen3 235B, Llama 3.3 70B.

## Project modes
- Transaction alerts (`src/casefile/`): frozen contract, code verifier, Gate, loop guard, attributor. Benchmark: `scripts/run_bench.py`.
- Uploaded case files (`src/casefile/records/`): atomic attributed claims verified against cached documents; pseudonymized output; never concludes wrongdoing. Run: `scripts/run_casefile.py`; benchmark: `scripts/run_records_bench.py`. Retrieval is behind `records/sources.py`: fixtures for reproducible benchmarks, or You.com Search -> exact-URL Contents for live cases. Search-wrapper and invented URLs are rejected.

## Support
Crusoe Discord https://discord.gg/tRKs5bMyry, support https://support.crusoecloud.com/hc/en-us/requests/new, status https://status.crusoecloud.com/, docs https://docs.crusoecloud.com/.
