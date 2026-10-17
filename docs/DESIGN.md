# Casefile: Technical Design

Status: draft v0.1. Implements `SPEC.md`. Interfaces below are the contract the tests in `tests/` are written against.

## 1. Architecture

```
 one-line goal + alert
        |
        v
 +-------------+  contract (frozen, v1)   +--------------------+
 |  Planner    |------------------------->|  Contract store    |
 | (model)     |  get_policy only         +---------+----------+
 +-------------+                                    |
        ^ re-plan (targeted)                        v
        |                               +--------------------+   tool calls   +-----------+
 +-------------+   failures + trace     |   Investigator     |--------------->| ToolBox   |
 | Attributor  |<-----------------------|   (model, ReAct)   |<---------------| (code)    |
 | (model)     |                        |   read-only tools  |  EvidenceRecord| + faults  |
 +-------------+                        +---------+----------+                +-----------+
        ^                                         | claims + recommendation        |
        |                                         v                                |
        |                               +--------------------+   LoopGuard watches |
        +-------------------------------|   Verifier (code)  |<--------------------+
            on failed check             |   7 checks         |
                                        +---------+----------+
                                                  | pre_commit passed
                                                  v
                                        +--------------------+
                                        |   Gate (code)      |  only writer, idempotent
                                        +---------+----------+
                                                  | receipt
                                                  v
                                        Verifier post_commit (result_persisted) -> DONE(outcome)
```

Three model roles (Planner, Investigator, Verifier-for-contradictions-only) plus the Attributor. Lookups, arithmetic, checks, the Gate and the guard are code. Every model call goes through one Crusoe adapter that logs to the trace.

## 2. Run state machine

```
PLAN -> INVESTIGATE -> VERIFY(pre) --pass--> COMMIT -> VERIFY(post) --pass--> DONE
            ^               |fail                                  |fail
            |               v                                      v
            +-- REPLAN <- ATTRIBUTE                          COMMIT_RETRY (same key)
                  |
                  v (guard says STOP)
          FINALIZE_WITHOUT_CLOSURE -> collection_failed | insufficient_evidence
```

Transitions
- `VERIFY(pre)` runs six checks (all but `result_persisted`). Pass leads to the Gate.
- Fail leads to the Attributor, which returns `(agent, step, category)`; the run re-plans only that step. A specification failure (wrong or missing check in the contract) is the only case that creates a new contract version.
- `LoopGuard` is consulted on every tool call and every re-plan. `FORCE_REPLAN` means the Investigator must change its plan. `STOP` finalizes without closure.
- Finalization without closure: `collection_failed` if a required source's last status is `error`; `insufficient_evidence` if sources responded but evidence is `empty`, `partial`, `stale` or has unresolved contradictions.
- `VERIFY(post)` checks `result_persisted` against the Gate receipt.

## 3. Package layout

```
src/
  crusoe_client.py          existing: OpenAI-compatible client, 429/503 backoff, cache accounting
  casefile/
    models.py               Outcome, EvidenceStatus, EvidenceRecord, Claim, NumericClaim, Recommendation, Contradiction, Case
    policy.py               Policy (versioned), decide(features) -> Outcome, required_sources, mandatory_checks
    contract.py             CHECKS, MANDATORY_CHECKS, build_contract(), Contract.revise(), UnknownCheckError, ContractViolation
    features.py             compute_sequence_features(), detect_contradictions(), IncompleteEvidence
    tools.py                ToolBox (resolve_account, get_device_history, get_transactions, compute_sequence_features), FaultPlan
    verifier.py             verify(), VerificationResult, Failure
    loop_guard.py           LoopGuard, GuardDecision
    gate.py                 Gate, Receipt, GateRefused, WriteInterrupted
    attribution.py          Attribution, Category, score_attribution(), attribution_accuracy()
    cost.py                 Price, CostLedger
    metrics.py              false_completion_rate(), cost_per_correct_case(), unnecessary_escalation_rate(), percentile()
    oracle.py               ground-truth labels + independent oracle (NEVER imported by agents/)
    trace.py                JSONL trace writer; step ids s001, s002, ...
    config.py               role -> model id, resolved against /v1/models; price table with `verified` flag
    agents/
      planner.py            PLANNER_TOOLS = {"get_policy"}
      investigator.py       INVESTIGATOR_TOOLS = 4 read tools
      attributor.py         trace -> Attribution
      critic.py             baseline-only LLM critic (never a gate)
    bench/
      cases.py              seeded synthetic case generator (dev / held-out)
      runner.py             three configurations x model-assignment arms
      report.py             results.json -> static report.html
data/cases/                 generated synthetic cases (dev/, heldout/)
labels/                     oracle labels, outside src/, not importable
tests/
runs/                       trace + results (gitignored)
```

## 4. Data model (pydantic v2, frozen unless noted)

