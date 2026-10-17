# Handoff: company-financial claims through `you-finance` (for the Claude session that has the You.com finance MCP)

Written Oct 17 2026 by the Claude Code session that built Casefile's core. Repo: `.`
(venv `.venv`; tests `.venv/bin/python -m pytest -q`; live Crusoe tests `-m live`). Read `CLAUDE.md` and `docs/RECORDS_SPEC.md` first.

## Paste this into the other session
```
You are taking over one workstream in . (Casefile, Crusoe hackathon). Read docs/YOUCOM_FINANCE_HANDOFF_FOR_CLAUDE.md,
CLAUDE.md, docs/RECORDS_SPEC.md and src/casefile/records/evidence_routing.py. Your job: add company-financial claims (earnings, stock/market data, company
financials) to the records mode, answered ONLY through the you-finance MCP tools you have connected. Work tests-first. Do not use any other finance source.
Start by listing the you-finance tools and their exact input/output schema, run 2-3 small real queries on a large public issuer, and save redacted real
responses as fixtures. Then follow the plan and file boundaries in the handoff doc. Report back with the tool schema, what worked, what failed, and the test count.
```

## What already exists (do not rebuild)
| Piece | Where | Notes |
| --- | --- | --- |
| Records pipeline | `src/casefile/records/` | intake (Super VL) -> attributed claims -> investigator (Lightning, read-only tools) -> **code verifier** -> gate -> pseudonymized report |
| Verifier | `records/verifier.py` | verbatim quotes, source adequacy, entity match, code-recomputed numbers, conflicts, neutral-language lint. Pass/fail is code, never a model |
| Retrieval interface | `records/sources.py` | `EvidenceSource.search/fetch`; `FixtureSource`; `YouComSource` (search then exact-URL contents; wrapper/invented URLs rejected) |
| Evidence routing | `records/evidence_routing.py` | **Fail-closed:** issuer identity via finance is `lead_only` (verify the legal entity in SEC EDGAR); issuer financials and market data via `you-finance` need a **verified ticker or CIK**, otherwise `not_eligible`; contracts, grants, campaign finance, registrations, court, rules go to search+contents, never finance |
| Schemas | `src/casefile/schemas.py` | strict JSON schemas for every agent; **enums are derived from `ClaimType`/`Verdict`, and `tests/harness/test_schemas.py` ties them together** |
| Crusoe models | `src/casefile/config.py` | Lightning = investigator; Super VL = intake/planner/escalation; prices from `/v1/models`; thinking off |
| Bench | `src/casefile/bench/records_*.py`, `scripts/run_records_bench.py` | synthetic fictional cases with an independent oracle |

## Your workstream: `company_financials` claims, `you-finance` only
Goal: a case file can contain statements like "Company X reported revenue of $N in FY2025" or "Company X's stock closed above $P on a date". Casefile verifies them
using only `you-finance` results, with quotes and code-recomputed arithmetic, and never states anything about anyone's conduct.

1. **Discover first (read-only).** List the `you-finance` tools; record tool names, parameters, and the response shape. Run a few small queries on a large well-known issuer.
   Save redacted real responses under `data/fixtures/finance/`. **Do not write code against a guessed schema.**
2. **Tests first** (`tests/records/test_finance_*.py`), covering at least:
   - a revenue/EPS/price claim is `supported` or `contradicted` from the tool's quoted text; the number is **recomputed in code** (growth %, ratios) with a stated tolerance;
   - an unverified or name-only issuer match **fails closed** (`insufficient_evidence`), per `evidence_routing.route_evidence`;
   - an as-of date or fiscal period is required for every value; a mismatched period is `contradicted`, a missing one is `insufficient_evidence`;
   - quotes are verbatim in the tool output (reuse the verifier's `_norm`/quote check);
   - two finance results that disagree must be listed in `conflicts`;
   - no wrongdoing vocabulary outside quotes (reuse `neutrality.lint`);
   - private companies and non-issuer entities: `insufficient_evidence`, never "private" as a conclusion (search absence is not evidence);
   - the you-finance tool is **never** used for procurement, grants, campaign finance, registrations, court or rules (routing must refuse).
3. **Implement.** New files preferred: `src/casefile/records/finance.py` (adapter over the MCP results to `Document`/`Finding` objects with URL, retrieved-at and sha256) and
   `tests/records/test_finance_*.py`. A `FinanceSource(EvidenceSource)` that only answers issuer-financial and market-data queries is the cleanest fit.
4. **Wire into the claim model** (shared files, coordinate): add `ClaimType.COMPANY_FINANCIALS` in `records/models.py`; add its check in `records/verifier.py::_expected`;
   the intake and records-step schemas pick the new enum up automatically, so keep `tests/harness/test_schemas.py` green and extend `records/agents/intake.py`'s prompt with the new params
   (`entity_canonical`, `ticker_or_cik`, `metric`, `period`, `claimed_value`, `comparison`).
5. **Live check:** one end-to-end run through Crusoe (`scripts/run_casefile.py`) on a small case file with one finance claim, using the real MCP. Report cost and the Crusoe calls.

## File ownership (to avoid collisions; two other agents also edit this repo)
- **You may create/edit:** `src/casefile/records/finance*.py`, `tests/records/test_finance_*.py`, `data/fixtures/finance/**`, `data/casefiles/finance_example.md`, and `docs/YOUCOM_FINANCE_*.md`.
- **Shared, small edits only, run the full suite before and after:** `records/models.py` (enum), `records/verifier.py` (`_expected` branch), `records/agents/intake.py` (prompt text).
- **Do not edit:** `src/casefile/harness/**`, `src/casefile/gate_mcp/**`, `src/casefile/orchestrator.py`, `src/casefile/bench/**`, `scripts/run_bench.py`, `scripts/run_records_bench.py`, `runs/**`, `labels*/`.
- **Do not change** the behavior of existing claim types: a records benchmark is running on the current code, and a held-out run will happen once after a freeze. If a finance change must touch existing behavior, stop and say so.
- Another agent (Codex) owns `youcom.py`, `records/sources.py` (`YouComSource`), `records/evidence_routing.py` and the Supabase layer. Read them; ask before changing them.

## Rules that must hold
- Crusoe models only for generation; `you-finance` is for **evidence retrieval**, not for answers. Do not let You.com's synthesized text decide a verdict; quote tool output and let code compare.
- Output stays pseudonymized by default and says "Not a legal finding." Real issuer names appear only inside quoted source text.
- No keys or tokens in files, chat or logs. The router masks PII on the wire.
- Report numbers only from real runs. Say what was not run.

## Hand back
Tool names and schema, saved fixtures list, tests added and the new total, any claim types you could not support and why, rate limits or credit cost seen, and the exact files you changed.

---

# What the core session does next (not for you)
1. Finish the records dev benchmark (running), read the results, and report them with caveats.
2. Fix whatever the benchmark exposes, then **freeze** and run the held-out split once.
3. **N+1:** group verifier failures by (check, agent); a Super VL "improver" proposes **one** prompt edit for the worst group; evaluate on a new **validation split** (not dev, which is tuned, and not held-out);
   keep the edit only if the score rises with no regressions and a different approver signs it (`harness/memory.py::ProceduralMemory`). The policy and the check list are never editable.
4. Optional: wire run traces into the Supabase tables (`cases`, `runs`, `evidence`, ... currently empty) and run the model sweep (Nano, Super 120B).
5. Update the pitch numbers in `docs/PITCH_PROMPTS.md` from `results.json` only.
