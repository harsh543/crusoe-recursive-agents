-- Four-layer enterprise memory with a database-enforced certification gate.
--
-- Working memory is transient and deleted when its episode closes. Episodic
-- memory is an immutable, bounded trace. Semantic and procedural candidates
-- never become organizational memory until automated confidence AND an
-- independent human SME review pass. Retrieval exposes certified memory only.

-- ---------- working memory: task-local and disposable ----------
create table if not exists public.agent_working_memory (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      text not null,
  task_id        text not null,
  case_id        uuid references public.cases(id) on delete cascade,
  owner_agent    text not null,
  content        jsonb not null default '{}'::jsonb,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  expires_at     timestamptz not null,
  unique (tenant_id, task_id),
  check (octet_length(content::text) <= 65536)
);
create index if not exists agent_working_memory_expiry_idx
  on public.agent_working_memory (expires_at);

-- ---------- episodic memory: one complete, immutable run trace ----------
create table if not exists public.agent_memory_episodes (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      text not null,
  task_id        text not null,
  case_id        uuid references public.cases(id) on delete set null,
  owner_agent    text not null,
  agent_version  text not null,
  status         text not null default 'open' check (status in ('open', 'closed')),
  started_at     timestamptz not null default now(),
  closed_at      timestamptz,
  outcome        text,
  review_label   text,
  check ((status = 'open' and closed_at is null) or (status = 'closed' and closed_at is not null))
);
create unique index if not exists one_open_memory_episode_per_task_idx
  on public.agent_memory_episodes (tenant_id, task_id) where status = 'open';

create table if not exists public.agent_memory_episode_events (
  id             bigint generated always as identity primary key,
  episode_id     uuid not null references public.agent_memory_episodes(id) on delete restrict,
  seq            int not null,
  action         text not null,
  agent          text not null,
  agent_version  text not null,
  data           jsonb not null default '{}'::jsonb,
  evidence_ids   text[] not null default '{}',
  occurred_at    timestamptz not null default now(),
  unique (episode_id, seq),
  check (octet_length(data::text) <= 65536)
);
create index if not exists agent_memory_episode_events_lookup_idx
  on public.agent_memory_episode_events (episode_id, seq);

-- ---------- semantic/procedural candidates: inert until certified ----------
create table if not exists public.organizational_memory_candidates (
  id                    uuid primary key default gen_random_uuid(),
  tenant_id             text not null,
  memory_kind           text not null check (memory_kind in ('semantic', 'procedural')),
  subject               text not null,
  content               jsonb not null,
  author_identity       text not null,
  proposing_team        text not null,
  source_episode_ids    uuid[] not null default '{}',
  evidence_ids          text[] not null default '{}',
  automated_confidence  numeric(5,4) not null check (automated_confidence between 0 and 1),
  confidence_threshold  numeric(5,4) not null default 0.8500 check (confidence_threshold between 0 and 1),
  valid_until           timestamptz,
  created_at            timestamptz not null default now(),
  check (octet_length(content::text) <= 32768),
  check (
    (memory_kind = 'semantic' and cardinality(evidence_ids) > 0 and valid_until is not null)
    or
    (memory_kind = 'procedural' and cardinality(source_episode_ids) > 0)
  )
);
create index if not exists organizational_memory_candidates_lookup_idx
  on public.organizational_memory_candidates (tenant_id, memory_kind, subject, created_at desc);

create table if not exists public.organizational_memory_certifications (
  id                uuid primary key default gen_random_uuid(),
  candidate_id      uuid not null unique references public.organizational_memory_candidates(id) on delete restrict,
  decision          text not null check (decision in ('approved', 'rejected')),
  reviewer_identity text not null,
  reviewer_team     text not null,
  reviewer_role     text not null check (reviewer_role in (
    'subject_matter_expert', 'risk_analyst', 'compliance_officer', 'agent_governance'
  )),
  human_review      boolean not null default true check (human_review),
  rationale         text not null,
  evaluation_id     text,
  score_before      numeric,
  score_after       numeric,
  certified_at      timestamptz not null default now(),
  check (length(btrim(rationale)) > 0)
);

