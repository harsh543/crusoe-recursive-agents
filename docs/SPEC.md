# Casefile: Product Specification

Status: draft v0.1, Oct 17 2026. Source: `Casefile — Project Brief (Recursive Agents Hackathon).md`.
Track: **Done Means Done** (lead). Shared Brain and Version N+1 are extensions, not requirements.
Companion docs: `DESIGN.md` (technical design), `TEST_PLAN.md` (test-first plan). Tests live in `tests/`.

## 1. Purpose
Casefile investigates suspicious account activity, finds missing evidence, repairs its own investigation, and **cannot close a case until executable checks pass**. Every agent call runs on NVIDIA Nemotron via Crusoe Managed Inference, using the cheapest model that can do the step.

Problem: *false completion*. A lookup fails, the agent reads "no data" as "nothing suspicious", closes the case as benign, and an LLM critic approves because the write-up reads well.

## 2. Goals, non-goals
Goals
- G1. A completion contract the agent cannot weaken, enforced by code, that a well-written wrong answer cannot pass.
- G2. Measured recovery from injected tool faults without a human.
- G3. Failure attribution: name the agent and step that broke before re-planning, and re-plan only that step.
- G4. A benchmark comparing three configurations (single agent, agent + LLM critic, Casefile) with false-completion rate and cost per correctly completed case on Crusoe.
- G5. A 60-second demo on alerts A-104 and A-105.

Non-goals
- No real customer data, no real money movement. Everything is synthetic.
- No similar-case search (no embedding model in the Crusoe catalog we were given).
- Stretch only, after the benchmark has run, at most one: VoiceChat callback, Omni screenshot reader. Lightning fine-tuning is out for today.
- Shared Brain / Version N+1 are demoed as extensions only if time remains.

## 3. Users
- Fraud analyst (bank/fintech) working an alert queue. Sees only escalations and insufficient-evidence cases.
- Customer whose account was taken over while the case sat marked "closed".
- Hackathon judges: need a visible refusal moment and measured numbers.

## 4. Terminal outcomes (never merged)
| Outcome | Meaning |
| --- | --- |
| `collection_failed` | A required evidence source ended in `error` after allowed retries |
| `closed_benign` | All checks passed and policy says benign |
| `escalated` | All checks passed and policy says escalate |
| `insufficient_evidence` | Sources responded but evidence is empty, partial, stale or unresolved-contradictory |

Assumption A1: the brief lists "evidence collection succeeded vs. failed; closed benign; escalated; insufficient evidence". We read that as four terminal outcomes, where "collection failed" is the failure side. `closed_benign` and `escalated` are *closure* outcomes and require a passing verification; the other two make no claim of completion and do not.

## 5. Functional requirements
| ID | Requirement | Verified by |
| --- | --- | --- |
| FR-01 | Planner turns a one-line goal into a contract using only allowlisted checks. Unknown checks are rejected. | `test_contract.py` |
| FR-02 | Policy-mandated checks and required sources cannot be removed by the Planner or by a revision. | `test_contract.py` |
| FR-03 | The contract is immutable. Any change creates a new version (version + 1). | `test_contract.py` |
| FR-04 | Evidence from a tool is `ok`, `error`, `empty`, `partial` or `stale`. Only `ok` counts as collected. Error/empty/partial is never read as "nothing suspicious". | `test_verifier.py`, `test_features_policy.py` |
| FR-05 | Verifier runs seven code checks: correct account, required evidence, window covered, claims supported, policy followed, contradictions addressed, result persisted. | `test_verifier.py` |
| FR-06 | Each failed check returns an actionable failure (check, reason naming source and status, evidence ids). Never "think harder". | `test_verifier.py` |
| FR-07 | Numeric claims are recomputed from evidence by code. | `test_verifier.py` |
| FR-08 | `result_persisted` is checked after commit (`post_commit`); the other six before (`pre_commit`). | `test_verifier.py` |
| FR-09 | The Gate is the only writer. It refuses closure outcomes without a passing verification, refuses non-allowlisted actions, and is idempotent per idempotency key. | `test_gate.py` |
| FR-10 | An interrupted final write can be retried with the same key and results in exactly one write. | `test_gate.py` |
| FR-11 | Loop guard: same tool + same arguments + no new evidence forces a re-plan; at most 2 re-plans; tool-call ceiling; deadline. | `test_loop_guard.py` |
| FR-12 | Attributor outputs (agent, step, category), validated against a closed schema. Scored by exact match, never substring. | `test_attribution.py` |
| FR-13 | Re-plan repairs only the attributed step (for the email-for-account-ID fault: resolve the account ID and retry that lookup). | `test_replan.py` (to write, needs fake LLM) |
| FR-14 | Investigator has exactly four tools; Planner has only `get_policy`; neither has write tools. | `test_isolation.py` |
| FR-15 | Ground-truth labels are unreachable from agent code. | `test_isolation.py` |
| FR-16 | Every model call logs role, model, tokens (input, cached, output), latency, retries and cost to a JSONL trace. | `test_metrics_cost.py` |
| FR-17 | Benchmark runs the same cases, tools, models and budgets through three configurations; held-out cases are separate from development cases. | `test_benchmark.py` (to write) |
| FR-18 | Fault injection covers wrong identifier, missing device evidence, stale records, contradictory timestamps, interrupted final write. | `test_tools_faults.py`, `test_gate.py` |
| FR-19 | Synthetic A-104 ends `escalated`; A-105 ends `closed_benign`; "escalate everything unfamiliar" must fail A-105. | `test_features_policy.py` |
| FR-20 | Results UI shows timeline, definition-of-done checklist, and results table; only measured numbers are displayed. | manual + `test_report.py` (to write) |

