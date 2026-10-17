-- Per-case hash-chained audit trail. Each row's hash covers the previous hash, so editing or deleting any row breaks verification.
create table public.audit_log (
  id         bigint generated always as identity primary key,
  case_id    uuid not null references public.cases(id) on delete cascade,
  seq        int not null,
  type       text not null,
  data       jsonb not null,
  prev       text not null,
  hash       text not null,
  created_at timestamptz not null default now(),
  unique (case_id, seq)
);
create index on public.audit_log (case_id, seq);
alter table public.audit_log enable row level security;   -- service role only