create table if not exists public.organizational_memory_retirements (
  id             uuid primary key default gen_random_uuid(),
  candidate_id   uuid not null unique references public.organizational_memory_candidates(id) on delete restrict,
  retired_by     text not null,
  retiring_team  text not null,
  reason         text not null check (reason in ('expired', 'superseded', 'revoked', 'policy_change')),
  detail         text,
  retired_at     timestamptz not null default now()
);

-- ---------- small/System-1 routing audit ----------
create table if not exists public.model_routing_decisions (
  id                 uuid primary key default gen_random_uuid(),
  tenant_id          text not null,
  case_id            uuid references public.cases(id) on delete set null,
  task_id            text not null,
  role               text not null,
  task_class         text not null,
  system_level       text not null check (system_level in ('system_1', 'system_2')),
  selected_model     text not null,
  reason             text not null,
  confidence         numeric(5,4) check (confidence is null or confidence between 0 and 1),
  estimated_cost_usd numeric(12,8),
  actual_cost_usd    numeric(12,8),
  escalated_from_id  uuid references public.model_routing_decisions(id) on delete set null,
  created_at         timestamptz not null default now()
);
create index if not exists model_routing_decisions_task_idx
  on public.model_routing_decisions (tenant_id, task_id, created_at);

-- ---------- immutability and lifecycle enforcement ----------
create or replace function public.reject_memory_mutation()
returns trigger
language plpgsql
set search_path = public, pg_catalog
as $$
begin
  raise exception '% is append-only; create a replacement or retirement record', tg_table_name;
end;
$$;

drop trigger if exists memory_events_append_only on public.agent_memory_episode_events;
create trigger memory_events_append_only
before update or delete on public.agent_memory_episode_events
for each row execute function public.reject_memory_mutation();

drop trigger if exists memory_candidates_append_only on public.organizational_memory_candidates;
create trigger memory_candidates_append_only
before update or delete on public.organizational_memory_candidates
for each row execute function public.reject_memory_mutation();

drop trigger if exists memory_certifications_append_only on public.organizational_memory_certifications;
create trigger memory_certifications_append_only
before update or delete on public.organizational_memory_certifications
for each row execute function public.reject_memory_mutation();

drop trigger if exists memory_retirements_append_only on public.organizational_memory_retirements;
create trigger memory_retirements_append_only
before update or delete on public.organizational_memory_retirements
for each row execute function public.reject_memory_mutation();

create or replace function public.validate_episode_event()
returns trigger
language plpgsql
set search_path = public, pg_catalog
as $$
begin
  if not exists (
    select 1 from public.agent_memory_episodes e
    where e.id = new.episode_id and e.status = 'open'
  ) then
    raise exception 'episode % is missing or closed', new.episode_id;
  end if;
  return new;
end;
$$;

drop trigger if exists memory_event_requires_open_episode on public.agent_memory_episode_events;
create trigger memory_event_requires_open_episode
before insert on public.agent_memory_episode_events
for each row execute function public.validate_episode_event();

create or replace function public.validate_memory_certification()
returns trigger
language plpgsql
set search_path = public, pg_catalog
as $$
declare
  candidate public.organizational_memory_candidates%rowtype;
