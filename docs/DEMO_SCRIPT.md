# Casefile Demo Script

Target length: **3:30–4:00**

Primary story: **Casefile verifies whether an investigation is actually complete before it allows a conclusion.**

Closing line: **“An agent that cannot prove it is done does not get to say it is done.”**

## Investigation Console

`frontend/` is a static console that replays the real persisted runs (claims, the You.com grounding trail, verifier rejections, Supabase counts, the N versus N+1 result). It is labelled a recorded run. Rebuild its data with `python frontend/build_data.py` and open `frontend/index.html` or deploy it as a static site.

## Before recording

Prepare these windows in advance:

1. The Casefile architecture diagram or the Mermaid diagram in `README.md`.
2. `data/casefiles/public_integrity/fat_leonard.md`.
3. `runs/casefile-20261017-143419/report.md`.
4. `runs/casefile-20261017-143419/retrieval_audit.json`.
5. A terminal in the repository root with the virtual environment ready.
6. The Supabase dashboard opened to the most recent synthetic case, if available.
7. `runs/dev-20261017-143607/report.html` for the measured development comparison.

Do not display `.env.local`, `.env.youcom`, API keys, service-role keys, Authorization headers, or hidden model reasoning.

Use a large terminal font and close unrelated tabs. Run the longer public-record retrieval before recording so the demo does not depend on network speed. The transaction and memory demonstrations can be run live.

## Scene 1 — Hook and problem (0:00–0:25)

### On screen

Show the title and the line:

> An agent that cannot prove it is done does not get to say it is done.

Then briefly show the Fat Leonard case file.

### Narration

> Investigations fail when an agent produces a fluent answer before it has complete evidence. A source may fail, a citation may point to a search page, or a document may concern the wrong entity. An LLM critic can still agree with the answer. Casefile changes the unit of success: the agent must prove that every required check is complete before the system allows a conclusion.

## Scene 2 — Two modes, one governed architecture (0:25–0:55)

### On screen

Show the architecture diagram. Highlight the two inputs, then follow the shared path through Investigator, Verifier, Gate, Supabase, and N+1 memory.

### Narration

> Casefile has two modes. Records Mode verifies claims from hearings, audits, indictments, and investigative reports. Transaction Mode investigates synthetic account-takeover alerts. NVIDIA Nemotron models on Crusoe plan and investigate, but plain code freezes the definition of done, verifies the evidence, limits recursion, and owns the final disposition.

> Super VL handles planning and records intake. Lightning performs evidence investigation and first-pass failure attribution. Every generative call goes through Crusoe Managed Inference.

## Scene 3 — Public-records case input (0:55–1:15)

### On screen

Open:

`data/casefiles/public_integrity/fat_leonard.md`

Point to:

- attributed statements;
- direct DOJ source URLs;
- checkable amounts or events; and
- the legal-conclusion claim.

### Narration

> This input contains attributed assertions, not pre-approved truth. Casefile splits the narrative into atomic claims. It can investigate checkable statements, but claims asking it to infer guilt or intent are marked out of scope rather than researched.

## Scene 4 — Exact-URL grounding with You.com (1:15–1:45)

### On screen

Open:

`runs/casefile-20261017-143419/retrieval_audit.json`

Show accepted DOJ URLs, queries, and document metadata. If convenient, also show:

`docs/PUBLIC_INTEGRITY_URL_VALIDATION.md`

### Narration

> You.com Search discovers candidate sources. Code rejects search wrappers and malformed URLs. You.com Contents then extracts only the exact accepted URL. Search snippets are never treated as evidence, and a URL invented by a model cannot become a scrape target.

> A real URL is not automatically relevant. Casefile rejected one proposed DOJ OIG document because it was about the removal of U.S. Attorneys and did not substantiate the Cunningham claims.

## Scene 5 — Evidence-backed report (1:45–2:20)

### On screen

Open:

`runs/casefile-20261017-143419/report.md`

Highlight:

- the “Not a legal finding” notice;
- the supported claim and its verbatim DOJ quotes;
- the two insufficient-evidence verdicts; and
- the out-of-scope legal conclusion.

Optionally switch briefly to:

`runs/casefile-20261017-143605/report.md`

Show the Martin Kao amount claim that was contradicted after code recomputed the documented loan amounts.

### Narration

> The report is claim-by-claim and pseudonymized by default. A supported or contradicted verdict requires verbatim evidence, adequate sources, an entity match, correct recomputation, addressed conflicts, and neutral language.

> Notice the conservative behavior: two claims remain insufficient because the retrieved record does not settle them. The legal conclusion is out of scope. In the Navatek example, Casefile contradicted a thirteen-million-dollar amount after recomputing three documented loan values to roughly fifteen-point-seven million.

## Scene 6 — Recursive repair and deterministic closure (2:20–2:55)

### On screen

Run:

```bash
.venv/bin/python scripts/demo.py A-105 wrong_identifier
```

