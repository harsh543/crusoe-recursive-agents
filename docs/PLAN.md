# Casefile — Project Plan and Agentic Architecture

Track: **Done Means Done** (lead). Stretch: **Version N+1**. Shared Brain comes for free from the Supabase case memory but is not pitched.

One line: *Casefile investigates a suspicious-account alert, writes its own definition of done, refuses to close a case until code-run checks pass, names the agent and step that broke, and repairs only that step — all on Nemotron on Crusoe.*

Source brief: `~/Downloads/Casefile — Project Brief (Recursive Agents Hackathon).md`. Crusoe facts: the hackathon skill file (crusoe-developer-hub, refreshed Oct 13 2026) and `CLAUDE.md`.

---

## 1. The use case, sharpened

| | |
|---|---|
| **User** | Fraud analyst working an alert queue at a bank/fintech |
| **Job** | Decide each alert: `escalate`, `close_benign`, or `insufficient_evidence` — with cited evidence |
| **Failure we kill** | *False completion*: a tool errors, the agent reads "no data" as "nothing suspicious", writes a fluent "benign" memo, an LLM critic approves it |
| **Why agents** | Evidence lives in several systems, lookups fail in boring ways (wrong ID type, stale data, partial pages), and the plan must adapt when they do |
| **Why "walk away"** | The analyst only sees escalations and insufficient-evidence cases. Everything else closes itself — *only if it can prove it's done* |

Showcase pair (synthetic): **A-104** account takeover → escalate; **A-105** benign lookalike (new phone, same country, payroll, first rent) → close benign. A-105 stops "escalate everything" from scoring well.

### What "done" means here (the thing judges grade)
A case is done only when **every check in its frozen contract passes in code**. A model can *propose* a disposition; only the Gate can *commit* one, and the Gate only reads check results.

---

## 2. Pattern map: Andrew Ng's four + the Educative catalog

Ng's four agentic patterns (DeepLearning.AI, *The Batch*, 2024) and the extended workflow patterns taught in Educative's agentic-design-patterns material (prompt chaining, routing, parallelization, orchestrator-workers, evaluator-optimizer, human-in-the-loop, memory). *Assumption:* "eduive io" = Educative.io; tell me if you meant another source.

| Pattern | Where it lives in Casefile | What makes our version different (the judge hook) |
|---|---|---|
| **Planning** (Ng) | Planner turns `"investigate alert A-104"` into a typed **completion contract** | Plan-then-execute: contract is schema-constrained, policy injects mandatory checks the Planner can't remove, then it's **frozen** (hash stored). Re-plans may change *steps*, never *checks* |
| **Tool Use** (Ng) | Investigator ReAct loop over 4 read-only tools | Tools return a typed envelope `{status: ok\|error\|empty\|partial, ...}` so "error" can never be read as "nothing found" |
| **Reflection** (Ng) | Verifier | **Reflection with external feedback**: code checks first, LLM only for contradictions. Feedback is actionable (`device_history.status=error`), never "think harder" |
| **Multi-agent collaboration** (Ng) | Planner / Investigator / Verifier / Attributor + code Gate | Only 3 model roles + attributor; each must earn its place in the benchmark (MAST: most multi-agent failures are spec/coordination/verification) |
| **Orchestrator–workers** | A **code** state machine is the orchestrator; models are workers | No LLM decides control flow → loops and drift are caught deterministically |
| **Evaluator–optimizer** | Verify → Attribute → targeted re-plan → re-investigate | Bounded: ≤2 re-plans, tool-call ceiling, deadline |
| **Routing** | Model cascade: Lightning by default, escalate to Super only on hard calls (low confidence / contradiction) | Measured: cost per *correct* case, not per call |
| **Parallelization** | Evidence fetches with no dependency run concurrently (transactions ∥ devices once account is resolved) | Spreads RPM across models (limits are per model) |
| **Prompt chaining** | `resolve_account` → features → claims → disposition draft | Each link validated by schema before the next |
| **Human-in-the-loop** | Only `escalate` / `insufficient_evidence` reach a human | Stretch: VoiceChat callback whose answer becomes *evidence*, not a decision |
| **Memory** | Supabase: case dossier, evidence receipts, append-only trace | Doubles as the Shared Brain story and the N+1 training signal |
| **Guardrails / Dual-LLM** | Investigator reads untrusted text but has no write tools; Gate is the only writer | Prompt-injection in a memo field can't move money or close a case |

