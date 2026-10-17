-- Reviewed fraud-policy RAG chunks derived from versioned grounding documents.
-- Raw You.com requests and page versions remain in grounding_requests/grounding_docs.

alter table public.grounding_requests
  add column if not exists request_fingerprint text,
  add column if not exists source_file text;

create unique index if not exists grounding_requests_request_fingerprint_idx
  on public.grounding_requests (request_fingerprint)
  where request_fingerprint is not null;

create table if not exists public.rag_policy_chunks (
  id               uuid primary key default gen_random_uuid(),
  chunk_id         text not null unique,
  rule_id          text,
  text             text not null,
  domain           text not null,
  source_title     text not null,
  source_url       text not null,
  source_date      text,
  source_page      text,
  source_section   text,
  authority_level  text not null check (authority_level in (
    'law_or_regulation', 'government_guidance', 'multilateral_guidance',
    'industry_rulebook', 'company_policy', 'internal_policy', 'research'
  )),
  jurisdiction     text,
  effective_from   date,
  effective_to     date,
  access_scope     text not null check (access_scope in ('public', 'organization', 'restricted')),
  retrieved_at     timestamptz not null,
  content_hash     text not null,
  supersedes_chunk_id text references public.rag_policy_chunks(chunk_id) on delete set null,
  review_status    text not null check (review_status in ('unreviewed', 'reviewed', 'approved', 'retired')),
  binding_status   text,
  applicability    text,
  evidence_fields  text[] not null default '{}',
  recommended_action text,
  retrieval_source_url text,
  notes            text,
  doc_id           uuid references public.grounding_docs(id) on delete set null,
  metadata         jsonb not null default '{}'::jsonb,
  fts              tsvector generated always as (
    to_tsvector('english', coalesce(rule_id, '') || ' ' || coalesce(domain, '') || ' ' ||
      coalesce(source_title, '') || ' ' || coalesce(source_section, '') || ' ' || text)
  ) stored,
  check (effective_to is null or effective_from is null or effective_to >= effective_from)
);

create index if not exists rag_policy_chunks_fts_idx on public.rag_policy_chunks using gin (fts);
create index if not exists rag_policy_chunks_filters_idx
  on public.rag_policy_chunks (review_status, authority_level, jurisdiction, domain);
create index if not exists rag_policy_chunks_source_idx
  on public.rag_policy_chunks (source_url, retrieved_at desc);

create or replace function public.search_policy_chunks(
  q text,
  authority_levels text[] default null,
  jurisdiction_filter text default null,
  domain_filter text default null,
  k int default 8
)
returns table (
  chunk_id text,
  rule_id text,
  text text,
  source_title text,
  source_url text,
  source_section text,
  authority_level text,
  jurisdiction text,
  binding_status text,
  retrieved_at timestamptz,
  rank real
)
language sql stable as $$
  select c.chunk_id, c.rule_id, c.text, c.source_title, c.source_url,
         c.source_section, c.authority_level, c.jurisdiction,
         c.binding_status, c.retrieved_at,
         ts_rank(c.fts, websearch_to_tsquery('english', q)) as rank
  from public.rag_policy_chunks c
  where c.fts @@ websearch_to_tsquery('english', q)
    and c.review_status in ('reviewed', 'approved')
    and c.access_scope = 'public'
    and (authority_levels is null or c.authority_level = any(authority_levels))
    and (jurisdiction_filter is null or c.jurisdiction = jurisdiction_filter)
    and (domain_filter is null or c.domain = domain_filter)
  order by rank desc, c.retrieved_at desc
  limit greatest(1, least(k, 50));
$$;

alter table public.rag_policy_chunks enable row level security;

create policy "public read reviewed policy chunks"
  on public.rag_policy_chunks
  for select to anon, authenticated
  using (access_scope = 'public' and review_status in ('reviewed', 'approved'));