begin
  select * into candidate
  from public.organizational_memory_candidates
  where id = new.candidate_id
  for update;

  if not found then
    raise exception 'memory candidate % does not exist', new.candidate_id;
  end if;
  if btrim(new.reviewer_identity) = '' or btrim(new.reviewer_team) = '' then
    raise exception 'certification requires reviewer identity and team';
  end if;
  if new.reviewer_identity = candidate.author_identity then
    raise exception 'memory author cannot certify their own candidate';
  end if;

  if new.decision = 'approved' then
    if not new.human_review then
      raise exception 'organizational memory approval requires human SME review';
    end if;
    if candidate.automated_confidence < candidate.confidence_threshold then
      raise exception 'automated confidence % is below threshold %',
        candidate.automated_confidence, candidate.confidence_threshold;
    end if;
    if candidate.memory_kind = 'semantic' and candidate.valid_until <= now() then
      raise exception 'expired semantic memory cannot be certified';
    end if;
    if candidate.memory_kind = 'procedural' then
      if new.evaluation_id is null or new.score_before is null or new.score_after is null then
        raise exception 'procedural approval requires an evaluation and before/after scores';
      end if;
      if new.score_after <= new.score_before then
        raise exception 'procedural memory must demonstrate a strict measured improvement';
      end if;
      if exists (
        select 1
        from unnest(candidate.source_episode_ids) source_id
        left join public.agent_memory_episodes e
          on e.id = source_id and e.tenant_id = candidate.tenant_id and e.status = 'closed'
        where e.id is null
      ) then
        raise exception 'procedural memory must reference closed episodes from the same tenant';
      end if;
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists organizational_memory_certification_gate on public.organizational_memory_certifications;
create trigger organizational_memory_certification_gate
before insert on public.organizational_memory_certifications
for each row execute function public.validate_memory_certification();

-- ---------- backend-only lifecycle RPCs ----------
create or replace function public.start_working_memory(
  p_tenant_id text,
  p_task_id text,
  p_owner_agent text,
  p_content jsonb default '{}'::jsonb,
  p_case_id uuid default null,
  p_ttl_minutes int default 180
)
returns uuid
language plpgsql
security definer
set search_path = public, pg_catalog
as $$
declare created_id uuid;
begin
  insert into public.agent_working_memory (
    tenant_id, task_id, case_id, owner_agent, content, expires_at
  ) values (
    p_tenant_id, p_task_id, p_case_id, p_owner_agent, coalesce(p_content, '{}'::jsonb),
    now() + make_interval(mins => greatest(1, least(p_ttl_minutes, 1440)))
  ) returning id into created_id;
  return created_id;
end;
$$;

create or replace function public.update_working_memory(
  p_tenant_id text,
  p_task_id text,
  p_patch jsonb
)
returns boolean
language plpgsql
security definer
set search_path = public, pg_catalog
as $$
begin
  update public.agent_working_memory
  set content = content || coalesce(p_patch, '{}'::jsonb), updated_at = now()
  where tenant_id = p_tenant_id and task_id = p_task_id and expires_at > now();
  if not found then
    raise exception 'working memory %/% is missing or expired', p_tenant_id, p_task_id;
  end if;
  return true;
end;
$$;

create or replace function public.working_memory_snapshot(p_tenant_id text, p_task_id text)
returns jsonb
language sql
stable
security definer
set search_path = public, pg_catalog
as $$
  select content from public.agent_working_memory
  where tenant_id = p_tenant_id and task_id = p_task_id and expires_at > now()
$$;

create or replace function public.discard_working_memory(p_tenant_id text, p_task_id text)
returns boolean
language plpgsql
security definer
set search_path = public, pg_catalog
as $$
begin
  delete from public.agent_working_memory
  where tenant_id = p_tenant_id and task_id = p_task_id;
  return found;
end;
$$;

create or replace function public.open_memory_episode(
  p_tenant_id text,
  p_task_id text,
  p_owner_agent text,
  p_agent_version text,
  p_initial_working_memory jsonb default '{}'::jsonb,
  p_case_id uuid default null,
  p_ttl_minutes int default 180
)
returns uuid
language plpgsql
security definer
set search_path = public, pg_catalog
as $$
declare episode_id uuid;
begin
  insert into public.agent_memory_episodes (
    tenant_id, task_id, case_id, owner_agent, agent_version
  ) values (
    p_tenant_id, p_task_id, p_case_id, p_owner_agent, p_agent_version
  ) returning id into episode_id;

  perform public.start_working_memory(
    p_tenant_id, p_task_id, p_owner_agent, p_initial_working_memory, p_case_id, p_ttl_minutes
  );
  return episode_id;
end;
$$;