## 6. Metrics (definitions are normative)
| Metric | Definition |
| --- | --- |
| False-completion rate | (runs that claimed completion and fail the independent oracle) / (runs that claimed completion). `None` if no run claimed completion. |
| Correct disposition rate | runs whose terminal outcome equals the oracle outcome / all runs |
| Recovery rate | recoverable-fault runs ending correct with no human / recoverable-fault runs |
| Unnecessary escalation rate | oracle-benign runs that ended `escalated` / oracle-benign runs |
| Supported-claim rate | claims whose cited evidence exists, is `ok` and (if numeric) recomputes / all claims |
| Attribution accuracy | exact match on agent **and** step / attributed failures |
| Cost per correct case | total spend on **all** runs (including failed attempts) / number of correct runs. `None` if zero correct. |
| Latency | p50 and p95 of wall-clock per run, retries included (nearest-rank percentile) |

## 7. Non-functional requirements
- NFR-1 Provider: Crusoe only. No other model API in agent code.
- NFR-2 Determinism: every pass/fail decision, number and closure comes from code. Models plan, read evidence, explain.
- NFR-3 Safety: evidence text is untrusted. Only read tools are exposed to models that read it. Planner sees typed features, never raw customer text.
- NFR-4 Rate limits: back off on 429/503 with jitter; stay inside per-model RPM. Without a payment method the limit is 30 RPM per model.
- NFR-5 Reasoning headroom: reasoning models get `max_tokens` of at least 1024 and `finish_reason == "length"` is treated as an error, not an answer.
- NFR-6 Cost control: per-run and per-benchmark spend ceilings; abort when exceeded.
- NFR-7 Reproducibility: seeded case generator, versioned policy, versioned contract, trace per run.
- NFR-8 Secrets: `CRUSOE_API_KEY` only from env or `.env.local`; never logged.

## 8. Synthetic cases
| Alert | Sequence | Correct outcome |
| --- | --- | --- |
| A-104 account takeover | Known US device for months, new device in another country, MFA reset, three $1-$2 test charges, new beneficiary, $4,800 transfer | `escalated` |
| A-105 benign lookalike | New phone same country, payroll in, first rent payment to a new landlord | `closed_benign` |

Policy (ours, synthetic; thresholds are not from the brief): escalate when a new device in a foreign country is followed by an MFA reset, a new beneficiary exists, and a transfer is at least 1,000. Otherwise benign. A-105 has a new beneficiary and a 1,500 transfer but no foreign device and no MFA reset, so it must close benign.

## 9. Acceptance criteria (demo-level)
1. A-104 with the wrong-identifier fault: the baseline closes benign; the LLM critic approves; the Gate refuses; the Attributor names Investigator + device lookup step; re-plan resolves the account ID; case ends `escalated` with cited events.
2. A-105 ends `closed_benign` with all checks green.
3. Results panel shows measured numbers for the three configurations and for the model-assignment arms, from a real run.
4. Held-out run executed once, after the pipeline is frozen.

## 10. Assumptions and open questions (verify before stage claims)
| # | Item | Why it matters / plan |
| --- | --- | --- |
| A1 | Meaning of "four outcomes" (see section 4) | Confirm; changes the `Outcome` enum |
| A2 | **Resolved Oct 17:** `nvidia/NVIDIA-Nemotron-3.5-Super-VL` exists in this project's `/v1/models` ($0.10 / $0.08 / $0.40 per 1M; lists tools, response_format, structured_outputs). Fallback to Super 120B no longer needed | Closed |
| A3 | Lightning and Super VL tool-calling support is unconfirmed | Check `supported_parameters` for `tools`. Fallback: JSON action protocol validated by schema |
| A4 | Schema-constrained output (`response_format`) may not be supported on every model | Check `supported_parameters`. Fallback: JSON in prompt, validate, one retry |
| A5 | Rate limits: 30 RPM/model without a payment method. A rough estimate (about 8 calls per case, 24 cases, 6 arms) is 1,100-1,200 calls, more than half on Lightning | Add a payment method (600 RPM) before the benchmark, or budget 20+ minutes of queueing per full run. These are estimates, not measured |
| A6 | Case memory: brief says Supabase for the Shared Brain extension | Core uses SQLite/in-memory so nothing external can block the build; Supabase only if the extension is built |
| A7 | Benchmark size is not specified | Proposal: 2 scenarios x 6 fault conditions (none + 5) = 12 cases per split, seeded variants; 12 dev, 12 held-out |
| A8 | Which checks are Planner-optional | Proposal: mandatory = correct_account, required_evidence, claims_supported, policy_followed, result_persisted. Optional (Planner-selectable) = window_covered, contradictions_addressed |
| A9 | **Resolved Oct 17:** prices are read from `/v1/models` (pricing.prompt / input_cache_reads / completion), not from the console snapshot | Closed |
| A10 | Substring-scoring claim about Failure Attribution issue #14, UltraBERT numbers, Gemma 4 article | Do not cite on stage until read |
| A11 | Judging criteria, submission process and credits are unpublished | Ask organizers |