---

## 3. Architecture

```
                 ┌──────────────── Supabase (case memory + trace) ────────────────┐
                 │ cases · contracts(frozen) · evidence · claims · checks · events │
                 │ playbooks(versioned) · runs · oracle.labels (agents can't read) │
                 └───────▲───────────▲───────────▲───────────▲───────────▲─────────┘
                         │           │           │           │           │
 alert ──► ORCHESTRATOR (Python state machine, no LLM) ─────────────────────────────
            │
            ├─1─► PLANNER  (Nemotron Super*)      goal → contract JSON  → policy merge → FREEZE (sha256)
            │
            ├─2─► INVESTIGATOR (Lightning, ReAct) tools: resolve_account · get_device_history
            │        │                                   get_transactions · compute_sequence_features
            │        └─► evidence receipts {source, args, status, rows, fetched_at} + claims[cites]
            │
            ├─3─► VERIFIER  (code; Super* only for contradictions)
            │        all checks pass ──────────────► 5. GATE (code) commit_disposition(idempotency_key)
            │        any check fails ─┐
            │                         ▼
            ├─4─► ATTRIBUTOR (Lightning → Super* if unsure)  "agent=investigator step=7 type=wrong_identifier"
            │        └─► REPLAN (Planner, steps only) → back to 2, only the blamed step
            │
            └── LOOP GUARD (code): same tool+args+no new evidence → force replan; ≤2 replans;
                 tool-call ceiling; deadline → outcome = insufficient_evidence (never "benign")
```

\* Super = `Nemotron 3.5 Super VL` if `/v1/models` lists it with `tools` + `response_format`; otherwise `nvidia/Nemotron-3-Super-120B-A12B`. **The Oct 13 skill file catalog does not list "3.5 Super VL"** — it came from a console snapshot. Confirm before wiring.

### State machine (the orchestrator)

```
INTAKE → PLAN → FREEZE → INVESTIGATE → VERIFY ─pass→ GATE → DONE(escalate|close_benign)
                              ▲            └fail→ ATTRIBUTE → REPLAN ─(replans<2)→ INVESTIGATE
                              │                                      └(budget out)→ DONE(insufficient_evidence)
                              └──────────── loop guard trips ──────────┘
```
Every transition writes one row to `events` (that row stream *is* the demo timeline via Supabase Realtime).

### Completion contract (what the Planner emits, schema-constrained)

```json
{
  "case_id": "A-104", "contract_version": 1,
  "window": {"start": "2026-09-01T00:00:00Z", "end": "2026-10-16T23:59:59Z"},
  "required_sources": ["devices", "transactions", "auth_events"],
  "checks": [
    {"id": "correct_account",      "origin": "policy"},
    {"id": "required_evidence_ok", "origin": "policy"},
    {"id": "window_covered",       "origin": "policy"},
    {"id": "claims_supported",     "origin": "policy"},
    {"id": "policy_rule_satisfied","origin": "policy", "rule": "ato_v3"},
    {"id": "contradictions_resolved","origin": "planner"},
    {"id": "result_persisted",     "origin": "policy"}
  ],
  "budget": {"max_replans": 2, "max_tool_calls": 20, "deadline_s": 180}
}
```
Check IDs come from an allowlist. Unknown IDs are rejected. Policy checks are re-added after the Planner even if it drops them. Freeze = store `sha256(canonical_json)`; Verifier refuses a contract whose hash changed.

### Tool envelope (the single most important design choice)

```json
{"tool": "get_device_history", "args": {"account_id": "acc_8812"},
 "status": "error", "error": "invalid account_id format: got email",
 "rows": [], "coverage": null, "fetched_at": "..."}
```
`required_evidence_ok` passes only if `status == "ok"` for every required source. `empty`, `error`, `partial` never count.

---

## 4. Models on Crusoe (Nemotron-only, per brief)