create or replace function public.record_memory_episode_event(
  p_episode_id uuid,
  p_action text,
  p_agent text,
  p_agent_version text,
  p_data jsonb default '{}'::jsonb,
  p_evidence_ids text[] default '{}'
)
returns int
language plpgsql
security definer
set search_path = public, pg_catalog
as $$
declare next_seq int;
begin
  perform 1 from public.agent_memory_episodes where id = p_episode_id for update;
  if not found then
    raise exception 'episode % does not exist', p_episode_id;
  end if;
  select coalesce(max(seq), 0) + 1 into next_seq
  from public.agent_memory_episode_events where episode_id = p_episode_id;
  insert into public.agent_memory_episode_events (
    episode_id, seq, action, agent, agent_version, data, evidence_ids
  ) values (
    p_episode_id, next_seq, p_action, p_agent, p_agent_version,
    coalesce(p_data, '{}'::jsonb), coalesce(p_evidence_ids, '{}')
  );
  return next_seq;
end;
$$;

create or replace function public.close_memory_episode(
  p_episode_id uuid,
  p_outcome text,
  p_review_label text default null
)
returns boolean
language plpgsql
security definer
set search_path = public, pg_catalog
as $$
declare episode public.agent_memory_episodes%rowtype;
begin
  select * into episode from public.agent_memory_episodes where id = p_episode_id for update;
  if not found or episode.status <> 'open' then
    raise exception 'episode % is missing or already closed', p_episode_id;
  end if;
  if not exists (select 1 from public.agent_memory_episode_events where episode_id = p_episode_id) then
    raise exception 'episode % cannot close without a trace event', p_episode_id;
  end if;

  update public.agent_memory_episodes
  set status = 'closed', closed_at = now(), outcome = p_outcome, review_label = p_review_label
  where id = p_episode_id;

  -- The database, not caller convention, guarantees task-local memory disposal.
  delete from public.agent_working_memory
  where tenant_id = episode.tenant_id and task_id = episode.task_id;
  return true;
end;
$$;

create or replace function public.get_memory_episode_events(p_episode_id uuid, p_k int default 50)
returns setof public.agent_memory_episode_events
language sql
stable
security definer
set search_path = public, pg_catalog
as $$
  select * from public.agent_memory_episode_events
  where episode_id = p_episode_id
  order by seq
  limit greatest(0, least(p_k, 100))
$$;

create or replace function public.propose_semantic_memory(
  p_tenant_id text,
  p_subject text,
  p_content jsonb,
  p_author_identity text,
  p_proposing_team text,
  p_evidence_ids text[],
  p_automated_confidence numeric,
  p_valid_until timestamptz,
  p_source_episode_ids uuid[] default '{}',
  p_confidence_threshold numeric default 0.8500
)
returns uuid
language plpgsql
security definer
set search_path = public, pg_catalog
as $$
declare candidate_id uuid;
begin
  if p_valid_until <= now() then
    raise exception 'semantic memory must expire in the future';
  end if;
  insert into public.organizational_memory_candidates (
    tenant_id, memory_kind, subject, content, author_identity, proposing_team,
    source_episode_ids, evidence_ids, automated_confidence, confidence_threshold, valid_until
  ) values (
    p_tenant_id, 'semantic', p_subject, p_content, p_author_identity, p_proposing_team,
    coalesce(p_source_episode_ids, '{}'), p_evidence_ids, p_automated_confidence,
    p_confidence_threshold, p_valid_until
  ) returning id into candidate_id;
  return candidate_id;
end;
$$;

create or replace function public.propose_procedural_memory(
  p_tenant_id text,
  p_subject text,
  p_workflow jsonb,
  p_author_identity text,
  p_proposing_team text,
  p_source_episode_ids uuid[],
  p_automated_confidence numeric,
  p_evidence_ids text[] default '{}',
  p_confidence_threshold numeric default 0.8500
)
returns uuid
language plpgsql
security definer
set search_path = public, pg_catalog
as $$
declare candidate_id uuid;
begin
  insert into public.organizational_memory_candidates (
    tenant_id, memory_kind, subject, content, author_identity, proposing_team,
    source_episode_ids, evidence_ids, automated_confidence, confidence_threshold
  ) values (
    p_tenant_id, 'procedural', p_subject, p_workflow, p_author_identity, p_proposing_team,
    p_source_episode_ids, coalesce(p_evidence_ids, '{}'), p_automated_confidence,
    p_confidence_threshold
  ) returning id into candidate_id;
  return candidate_id;
