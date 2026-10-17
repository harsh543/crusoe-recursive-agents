# Fraud detection data input pack

Prepared on 2026-10-17 for the Crusoe Recursive Agents Casefile project.

This pack separates three kinds of evidence that should not be mixed:

1. **Transaction data** for feature engineering, anomaly detection, and supervised/weakly supervised scoring.
2. **Grounded rules and policies** for retrieval, explanations, and case-review support.
3. **Internal design references** from connected Google Drive. These are useful product ideas, but they are not authoritative policy and are not redistributed here.

## Included files

- `research/source_manifest.csv` — curated datasets, policy sources, GitHub projects, Drive references, and Devpost examples.
- `rules/policy_rules.jsonl` — paraphrased, source-cited rules ready to chunk or index for RAG.
- `schemas/transaction_schema.json` — a canonical transaction/event schema for billing, payment, invoice, and procurement data.
- `schemas/rag_policy_chunk_schema.json` — the expected metadata contract for policy chunks.
- `transactions/uci_online_retail_sample.csv` — a deterministic 1,000-row research sample derived from UCI Online Retail.
- `transactions/ATTRIBUTION.md` — source, license, transformation, and intended-use notes for the sample.
- `research/youcom_query_templates.json` — reusable policy, company, pricing, and quality research prompts.
- `research/youcom_mcp_servers.example.json` — non-secret MCP endpoint template for You.com tools.
- `YOUCOM_ENRICHMENT.md` — setup and evidence-acceptance workflow for You.com enrichment.
- `../../scripts/prepare_fraud_data_inputs.py` — reproducibly downloads the UCI archive and rebuilds the sample.
- `../../scripts/youcom_enrich.py` — provenance-preserving You.com REST client for search, contents, research, and finance.

## Recommended architecture for this repository

Do not embed millions of raw transactions in the retrieval layer. Keep transactions in the structured Casefile data pipeline and compute features and rule hits there. Index only compact, human-readable evidence for retrieval:

- policies and control requirements;
- vendor contracts, statements of work, pricing schedules, and quality specifications;
- procurement red-flag definitions;
- prior reviewed fraud cases and investigator outcomes;
- a compact case summary containing the current transaction's facts and triggered rule IDs.

At answer time, retrieve policy chunks by rule ID, domain, jurisdiction, effective date, and vendor/payment context. The LLM should explain why a transaction was flagged and cite the retrieved source. A rule hit is a review signal, not a legal or fraud determination.

## Suggested first implementation slice

1. Load and validate transactions against `schemas/transaction_schema.json`.
2. Add deterministic features such as duplicate invoice, payment-over-contract, unit-price deviation, velocity, refund ratio, beneficiary change, split purchase, and specification mismatch.
3. Write triggered rules and feature values to a compact case JSON.
4. Index `rules/policy_rules.jsonl` plus approved company policy documents in a separate policy-evidence collection.
5. Retrieve by triggered rule IDs and metadata filters, then produce an evidence-backed review summary.
6. Require human review for sanctions, supplier exclusion, payment holds, account suspension, or adverse vendor decisions.

## Data cautions

- The UCI sample is real retail activity but has **no fraud label**. Its candidate signals are only anomaly examples.
- The Fraud Detection Handbook raw GitHub data is useful and labeled, but the raw-data repository does not clearly state a separate dataset license. Resolve licensing before redistribution.
- Kaggle-hosted datasets can change terms; verify the current dataset license before copying them into this repository.
- Company policies may be proprietary or jurisdiction-specific. Store only documents the organization is entitled to use, preserve effective dates, and enforce access controls.
- The two Drive documents listed in the manifest are design prototypes, not compliance authorities.