| Role | Model ID (verify with `scripts/check_models.py`) | Settings |
|---|---|---|
| Investigator, Attributor (default) | `nvidia/nemotron-3.5-lightning-30b-a3b` | tools on; `chat_template_kwargs.enable_thinking=false` for tool turns, `max_tokens ≥ 1024` |
| Planner, contradiction resolver, Attributor escalation | `Nemotron 3.5 Super VL` (ID TBD) → fallback `nvidia/Nemotron-3-Super-120B-A12B` | `response_format` JSON schema if supported; thinking on, `max_tokens ≥ 2048` |
| Comparison arm (small) | `nvidia/Nemotron-3-Nano-30B-A3B` (from docs table, confirm casing) | same as Lightning |
| Stretch: screenshot evidence | `nvidia/Nemotron-3-Nano-Omni-Reasoning-30B-A3B` | image via data URI |
| Stretch: voice callback | `nvidia/Nemotron-3-VoiceChat` | request format **undocumented** — ask Crusoe before committing time |

Operational rules (from the skill file):
- 30 RPM/model without a payment method → add one (600 RPM) before benchmark runs, or the 4-config × N-case sweep will stall.
- Keep system prompt + tool schemas byte-identical per role → prefix cache; log `cached_tokens` per call.
- Log per call: model, role, step, prompt/cached/completion tokens, latency, cost → `events`.
- `src/crusoe_client.py` `MODELS` still lists the DeepSeek/gpt-oss roles; switch to the Nemotron map once IDs are confirmed.

---

## 5. Supabase design

Schema draft: `supabase/migrations/0001_casefile.sql` (not applied yet).

| Table | Purpose | Who writes |
|---|---|---|
| `cases` | alert, account, tenant, status, final disposition | orchestrator, gate |
| `contracts` | versioned frozen contracts + hash | planner (via orchestrator) |
| `evidence` | one receipt per tool call (envelope above) | tools |
| `claims` | investigator claims with `cites evidence_id[]` | investigator |
| `check_results` | per check per attempt: pass/fail + actionable reason | verifier |
| `attributions` | agent, step, failure category, confidence | attributor |
| `events` | append-only trace, cost/latency per step; Realtime → UI | orchestrator |
| `runs` | benchmark run metadata (config, model map, case split) | eval harness |
| `playbooks` | versioned investigator/planner playbook text + eval scores (N+1) | improver |
| `oracle.labels` | ground-truth disposition + faulty step per case | humans only; **no grant to agent role** |

### Grounding memory (You.com → Supabase), `0002_grounding.sql`