- `Outcome`: `collection_failed | closed_benign | escalated | insufficient_evidence`. Closure outcomes: the latter two of `closed_benign`, `escalated`.
- `EvidenceStatus`: `ok | error | empty | partial | stale`.
- `EvidenceRecord(id, source, account_id, tenant_id, status, covers_from, covers_to, retrieved_at, data: dict, error: str | None)`.
- `NumericClaim(metric, value)` with metrics `largest_transfer | test_charge_count | transaction_count`, recomputed by code.
- `Claim(id, text, evidence_ids, numeric: NumericClaim | None)`.
- `Recommendation(outcome, claims)`.
- `Contradiction(id, evidence_ids, resolution: "resolved" | "escalated" | None)`.
- `Contract(version, case_id, account_id, tenant_id, window_start, window_end, required_sources, checks)`; `revise(**changes)` returns a new contract with `version + 1` and re-validates the mandatory set.
- `Attribution(agent: planner|investigator|verifier|gate, step: str, category: specification|inter_agent_misalignment|task_verification)`.

## 5. Component specifications

### 5.1 Contract (`contract.py`)
- `CHECKS = {correct_account, required_evidence, window_covered, claims_supported, policy_followed, contradictions_addressed, result_persisted}` is the allowlist.
- `MANDATORY_CHECKS = {correct_account, required_evidence, claims_supported, policy_followed, result_persisted}`.
- `build_contract(*, case_id, account_id, tenant_id, window_start, window_end, planner_checks, policy, planner_sources=())`: rejects unknown checks (`UnknownCheckError`), unions mandatory checks and `policy.required_sources`, freezes.
- `revise()` may add checks or sources; removing a mandatory check or required source raises `ContractViolation`.

### 5.2 Verifier (`verifier.py`)
`verify(*, contract, policy, evidence, recommendation, contradictions=(), receipt=None, phase="pre_commit") -> VerificationResult(passed, failures)`

| Check | Rule |
| --- | --- |
| correct_account | every record's `account_id` and `tenant_id` equal the contract's |
| required_evidence | for each required source, at least one record with status `ok`; otherwise failure reason `"<source> status=<status>"` |
| window_covered | union of `ok` records' coverage spans `[window_start, window_end]` |
| claims_supported | each claim cites existing evidence; every cited record is `ok`; numeric claims recompute within 0.01 |
| policy_followed | `recommendation.outcome == policy.decide(features(evidence))`; requires every required source `ok`, else this check also fails with the same reason |
| contradictions_addressed | every contradiction has a resolution |
| result_persisted | (`post_commit` only) receipt exists, has an idempotency key, outcome equals the recommendation |

`Failure(check, reason, evidence_ids)`. Evidence `data` text is never interpreted, so injected instructions in evidence cannot change a status or a check.

### 5.3 Gate (`gate.py`)
`Gate(fail_next_write=False)`; `commit_disposition(*, verification, case_id, outcome, contract_version, idempotency_key) -> Receipt`.
- Outcome must be an `Outcome` member, else `GateRefused` (this is the allowlisted-action rule: nothing changes money).
- `closed_benign` and `escalated` require `verification.passed`; the other two outcomes make no completion claim and are allowed.
- Same `idempotency_key` returns the original receipt and does not write again.
- `fail_next_write=True` raises `WriteInterrupted` once before recording; the retry with the same key writes exactly once.

### 5.4 Loop guard (`loop_guard.py`)
`LoopGuard(max_replans=2, max_tool_calls, deadline_s, clock=time.monotonic)`
- `record_tool_call(tool, args, new_evidence_ids) -> GuardDecision`: key is `(tool, canonical-json(args))`, canonicalized so dict order does not matter.
  - tool-call ceiling exceeded or deadline passed: `STOP`.
  - seen before and no new evidence ids: `FORCE_REPLAN`.
  - otherwise `CONTINUE`.
- `record_replan() -> GuardDecision`: `CONTINUE` for the first two, `STOP` on the third.

### 5.5 Tools and faults (`tools.py`)
- `resolve_account(email) -> account_id`.
- `get_device_history(account_id)` and `get_transactions(account_id)` return `EvidenceRecord`. Passing anything that is not an account id (for example an email) returns a record with status `error` and an error message naming `account_id`. This models the production failure.
- `FaultPlan(device_history=None|"error"|"empty"|"stale"|"partial", transactions=..., contradictory_timestamps=False)` forces statuses or injects a conflicting record. The wrong-identifier fault needs no plan: the real tool rejects the email.
- `compute_sequence_features(evidence) -> Features` raises `IncompleteEvidence` if a required source is not `ok`. Missing data is never converted into "no signals".

### 5.6 Features and policy
`Features(new_device_foreign, mfa_reset_after_new_device, test_charge_count, new_beneficiary, largest_transfer, payroll_seen)`. Test charge: charge with amount at most 2.00. `Policy.decide`: `escalated` if `new_device_foreign and mfa_reset_after_new_device and new_beneficiary and largest_transfer >= transfer_threshold` (1,000); else `closed_benign`. Policy is versioned (`version="p1"`) and not editable by any agent.

### 5.7 Attribution (`attribution.py`)
- Closed schema; free text or unknown agent names fail validation, the attempt is logged and counts as wrong.
- `score_attribution(pred, truth)` is true only if `agent == agent and step == step` (string equality, never substring).
- `attribution_accuracy(preds, truths)` raises on empty input or length mismatch.
- Attributor escalates from Lightning to the larger model when its output fails validation or it reports low confidence.

