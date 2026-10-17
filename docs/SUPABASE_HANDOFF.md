# Supabase handoff: Casefile memory layer

Project: your Supabase project (us-west-2); set `SUPABASE_URL` in `.env.local`.
Status as of Oct 17, 2026, 14:55 PDT: **live**. Migrations 0001–0005 are applied. Local memory is replayed, the importer is verified idempotent, and the verification checks below all pass. 306 tests pass.

Key handling: run `zsh scripts/set_supabase_key.sh`, which prompts with hidden input and writes `.env.local`. Paste the key once; a doubled paste produces a 401 "Invalid API key". `0005` makes `search_policy_chunks` match on any term, with chunks that contain all terms ranked first.

## 1. Done (first pass, 14:05)

| Item | State |
|---|---|
| Migrations | Applied in order: `0001_casefile`, `0002_grounding`, `0003_fraud_policy_memory`, `0004_search_path`. The DB was empty, so nothing was dropped or recreated |
| `SUPABASE_URL` | Written to `.env.local` (gitignored) |
| `SUPABASE_SERVICE_ROLE_KEY` | **Not set.** There's an empty placeholder line in `.env.local` |
| Local staged memory | `data/store/`: 15 requests, 96 docs, 20 policy chunks. Not uploaded yet |
| Secret scan of `data/store/*.jsonl` | No key values found. The "Authorization" matches are regulation text (FAR 32.905, NDAA), not headers |
| Tests | `pytest`: 161 passed, 5 live tests deselected |
| Security advisor | Two `search_path` warnings, fixed by 0004. Four INFO findings for "RLS enabled, no policy" on `claims`, `dispositions`, `evidence` and `grounding_requests`. That's intended: service role only |

## 2. Finish it (about 2 minutes)

1. Copy the service-role (secret) key: Supabase dashboard → Project Settings → API Keys.
2. Paste it after `SUPABASE_SERVICE_ROLE_KEY=` in `.env.local`. Don't use a shell `export`, don't paste it into chat, and don't commit it.
3. Run:

```bash
PYTHONPATH=src .venv/bin/python -m casefile.store --replay
```

```bash
.venv/bin/python scripts/ingest_fraud_policy_memory.py --require-supabase
```

```bash
.venv/bin/python scripts/ingest_fraud_policy_memory.py --require-supabase
```

The second importer run must report `policy chunks: 0 inserted, 20 already present` and `requests: 0 inserted`.

## 3. Verification SQL (run in the SQL editor or via MCP)

```sql
-- expect: 20 | 11 | true | true | true | true
select count(*)                                             as chunks,
       count(distinct source_url)                           as sources,
       bool_and(review_status = 'reviewed')                 as all_reviewed,
       bool_and(access_scope = 'public')                    as all_public,
       bool_and(coalesce(content_hash, '') <> '')           as all_hashed,
       bool_and(exists (select 1 from grounding_docs d where d.id = c.doc_id)) as all_linked
from rag_policy_chunks c
where chunk_id like 'fraud-policy-v1:%';

-- expect every row trusted = true
select domain, bool_and(trusted) as trusted, count(*)
from grounding_docs
where domain in ('acquisition.gov','justice.gov','ofac.treasury.gov','sec.gov','fincen.gov')
   or domain like '%.acquisition.gov' or domain like '%.justice.gov' or domain like '%.sec.gov'
group by domain order by domain;

-- duplicates: expect 0 rows
select chunk_id, count(*) from rag_policy_chunks group by chunk_id having count(*) > 1;
select request_fingerprint, count(*) from grounding_requests
where request_fingerprint is not null group by 1 having count(*) > 1;

-- secret scan: expect 0
select count(*) from grounding_requests
where request::text ~* '(x-api-key|bearer\s+[a-z0-9]|service_role|sb_secret_)'
   or coalesce(response::text,'') ~* '(x-api-key"\s*:|bearer\s+ey|sb_secret_)';

-- retrieval smoke tests: each should return >= 1 row
select chunk_id, source_url, rank from search_policy_chunks('duplicate invoice receiving report', k => 3);
select chunk_id, source_url, rank from search_policy_chunks('sanctions screening vendor payment', k => 3);
select chunk_id, source_url, rank from search_policy_chunks('third party due diligence compensation', k => 3);
```

## 4. Storage boundaries (where each kind of data goes)

| Data | Table | Rule |
|---|---|---|
| Raw You.com requests and responses | `grounding_requests` | Payloads only. No headers, no keys. Service-role read only |
| Versioned source pages | `grounding_docs` | One row per (url, content_sha256). `trusted` comes from the allowlist in `src/casefile/youcom.py` |
| Reviewed, reusable policy evidence | `rag_policy_chunks` | `search_policy_chunks` returns only `reviewed`/`approved`, `public` rows |
| Case-specific tool results | `evidence` | Typed envelope: ok / error / empty / partial |
| Model claims plus citation IDs | `claims` | `cites` = evidence ids and chunk ids |
| Compact model-output summaries, tokens, latency, cost | `events.detail` | No system prompts, no hidden reasoning |

Never store: system prompts, `reasoning_content`, credentials, request headers, or personal data unrelated to the case. Retrieved rules and anomalies are **review evidence**, not proof of fraud or legal conclusions.

## 5. Gotchas

- **The service-role key bypasses RLS.** Python backend only (`src/casefile/store.py`). The UI must use the publishable/anon key.
- **The local fallback is silent by design.** Without the key, `Store` writes to `data/store/*.jsonl`. Pass `--require-supabase` wherever a run must hit the database.
- **Replay keeps local UUIDs** and uses `resolution=ignore-duplicates`, so re-running it is safe.
- **New schema changes go in `supabase/migrations/000N_*.sql`.** Apply them in numeric order and never edit an applied file. `supabase_migrations.schema_migrations` shows what's live.
- **You.com Research endpoint:** `YouCom.research()` is off by default, because it runs a non-Crusoe LLM.