end;
$$;

create or replace function public.review_enterprise_memory(
  p_candidate_id uuid,
  p_decision text,
  p_reviewer_identity text,
  p_reviewer_team text,
  p_reviewer_role text,
  p_rationale text,
  p_evaluation_id text default null,
  p_score_before numeric default null,
  p_score_after numeric default null
)
returns uuid
language plpgsql
security definer
set search_path = public, pg_catalog
as $$
declare certification_id uuid;
begin
  insert into public.organizational_memory_certifications (
    candidate_id, decision, reviewer_identity, reviewer_team, reviewer_role,
    human_review, rationale, evaluation_id, score_before, score_after
  ) values (
    p_candidate_id, p_decision, p_reviewer_identity, p_reviewer_team, p_reviewer_role,
    true, p_rationale, p_evaluation_id, p_score_before, p_score_after
  ) returning id into certification_id;
  return certification_id;
end;
$$;

create or replace function public.forget_expired_enterprise_memory(p_tenant_id text default null)
returns int
language plpgsql
security definer
set search_path = public, pg_catalog
as $$
declare forgotten int;
begin
  insert into public.organizational_memory_retirements (
    candidate_id, retired_by, retiring_team, reason, detail
  )
  select c.id, 'system:expiry', 'memory-governance', 'expired', 'valid_until reached'
  from public.organizational_memory_candidates c
  join public.organizational_memory_certifications cert
    on cert.candidate_id = c.id and cert.decision = 'approved'
  left join public.organizational_memory_retirements r on r.candidate_id = c.id
  where c.memory_kind = 'semantic'
    and c.valid_until <= now()
    and r.id is null
    and (p_tenant_id is null or c.tenant_id = p_tenant_id)
  on conflict (candidate_id) do nothing;
  get diagnostics forgotten = row_count;
  return forgotten;
end;
$$;

create or replace function public.retire_enterprise_memory(
  p_candidate_id uuid,
  p_retired_by text,
  p_retiring_team text,
  p_reason text,
  p_detail text default null
)
returns uuid
language plpgsql
security definer
set search_path = public, pg_catalog
as $$
declare retirement_id uuid;
begin
  insert into public.organizational_memory_retirements (
    candidate_id, retired_by, retiring_team, reason, detail
  ) values (
    p_candidate_id, p_retired_by, p_retiring_team, p_reason, p_detail
  ) returning id into retirement_id;
  return retirement_id;
end;
$$;

create or replace view public.certified_organizational_memory
with (security_invoker = true)
as
select
  c.id,
  c.tenant_id,
  c.memory_kind,
  c.subject,
  c.content,
  c.source_episode_ids,
  c.evidence_ids,
  c.automated_confidence,
  c.confidence_threshold,
  c.valid_until,
  c.created_at,
  cert.reviewer_identity as certified_by,
  cert.reviewer_team as certifying_team,
  cert.reviewer_role,
  cert.rationale as certification_rationale,
  cert.evaluation_id,
  cert.score_before,
  cert.score_after,
  cert.certified_at
from public.organizational_memory_candidates c
join public.organizational_memory_certifications cert
  on cert.candidate_id = c.id and cert.decision = 'approved'
left join public.organizational_memory_retirements retired on retired.candidate_id = c.id
where retired.id is null
  and (c.valid_until is null or c.valid_until > now());

create or replace function public.retrieve_organizational_memory(
  p_tenant_id text,
  p_subject text default null,
  p_k int default 10
)
returns setof public.certified_organizational_memory
language plpgsql
security definer
set search_path = public, pg_catalog
as $$
begin
  -- Retrieval actively records expiry tombstones before returning current truth.
  perform public.forget_expired_enterprise_memory(p_tenant_id);
  return query
    select * from public.certified_organizational_memory m
    where m.tenant_id = p_tenant_id
      and (p_subject is null or m.subject = p_subject)
    order by m.certified_at desc
    limit greatest(0, least(p_k, 20));