Company and regulatory policy come in through **You.com** ([agent-skills](https://github.com/youdotcom-oss/agent-skills)), and every response is kept:

```
You.com search / contents ──► grounding_requests (every call, raw JSON, status, latency, purpose, case_id)
                          └─► grounding_docs     (one row per page version: url + sha256, markdown, trusted flag, FTS index)
                                   └─► policy_clauses (verbatim quote bound to an ato_v1 signal/check; code-verified substring)
Planner.get_policy ──► ato_v1 + its clauses, with doc ids it can cite
Agents' memory lookup ──► search_grounding(q) (Postgres full-text; no embedding model needed)
```

- **Runtime uses search + contents only.** Both are retrieval. You.com's Research endpoint runs its own LLM, which would break "Crusoe is the only model provider". So `YouCom.research()` refuses unless `allow_external_llm=True`, and that's meant for offline corpus work, only if the organizers OK it.
- **Trusted sources only for policy.** `trusted = true` only for allowlisted primary domains (fincen.gov, ecfr.gov, nist.gov, ffiec.gov, …). Clauses can bind only to trusted docs.
- **Untrusted text stays data.** Page text reaches prompts via `as_evidence()`, wrapped in `<external-content>`.
- **Freshness is free.** A page that changes gets a new `content_sha256` row, so "which version of the policy did we cite" is answerable.
- Build or refresh with `python scripts/build_policy_corpus.py`. The first run stored 20 trusted docs from 11 calls.

Agents talk to Supabase via the service key from the Python backend only; the UI uses the anon key with RLS read-only on `cases/events/check_results`. `oracle` schema is not exposed to the API.

---

## 6. Evaluation first (build this before the agents)

**Case set** (synthetic, JSON fixtures + seeded into Supabase): ~24 cases = 12 dev + 12 held-out, balanced escalate / benign / insufficient.

**Fault injection** (per case, toggled by the harness, not visible to agents):
1. wrong identifier (email instead of account ID)
2. missing device evidence (`status=error` / timeout)
3. stale records (`fetched_at` older than window)
4. contradictory timestamps (timezone shift)
5. interrupted final write (Gate retry must be idempotent)

**Configurations** (same cases, tools, budgets):
| Config | Description |
|---|---|
| C1 single | Investigator alone decides |
| C2 critic | Investigator + LLM critic approves/rejects |
| C3 Casefile | Contract + code Verifier + Attributor + targeted re-plan + Gate |

Model sweep on C3: Lightning-everywhere · Super-everywhere · cascade (Lightning + Super) · cascade with Nano.

**Metrics:** false-completion rate (headline) · correct disposition · recovery rate · unnecessary escalation · supported-claim rate · attribution exact-match (agent + step) · cost per correct case (failed attempts included) · p50/p95 latency.

Rule: don't script C1/C2 to fail. If they get A-104 right, report it; the fault set carries the comparison.

---

## 7. Version N+1 (stretch, only after the C1/C2/C3 table exists)

Loop that turns Attributor output into a better team, with a measured gate:

```
dev-set run ─► attributions grouped by (agent, failure_type)
            ─► Improver (Super) proposes ONE playbook edit for the worst bucket
               e.g. "Before any device lookup, call resolve_account and pass account_id"
            ─► re-run dev set with playbook v(n+1)
            ─► keep iff dev score ↑ AND held-out score ≥ v(n); else discard
            ─► playbooks row: version, diff, dev_score, heldout_score, kept
```
Hard rule: the **completion policy and check allowlist are not editable** by the improver — only the investigator/planner playbooks. That's what keeps N+1 from "improving" by lowering the bar. Demo: before/after on held-out cases, one kept edit and one rejected edit.

---

## 8. Build plan (Oct 17, 9:00 AM – 10:00 PM PDT; submission deadline unknown — ask organizers)

| Time | Deliverable | Owner (suggested) |
|---|---|---|
| 9:00–10:00 | Crusoe key in `.env.local`, `check_models.py` green, confirm Super VL ID + tool support; Supabase migration applied; fixtures for A-104/A-105 | All / **P1 infra** |
| 10:00–11:30 | Tools with envelopes + fault injector; eval harness skeleton with oracle; C1 single-agent baseline runs end to end | **P2 tools+eval** |
| 10:00–12:30 | Planner → contract → policy merge → freeze; orchestrator state machine; events logging | **P1 orchestrator** |
| 11:30–13:30 | Investigator ReAct (Lightning); code Verifier with all 7 checks; Gate | **P3 agents** |
| 13:30–15:00 | Attributor + targeted re-plan + loop guard; C2 critic config | P3 / P1 |
| 13:00–16:00 | UI: case timeline (Realtime on `events`), contract checklist, results table | **P4 UI** |
| 15:00–17:00 | Full case set (24), C1/C2/C3 runs, model sweep; fix what breaks | P2 |
| 17:00–19:00 | **Freeze features.** Stretch N+1 only if the results table is real | P3 |
| 19:00–21:00 | Held-out run, README, 60-s demo recording, pitch | All |
| 21:00–22:00 | Buffer / submit | All |

Fallback if the investigation loop isn't working by 13:30: Ledgerproof (reconciliation) reusing contract + verifier + gate.

### Repo layout to create
```
src/casefile/
  orchestrator.py   # state machine, loop guard, budgets
  contract.py       # schema, allowlist, policy merge, freeze/hash
  agents/planner.py investigator.py verifier.py attributor.py
  tools.py          # 4 read tools + envelope + fault injection hooks
  gate.py           # commit_disposition (idempotent)
  store.py          # Supabase client
eval/
  cases/*.json      # fixtures (+ oracle labels kept separately)
  run.py            # configs C1/C2/C3 × model maps → runs table
supabase/migrations/0001_casefile.sql
ui/                 # timeline + results (Next.js or a single Streamlit page)
```

---

## 9. Open questions (blocking or worth 5 minutes)

1. **Super VL exact ID, tool calling and `response_format` support** — from `/v1/models`.
2. Payment method on the Crusoe account (30 vs 600 RPM) — decides whether the sweep is feasible.
3. Submission deadline, judging rubric, pre-existing code rules — organizers (not published).
4. UI stack: Next.js on Vercel vs Streamlit. Recommend **Streamlit or a single Next.js page** — the UI is a viewer, not the product.
5. VoiceChat request format — ask Crusoe before betting on that stretch.

## Pitch line
*"An agent that can't prove it's done doesn't get to say it's done. Casefile proves it, finds the step that broke, and does it on the smallest model on Crusoe that can."*