### 5.8 Cost and metrics
- `CostLedger(prices)`; `record(model, input_tokens, cached_tokens, output_tokens)`. Cost = `(input - cached) * in + cached * cached_rate + output * out`, per 1M tokens. Unknown model raises. Crusoe reports `prompt_tokens` including cached tokens, so cached is a subset.
- Metrics functions implement SPEC section 6 exactly.

### 5.9 Isolation
- `oracle.py` and `labels/` are not imported anywhere under `casefile/agents/`. A test scans imports with `ast`.
- Tool allowlists are constants, asserted in tests: Planner `{get_policy}`; Investigator `{resolve_account, get_device_history, get_transactions, compute_sequence_features}`. `commit_disposition` appears in neither.

## 6. Crusoe adapter and model assignment

- One `Crusoe` client (`src/crusoe_client.py`). Base URL `https://api.inference.crusoecloud.com/v1`. Backoff on 429/503. Usage and cached tokens recorded per call.
- `config.py` maps roles to model IDs and resolves them against `GET /v1/models` at startup. IDs are case-sensitive; mismatch is reported, not guessed. Defaults (from the hackathon skill file, to confirm): Investigator `nvidia/nemotron-3.5-lightning-30b-a3b`, comparison `nvidia/Nemotron-3-Nano-30B-A3B`, ceiling `nvidia/Nemotron-3-Super-120B-A12B`. Planner/contradiction role is "3.5 Super VL" per the brief; its ID is **unverified**, so the fallback is the Super 120B ID.
- Capability gates read from `/v1/models` `supported_parameters`: `tools` (else JSON action protocol), `response_format` (else JSON in prompt + validate + one retry), thinking toggles per model (never assumed).
- Prompt layout for prefix caching: `[system][policy][contract][tool schemas]` byte-identical and first; evidence and turns appended; the changing part is last. Hit rate = `sum(cached_tokens) / sum(prompt_tokens)`, reported per config.
- Reasoning models: `max_tokens >= 1024`; `finish_reason == "length"` raises `ModelBudgetError` and is retried once with double budget, then recorded as a failed step.
- Model-assignment arms (benchmark): (1) Lightning everywhere, (2) Super 120B everywhere, (3) cascade, (4) cascade with Nano in place of Lightning.

## 7. Benchmark design
- Same cases, tools, models and budgets across: single investigator; investigator + LLM critic; Casefile.
- Case set: 2 scenarios x 6 conditions (no fault, wrong identifier, missing device evidence, stale records, contradictory timestamps, interrupted final write). Seeded variation changes amounts, countries, timestamps. 12 dev, 12 held-out (proposal, SPEC A7).
- Oracle (`oracle.py`) computes expected outcome and whether a claimed completion is actually complete; labels are read only by the runner after a run finishes.
- Report per config and per arm: all SPEC section 6 metrics. Do not script the baseline to fail; if it handles a case, report it.
- Rate budget: see SPEC A5. The runner enforces per-model RPM from response headers (`x-ratelimit-remaining-requests`) and a spend ceiling.

## 8. Safety and guardrails
- Prompt injection: evidence text reaches only the Investigator (read-only tools). Planner receives typed features. Verifier and Gate never interpret free text.
- No PII: all data synthetic. Stretch inputs (screenshots, calls) are treated as untrusted evidence like any tool result.
- Secrets: `.env.local` loader, never logged. Traces redact the Authorization header and any env values.
- Fail closed: any exception in verification or the Gate means no closure.

## 9. Observability
JSONL trace per run: `{run_id, step_id, role, model, input_tokens, cached_tokens, output_tokens, latency_ms, retries, cost_usd, status, tool, args_hash}` plus evidence ids produced. Step ids (`s001`...) are what the Attributor cites. `report.py` renders a timeline, the checklist and the results table from the trace and `results.json`.

## 10. Build order (maps to the brief's timeboxes)
| Block | Build, test-first |
| --- | --- |
| Hour 1 | `models`, `policy`, `features`, `tools`, synthetic A-104/A-105, `config` + live `/v1/models` check |
| Hours 2-3 | `contract`, `verifier`, `gate`, `loop_guard`; Planner, Investigator; re-plan loop |
| Hour 4 | `attribution`, fault injection, three configurations |
| Hour 5 | `cost`, `metrics`, runner, report; model-assignment arms |
| Final hour | held-out run once, README, demo recording; no new features |

Fallback (from the brief): if the investigation loop is not working by hour 3, switch to Ledgerproof (reconciliation), reusing `contract`, `verifier`, `gate`, `loop_guard`.

## 11. Risks
| Risk | Mitigation |
| --- | --- |
| Model IDs or capabilities differ from the brief | Startup resolution against `/v1/models`; fallbacks in section 6 |
| 30 RPM per model throttles the benchmark | Payment method; RPM-aware runner; smaller dev set |
| Reasoning models return empty content | Token headroom; `finish_reason` check |
| Baseline succeeds on the showcase case | Report honestly; the fault set carries the comparison |
| Scope creep into stretch goals | Stretch only after the benchmark has run |
