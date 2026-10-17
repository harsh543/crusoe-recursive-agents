-- Casefile schema: case memory, frozen contracts, evidence receipts, trace, benchmark, N+1 playbooks.
-- Agents write through the Python backend with the service role. The UI reads with anon via RLS.
-- Ground truth lives in schema `oracle`, which is not exposed to the API and has no grants to anon/authenticated.

create extension if not exists pgcrypto;

-- ---------- benchmark runs ----------
create table public.runs (
  id            uuid primary key default gen_random_uuid(),
  config        text not null check (config in ('C1_single','C2_critic','C3_casefile')),
  model_map     jsonb not null,            -- {"planner": "...", "investigator": "...", ...}
  split         text not null check (split in ('dev','heldout')),
  playbook_version int,
  started_at    timestamptz not null default now(),
  finished_at   timestamptz,
  summary       jsonb                      -- metrics computed by eval/run.py
);

-- ---------- cases ----------
create table public.cases (
  id            uuid primary key default gen_random_uuid(),
  run_id        uuid references public.runs(id) on delete cascade,
  alert_id      text not null,             -- e.g. A-104
  tenant_id     text not null,
  account_hint  text not null,             -- what the alert gives us (may be an email)
  faults        text[] not null default '{}', -- injected faults; hidden from agents by the backend
  status        text not null default 'intake'
                check (status in ('intake','planning','investigating','verifying','attributing','replanning','done')),
  disposition   text check (disposition in ('escalate','close_benign','insufficient_evidence')),
  evidence_collection text check (evidence_collection in ('succeeded','failed')),
  replans       int not null default 0,
  tool_calls    int not null default 0,
  created_at    timestamptz not null default now(),
  closed_at     timestamptz,
  unique (run_id, alert_id)
);

-- ---------- frozen completion contracts ----------
create table public.contracts (
  id            uuid primary key default gen_random_uuid(),
  case_id       uuid not null references public.cases(id) on delete cascade,
  version       int not null,
  body          jsonb not null,            -- schema-constrained contract (checks, window, sources, budget)
  sha256        text not null,             -- hash of canonical JSON at freeze time
  frozen_at     timestamptz not null default now(),
  unique (case_id, version)
);

-- ---------- evidence receipts (one per tool call) ----------
create table public.evidence (
  id            uuid primary key default gen_random_uuid(),
  case_id       uuid not null references public.cases(id) on delete cascade,
  step          int not null,
  tool          text not null,
  args          jsonb not null,
  status        text not null check (status in ('ok','error','empty','partial')),
  error         text,
  rows          jsonb not null default '[]',
  coverage      tstzrange,                 -- time span the rows actually cover
  account_id    text,                      -- account the rows belong to (checked by correct_account)
  fetched_at    timestamptz not null default now()
);
create index on public.evidence (case_id, step);

-- ---------- claims ----------
create table public.claims (
  id            uuid primary key default gen_random_uuid(),
  case_id       uuid not null references public.cases(id) on delete cascade,
  attempt       int not null,
  text          text not null,
  numeric_value numeric,                   -- recomputed by the verifier when present
  cites         uuid[] not null default '{}'
);

-- ---------- verifier results ----------
create table public.check_results (
  id            uuid primary key default gen_random_uuid(),
  case_id       uuid not null references public.cases(id) on delete cascade,
  attempt       int not null,
  check_id      text not null,
  passed        boolean not null,
  reason        text,                      -- actionable, e.g. "device_history status=error"
  created_at    timestamptz not null default now()
);

-- ---------- failure attribution ----------
create table public.attributions (
  id            uuid primary key default gen_random_uuid(),
  case_id       uuid not null references public.cases(id) on delete cascade,
  attempt       int not null,
  agent         text not null check (agent in ('planner','investigator','verifier','gate')),
  step          int not null,
  category      text not null check (category in ('specification','inter_agent_misalignment','task_verification')),
  failure_type  text,                      -- e.g. wrong_identifier, stale_records
  confidence    real,
  model         text not null,
  created_at    timestamptz not null default now()
);

-- ---------- append-only trace (drives the UI timeline via Realtime) ----------
create table public.events (
  id            bigint generated always as identity primary key,
  case_id       uuid not null references public.cases(id) on delete cascade,
  ts            timestamptz not null default now(),
  state         text not null,
  role          text,
  model         text,
  step          int,
  prompt_tokens int,
  cached_tokens int,
  completion_tokens int,
  latency_ms    int,
  cost_usd      numeric(12,8),
  detail        jsonb
);
create index on public.events (case_id, id);

-- ---------- gate writes (idempotent) ----------
create table public.dispositions (
  idempotency_key text primary key,
  case_id       uuid not null references public.cases(id) on delete cascade,
  disposition   text not null check (disposition in ('escalate','close_benign','insufficient_evidence')),
  contract_sha256 text not null,
  committed_at  timestamptz not null default now()
);

-- ---------- Version N+1 playbooks ----------
create table public.playbooks (
  id            uuid primary key default gen_random_uuid(),
  role          text not null check (role in ('planner','investigator')),  -- completion policy is NOT editable
  version       int not null,
  body          text not null,
  diff_from_prev text,
  rationale     text,
  dev_score     real,
  heldout_score real,
  kept          boolean,
  created_at    timestamptz not null default now(),
  unique (role, version)
);

-- ---------- ground truth: never readable by agents or UI ----------
create schema if not exists oracle;
revoke all on schema oracle from anon, authenticated;
create table oracle.labels (
  alert_id      text primary key,
  split         text not null check (split in ('dev','heldout')),
  disposition   text not null check (disposition in ('escalate','close_benign','insufficient_evidence')),
  faulty_agent  text,
  faulty_step   int,
  notes         text
);
revoke all on oracle.labels from anon, authenticated;

-- ---------- RLS: UI may read the timeline, nothing may write except the service role ----------
alter table public.runs          enable row level security;
alter table public.cases         enable row level security;
alter table public.contracts     enable row level security;
alter table public.evidence      enable row level security;
alter table public.claims        enable row level security;
alter table public.check_results enable row level security;
alter table public.attributions  enable row level security;
alter table public.events        enable row level security;
alter table public.dispositions  enable row level security;
alter table public.playbooks     enable row level security;

create policy "ui read" on public.runs          for select to anon using (true);
create policy "ui read" on public.cases         for select to anon using (true);
create policy "ui read" on public.contracts     for select to anon using (true);
create policy "ui read" on public.check_results for select to anon using (true);
create policy "ui read" on public.attributions  for select to anon using (true);
create policy "ui read" on public.events        for select to anon using (true);
create policy "ui read" on public.playbooks     for select to anon using (true);

alter publication supabase_realtime add table public.events, public.cases, public.check_results;