Use **A-105**, not A-104, for the live refusal: in a recorded rehearsal both the critic arm and Casefile escalated A-104 correctly (the investigator fixed its own identifier from the tool's error message), whereas A-105 shows the verifier refusing a closure on errored evidence, two attributions, and a repaired `closed_benign`. Do not claim the critic arm failed A-104.

Highlight the failed tool call, verifier failure, attribution, targeted replan, and final disposition. If the live model run is too slow, show the prepared development report instead:

`runs/dev-20261017-143607/report.html`

### Narration

> Here the investigator passes an email to a tool that requires an account ID. A conventional flow can misread the resulting absence as benign. Casefile’s verifier detects the missing evidence. The failure attributor identifies the broken step, the LoopGuard permits a bounded repair, and only the Gate can write the final disposition.

> In the recorded development comparison, Casefile reached one hundred percent correct disposition with zero false completions. Those are development numbers, not held-out results.

## Scene 7 — Durable audit in Supabase (2:55–3:15)

### On screen

In Supabase, show one synthetic case and its linked rows:

- `cases`;
- `evidence`;
- `claims`;
- `check_results`;
- `events`;
- `audit_log` (verify the hash chain with `python scripts/audit_verify.py --run <run uuid>`); and
- `dispositions`.

If the dashboard is not ready, show the schema diagram or `supabase/migrations/` and a prepared query result.

### Narration

> Supabase preserves the frozen contract, evidence receipts, claims, deterministic checks, events, audit chain, and idempotent disposition. You.com grounding documents are versioned by URL and content hash. The result is reproducible evidence, not just a chat transcript.

## Scene 8 — Governed Version N+1 (3:15–3:40)

### On screen

Run:

```bash
.venv/bin/python scripts/memory_certification_demo.py
```

Highlight these true results:

- `working_discarded_on_completion`;
- `episode_closed_and_immutable`;
- `unreviewed_fact_hidden`;
- `semantic_self_certification_blocked`;
- `procedural_self_approval_blocked`;
- `procedural_no_gain_blocked`; and
- `certified_workflow_retrieved`.

### Narration

> Completed runs become immutable episodic memory. The N+1 loop is designed to cluster deterministic verifier failures and propose one bounded playbook improvement. A procedure cannot certify itself, cannot ship without a measured gain, and cannot change policy, verifier checks, tool permissions, or the Gate.

> The certification controls are working today. Automatic failure clustering and the paired N versus N+1 held-out evaluation are the remaining integration step, so we do not claim an unmeasured N+1 improvement.

Measured N+1 experiment (synthetic mule-ring data, `scripts/n_plus_1_demo.py`, shown in the console): the improver drafted a playbook from the audited failures of N, the paired comparison on 10 validation cases gave N 7/10 correct with 3 false completions and N+1 7/10 correct with 0 false completions, and the promotion gate **rejected** N+1 because correct dispositions did not strictly improve (it answered `insufficient_evidence` on cases N got right). Present this as the gate working, not as an improvement. The held-out split has not been run.

## Scene 9 — Close (3:40–3:55)

### On screen

Return to the architecture or title card. Show the partner stack:

- Crusoe Managed Inference;
- NVIDIA Nemotron;
- You.com;
- Supabase; and
- deterministic Python verification.

### Narration

> Casefile combines Nemotron reasoning, exact-URL web grounding, deterministic verification, durable evidence, and independently certified memory. The goal is not to make an agent sound more certain. It is to make completion auditable.

> An agent that cannot prove it is done does not get to say it is done.

## Commands to prepare the recording

Run offline tests:

```bash
.venv/bin/python -m pytest -q
```

Confirm Crusoe model access:

```bash
.venv/bin/python scripts/check_models.py
```

Optionally create a fresh live records artifact before recording:

```bash
.venv/bin/python scripts/run_casefile.py \
  data/casefiles/public_integrity/fat_leonard.md \
  --youcom \
  --include-domain justice.gov
```

Create a fresh enterprise-controls artifact:

```bash
.venv/bin/python scripts/enterprise_demo.py
```

Create a fresh memory-certification artifact:

```bash
.venv/bin/python scripts/memory_certification_demo.py
```

## Recording asset checklist

- [ ] Title card with the closing line
- [ ] Architecture diagram
- [ ] One public-integrity case input
- [ ] Exact-URL retrieval audit
- [ ] Pseudonymized report with one supported/contradicted result and one refusal
- [ ] Recursive transaction repair
- [ ] Supabase linked evidence and disposition
- [ ] N+1 memory certification output
- [ ] Development benchmark table with the “not held-out” label visible
- [ ] Final partner-stack and responsible-use slide

## Claims not to make

Do not say that:

- every allegation in an input case is true;
- Casefile determines guilt, fraud, corruption, intent, or legal liability;
- You.com Finance proves misconduct;
- the development benchmark is held out;
- N+1 improved performance until the paired evaluation produces that result;
- Supabase constitutes production authentication;
- the system uses real customer banking data; or
- the system is a replacement for an investigator, auditor, regulator, or court.

## Optional 60-second cut

If a short social/demo cut is needed:

1. **0:00–0:08:** hook and false-completion problem.
2. **0:08–0:20:** architecture—models investigate, code verifies.
3. **0:20–0:38:** exact-URL audit and evidence-backed Fat Leonard report.
4. **0:38–0:50:** recursive repair and zero false completion development result.
5. **0:50–0:57:** certified N+1 memory controls.
6. **0:57–1:00:** closing line.
