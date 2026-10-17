# Supabase memory handoff prompt

Paste the prompt below into the LLM or coding agent that has access to your Supabase project. Give credentials only through that agent's secret manager or local `.env.local`; never paste a service-role key into chat, logs, source code, frontend code, or a commit.

## Copy/paste prompt

```text
Work only in ..

Goal: connect the existing Casefile memory layer to my Supabase project and ingest the already-fetched fraud-policy evidence. Do not refetch You.com data unless a required local evidence file is missing. Never print, log, return, or commit SUPABASE_SERVICE_ROLE_KEY, YDC_API_KEY, CRUSOE_API_KEY, access tokens, Authorization headers, or complete environment files.

Repository facts:
- Supabase migrations are supabase/migrations/0001_casefile.sql, 0002_grounding.sql, and 0003_fraud_policy_memory.sql.
- Raw You.com responses are in data/fraud_detection/research/youcom/.
- The reviewed RAG batch is data/fraud_detection/rag/verified_policy_chunks_batch_01.jsonl.
- The local, replayable memory fallback is data/store/*.jsonl.
- The backend persistence adapter is src/casefile/store.py.
- The ingestion command is .venv/bin/python scripts/ingest_fraud_policy_memory.py --require-supabase.
- Full local-memory replay is PYTHONPATH=src .venv/bin/python -m casefile.store --replay.

Complete these steps:
1. Inspect the three migrations and the persistence/ingestion code before changing anything.
2. Determine which migrations are already applied. Apply only missing migrations, in numeric order. Do not drop, truncate, or recreate existing tables.
3. Configure SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY through a backend-only secret mechanism. If a local file is required, use the gitignored .env.local. Never expose the service-role key to browser or anon clients.
4. Ingest all staged data/store/*.jsonl rows with the replay command. Then run the fraud-policy ingestion command once; it must be idempotent.
5. Verify foreign keys, deduplication, and counts. At minimum, confirm:
   - rag_policy_chunks contains 20 rows for chunk_id prefix fraud-policy-v1:;
   - those rows cover 11 distinct source_url values;
   - every batch-01 chunk has review_status='reviewed', access_scope='public', a content_hash, and a linked grounding_docs row;
   - the official domains acquisition.gov, justice.gov, ofac.treasury.gov, sec.gov, and fincen.gov are trusted for the imported source versions;
   - no secret values appear in grounding_requests.request, grounding_requests.response, grounding_docs.markdown, rag_policy_chunks, logs, or committed files.
6. Smoke-test public.search_policy_chunks with the query "duplicate invoice receiving report" and confirm it returns FAR-INVOICE-001, FAR-OVERPAY-001, or FAR-RECEIPT-001 near the top. Also test a sanctions query and a third-party due-diligence query.
7. Keep these write boundaries:
   - raw external call provenance and responses -> grounding_requests;
   - fetched, versioned source text -> grounding_docs;
   - reviewed reusable policy memory -> rag_policy_chunks;
   - case-specific tool receipts -> evidence;
   - attributed model claims with evidence IDs -> claims;
   - token/cost/latency and a compact structured model-output summary -> events.detail.
   Do not store system prompts, hidden reasoning, API keys, Authorization headers, or unrelated personal data.
8. Agents may retrieve reviewed/approved public chunks. Only the backend service role may write. The UI remains read-only under RLS. A retrieved rule or anomaly is review evidence, never proof of fraud or a legal conclusion.
9. Run the relevant tests. Report applied migrations, inserted/skipped row counts, search smoke-test results, and any remaining blocker. Redact all secrets.

Do not commit automatically. Stop after verification and give me the exact changed-file list and a safe commit message I can use.
```

## Runtime memory contract

For every answer that relies on external evidence, retrieve from `search_policy_chunks` first, cite `source_url` and `source_section`, and preserve the returned `chunk_id` in the case trace. If retrieval is empty, stale, or outside the stated jurisdiction or applicability, return `insufficient_evidence` or request human review rather than inventing a rule.

Raw model prose should not become trusted memory by itself. Store model outputs as attributed claims or event summaries; promote material into `rag_policy_chunks` only after source extraction, citation verification, metadata completion, and human or deterministic review.
