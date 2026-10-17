-- Grounding memory: every You.com request/response is kept, and the pages it returned become a searchable,
-- versioned policy corpus that the Planner and Verifier cite. Retrieval is Postgres full-text search, so no
-- embedding model (and no non-Crusoe model) is needed.

-- One row per You.com API call, success or failure. Raw response kept verbatim for replay and audit.
create table public.grounding_requests (
  id            uuid primary key default gen_random_uuid(),
  endpoint      text not null check (endpoint in ('search','contents','research')),
  request       jsonb not null,
  response      jsonb,
  http_status   int,
  error         text,
  latency_ms    int,
  purpose       text,                      -- e.g. 'policy_corpus', 'case:A-104'
  case_id       uuid references public.cases(id) on delete set null,
  requested_at  timestamptz not null default now()
);
create index on public.grounding_requests (endpoint, requested_at desc);

-- One row per distinct page version. Same URL with changed content -> new row (content_sha256 differs).
create table public.grounding_docs (
  id            uuid primary key default gen_random_uuid(),
  url           text not null,
  domain        text not null,
  title         text,
  markdown      text,
  content_sha256 text not null,
  source_kind   text not null default 'web' check (source_kind in ('web','news','research_source')),
  trusted       boolean not null default false,  -- true only for allowlisted primary sources (fincen.gov, ecfr.gov, ...)
  first_request_id uuid references public.grounding_requests(id) on delete set null,
  fetched_at    timestamptz not null default now(),
  fts           tsvector generated always as (to_tsvector('english', coalesce(title,'') || ' ' || coalesce(markdown,''))) stored,
  unique (url, content_sha256)
);
create index on public.grounding_docs using gin (fts);
create index on public.grounding_docs (url, fetched_at desc);

-- Clauses extracted from trusted docs and bound to a policy signal or check. This is what get_policy returns.
create table public.policy_clauses (
  id            uuid primary key default gen_random_uuid(),
  policy_id     text not null,             -- e.g. 'ato_v1'
  binds_to      text not null,             -- signal or check id, e.g. 'mfa_reset_after_new_device'
  doc_id        uuid not null references public.grounding_docs(id) on delete restrict,
  quote         text not null,             -- short excerpt that must appear verbatim in doc.markdown
  extracted_by  text not null,             -- model id or 'human'
  verified      boolean not null default false,  -- code checked quote is a substring of the doc
  created_at    timestamptz not null default now()
);
create index on public.policy_clauses (policy_id, binds_to);

-- Ranked full-text search over the corpus, used as the agents' memory lookup.
create or replace function public.search_grounding(q text, trusted_only boolean default true, k int default 5)
returns table (id uuid, url text, title text, rank real, excerpt text)
language sql stable as $$
  select d.id, d.url, d.title,
         ts_rank(d.fts, websearch_to_tsquery('english', q)) as rank,
         ts_headline('english', coalesce(d.markdown,''), websearch_to_tsquery('english', q),
                     'MaxFragments=2, MaxWords=40, MinWords=15') as excerpt
  from public.grounding_docs d
  where d.fts @@ websearch_to_tsquery('english', q)
    and (not trusted_only or d.trusted)
  order by rank desc
  limit k
$$;

alter table public.grounding_requests enable row level security;
alter table public.grounding_docs     enable row level security;
alter table public.policy_clauses     enable row level security;
create policy "ui read" on public.grounding_docs  for select to anon using (true);
create policy "ui read" on public.policy_clauses  for select to anon using (true);
-- grounding_requests holds raw API payloads: service role only.
