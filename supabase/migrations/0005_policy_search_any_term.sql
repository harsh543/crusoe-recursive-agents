-- search_policy_chunks required every query term in one chunk (websearch_to_tsquery ANDs terms), so natural
-- queries like "duplicate invoice receiving report" matched nothing. Match on ANY term instead, and rank
-- chunks that contain all terms first. Same signature and return type, so callers are unaffected.
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
language sql stable
set search_path = public, pg_catalog
as $$
  with tq as (
    select websearch_to_tsquery('english', q) as all_terms,
           to_tsquery('english', nullif(replace(websearch_to_tsquery('english', q)::text, ' & ', ' | '), '')) as any_term
  )
  select c.chunk_id, c.rule_id, c.text, c.source_title, c.source_url,
         c.source_section, c.authority_level, c.jurisdiction,
         c.binding_status, c.retrieved_at,
         (ts_rank(c.fts, tq.any_term) + case when c.fts @@ tq.all_terms then 1 else 0 end)::real as rank
  from public.rag_policy_chunks c, tq
  where c.fts @@ tq.any_term
    and c.review_status in ('reviewed', 'approved')
    and c.access_scope = 'public'
    and (authority_levels is null or c.authority_level = any(authority_levels))
    and (jurisdiction_filter is null or c.jurisdiction = jurisdiction_filter)
    and (domain_filter is null or c.domain = domain_filter)
  order by rank desc, c.retrieved_at desc
  limit greatest(1, least(k, 50));
$$;
