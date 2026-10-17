-- Structured account evidence the investigator reads (replaces Case.raw), plus constraint fixes so the
-- durable case record matches the code's outcome vocabulary and You.com/Finance requests link to a case.

create table public.accounts (
  account_id    text primary key,
  tenant_id     text not null,
  email         text not null,
  home_country  text,
  created_at    timestamptz not null default now(),
  unique (tenant_id, email)
);

create table public.device_events (
  id            uuid primary key default gen_random_uuid(),
  account_id    text not null references public.accounts(account_id) on delete cascade,
  kind          text not null check (kind in ('device_seen','mfa_reset')),
  device_id     text not null default '',
  country       text,
  known         boolean,
  occurred_at   timestamptz not null,
  unique (account_id, kind, device_id, occurred_at)
);
create index on public.device_events (account_id, occurred_at);

create table public.transactions (
  id            uuid primary key default gen_random_uuid(),
  account_id    text not null references public.accounts(account_id) on delete cascade,
  tx_id         text not null,
  kind          text not null,
  amount        numeric(14,2) not null,
  beneficiary   text,
  beneficiary_new boolean,
  occurred_at   timestamptz not null,
  unique (account_id, tx_id)
);
create index on public.transactions (account_id, occurred_at);

alter table public.accounts      enable row level security;
alter table public.device_events enable row level security;
alter table public.transactions  enable row level security;   -- no anon policy: service role only

-- outcome vocabulary used by the code
alter table public.evidence drop constraint if exists evidence_status_check;
alter table public.evidence add constraint evidence_status_check check (status in ('ok','error','empty','partial','stale'));
alter table public.cases drop constraint if exists cases_disposition_check;
alter table public.cases add constraint cases_disposition_check
  check (disposition in ('escalated','closed_benign','insufficient_evidence','collection_failed'));
alter table public.dispositions drop constraint if exists dispositions_disposition_check;
alter table public.dispositions add constraint dispositions_disposition_check
  check (disposition in ('escalated','closed_benign','insufficient_evidence','collection_failed'));
alter table public.runs drop constraint if exists runs_config_check;
alter table public.runs add constraint runs_config_check check (config in ('C1','C2','C3','C1_single','C2_critic','C3_casefile','records'));

-- records-mode claim verdicts live on claims
alter table public.claims add column if not exists claim_ref text;
alter table public.claims add column if not exists verdict text;
alter table public.claims add column if not exists claim_type text;

-- every You.com request, including Finance MCP responses, links to a case
alter table public.grounding_requests drop constraint if exists grounding_requests_endpoint_check;
alter table public.grounding_requests add constraint grounding_requests_endpoint_check
  check (endpoint in ('search','contents','research','finance_mcp'));
alter table public.grounding_requests add column if not exists tool text;
create index if not exists grounding_requests_case_idx on public.grounding_requests (case_id);
