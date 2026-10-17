-- Records-mode verdicts are dispositions too; they have no transaction contract, so the contract hash is optional.
alter table public.dispositions drop constraint if exists dispositions_disposition_check;
alter table public.dispositions add constraint dispositions_disposition_check
  check (disposition in ('escalated','closed_benign','insufficient_evidence','collection_failed','supported','contradicted','out_of_scope'));
alter table public.dispositions alter column contract_sha256 drop not null;
alter table public.dispositions add column if not exists claim_ref text;