end;
$$;

-- ---------- access: backend service role only ----------
alter table public.agent_working_memory enable row level security;
alter table public.agent_memory_episodes enable row level security;
alter table public.agent_memory_episode_events enable row level security;
alter table public.organizational_memory_candidates enable row level security;
alter table public.organizational_memory_certifications enable row level security;
alter table public.organizational_memory_retirements enable row level security;
alter table public.model_routing_decisions enable row level security;

revoke all on public.agent_working_memory from anon, authenticated;
revoke all on public.agent_memory_episodes from anon, authenticated;
revoke all on public.agent_memory_episode_events from anon, authenticated;
revoke all on public.organizational_memory_candidates from anon, authenticated;
revoke all on public.organizational_memory_certifications from anon, authenticated;
revoke all on public.organizational_memory_retirements from anon, authenticated;
revoke all on public.model_routing_decisions from anon, authenticated;
revoke all on public.certified_organizational_memory from anon, authenticated;

revoke execute on function public.start_working_memory(text, text, text, jsonb, uuid, int) from public, anon, authenticated;
revoke execute on function public.update_working_memory(text, text, jsonb) from public, anon, authenticated;
revoke execute on function public.working_memory_snapshot(text, text) from public, anon, authenticated;
revoke execute on function public.discard_working_memory(text, text) from public, anon, authenticated;
revoke execute on function public.open_memory_episode(text, text, text, text, jsonb, uuid, int) from public, anon, authenticated;
revoke execute on function public.record_memory_episode_event(uuid, text, text, text, jsonb, text[]) from public, anon, authenticated;
revoke execute on function public.close_memory_episode(uuid, text, text) from public, anon, authenticated;
revoke execute on function public.get_memory_episode_events(uuid, int) from public, anon, authenticated;
revoke execute on function public.propose_semantic_memory(text, text, jsonb, text, text, text[], numeric, timestamptz, uuid[], numeric) from public, anon, authenticated;
revoke execute on function public.propose_procedural_memory(text, text, jsonb, text, text, uuid[], numeric, text[], numeric) from public, anon, authenticated;
revoke execute on function public.review_enterprise_memory(uuid, text, text, text, text, text, text, numeric, numeric) from public, anon, authenticated;
revoke execute on function public.forget_expired_enterprise_memory(text) from public, anon, authenticated;
revoke execute on function public.retire_enterprise_memory(uuid, text, text, text, text) from public, anon, authenticated;
revoke execute on function public.retrieve_organizational_memory(text, text, int) from public, anon, authenticated;

grant execute on function public.start_working_memory(text, text, text, jsonb, uuid, int) to service_role;
grant execute on function public.update_working_memory(text, text, jsonb) to service_role;
grant execute on function public.working_memory_snapshot(text, text) to service_role;
grant execute on function public.discard_working_memory(text, text) to service_role;
grant execute on function public.open_memory_episode(text, text, text, text, jsonb, uuid, int) to service_role;
grant execute on function public.record_memory_episode_event(uuid, text, text, text, jsonb, text[]) to service_role;
grant execute on function public.close_memory_episode(uuid, text, text) to service_role;
grant execute on function public.get_memory_episode_events(uuid, int) to service_role;
grant execute on function public.propose_semantic_memory(text, text, jsonb, text, text, text[], numeric, timestamptz, uuid[], numeric) to service_role;
grant execute on function public.propose_procedural_memory(text, text, jsonb, text, text, uuid[], numeric, text[], numeric) to service_role;
grant execute on function public.review_enterprise_memory(uuid, text, text, text, text, text, text, numeric, numeric) to service_role;
grant execute on function public.forget_expired_enterprise_memory(text) to service_role;
grant execute on function public.retire_enterprise_memory(uuid, text, text, text, text) to service_role;
grant execute on function public.retrieve_organizational_memory(text, text, int) to service_role;

