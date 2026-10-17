# Fraud Data and You.com Research Handoff

This work was started in the Nemotron workspace by mistake and moved into the Crusoe Recursive Agents Casefile project on 17 October 2026.

## Objective

Build grounded inputs for a fraud-detection RAG application:

- transaction datasets for billing, payment, invoice, and procurement analysis;
- government rules, regulator guidance, company policies, vendor requirements, price evidence, and technical quality specifications;
- provenance-preserving research outputs that can be reviewed before indexing;
- deterministic fraud-review signals followed by citation-backed agent explanations and human review.

## Completed work

- Curated source manifest covering transaction datasets, procurement data, government guidance, company policies, Google Drive references, and Devpost architecture examples.
- Prepared a 1,000-row attributed UCI Online Retail sample with research-only anomaly annotations.
- Created canonical transaction and RAG policy-chunk schemas.
- Created 28 paraphrased, source-cited policy and control rules.
- Produced Word and PDF research briefs under `output/`.
- Installed the global You.com skills `you-web`, `you-research`, `you-finance`, and `you-discover` from `youdotcom-oss/agent-skills`.
- Added `scripts/youcom_enrich.py` for You.com Web Search, Contents, Research, and Finance Research REST APIs.
- Added reusable You.com prompts and an MCP endpoint template under `data/fraud_detection/research/`.

## Secret setup

The real You.com key belongs in the gitignored `.env.youcom` file:

```dotenv
YDC_API_KEY=
```

Never paste the key into chat, source control, JSON output, logs, or the MCP example. REST calls use `X-API-Key`; remote MCP connections use `Authorization: Bearer` or OAuth.

## First evidence batch completed

On 17 October 2026, the first evidence batch was completed:

1. Three current official-domain searches covered vendor-payment controls, sanctions screening, and federal procurement/price controls.
2. Deep U.S. policy research returned 26 cited official sources with binding-versus-guidance and applicability distinctions.
3. Fourteen selected official URLs were extracted in two Contents requests, never exceeding 10 URLs per request.
4. Eleven accepted sources passed deterministic phrase checks and produced 20 reviewed records in `data/fraud_detection/rag/verified_policy_chunks_batch_01.jsonl`.
5. The raw responses and reviewed chunks were staged through the local `data/store/*.jsonl` fallback for later Supabase replay.
6. No company Finance Research was run because no company/ticker and dated counterparty question were supplied.

## Next action

Apply `supabase/migrations/0003_fraud_policy_memory.sql`, configure the backend-only Supabase credentials, and replay the staged memory. The copy/paste connector prompt is in `docs/SUPABASE_MEMORY_HANDOFF_PROMPT.md`. After that, the next enrichment slice should name the companies/vendors, products/services, jurisdictions, and time periods so company policy, finance, price, and quality evidence stays scoped and comparable.

See `data/fraud_detection/YOUCOM_ENRICHMENT.md` for the evidence files, rebuild/import commands, and RAG acceptance gate.
