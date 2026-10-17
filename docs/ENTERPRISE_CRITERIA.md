# Enterprise criteria: PayPal agent-platform guidance vs. this build

Source of the criteria: the summaries of the PayPal talk "Building Agentic AI at PayPal: Platform, Governance, and Agent Design" (Hardik Nahata and
Deepika Khera, The AI Conference) that the project owner pasted on Oct 17 2026. I could not retrieve the video or a transcript, so every criterion
below is taken from those summaries and none was checked against the talk itself. Models: Crusoe Managed Inference only.

Status key: **Built** (code + tests), **Partial** (works, with a stated limit), **Stub** (simulated for the hackathon), **Gap** (not built).

## Platform foundations
| Criterion | Status | What exists | Limit, stated plainly |
| --- | --- | --- | --- |
| Agent registry: owned, certified, validated agents | **Built (self-attested)** | `harness/agents.py`: owner, version, model role, tools, `certified_by`; the governance gate refuses to run if a required agent is not certified, before any model call | Certification is a recorded self-attestation, not an independent review |
| Tool registry (MCP-style): reusable, versioned tools | **Built (local)** | `harness/registry.py`: each tool has owner, version, read/write class; per-role authorization at call time; one receipt shape (`status`, `evidence_id`, `coverage`, `record_count`) | Not an actual MCP server. The investigator loop uses the registry for authorization; the full receipt is returned by `registry.call`, while the loop still passes `EvidenceRecord`s |
| AI router: single governance point, unified key, RBAC, cost bounds, DLP/PII masking | **Built** | `harness/router.py`: one client for every Crusoe call; model allowlist; role-based model access (default deny); per-case dollar budget; PII tokenized outbound and restored inbound (`harness/masking.py`); one log line per call with no prompt text | Crusoe only, so there is no multi-provider routing. Rate-limit headers are absent on 200 responses (verified), so throttling uses the configured RPM |
| Enterprise memory: working, episodic, semantic, procedural | **Built (governed local service); runtime integration partial** | `harness/memory.py`: working entries are discarded on completion; closed episodes are immutable and capped; semantic proposals need evidence, expiry, an independent certifier and verifying team; procedural edits need source episodes, a different approver and measured gain; organizational retrieval returns only certified, unexpired content under one cap. `scripts/memory_certification_demo.py` exercises every rule | Durable storage is local JSONL. Supabase centralization and automatic N+1 candidate generation from completed episodes are not yet wired into the runtime |
| Gateway: identity, authentication, policy enforcement | **Partial / Stub** | Tenant allowlist and policy-version check in the governance gate; per-role identities for tools and models | No user authentication or signed tokens |
| Agent runtime: framework-agnostic, delegation, observability | **Partial** | A small code state machine; trace, audit and router logs share one `context_id` and a `task_id` per step | No agent-to-agent protocol; no LangGraph (not needed at this size) |

## Design patterns
| Criterion | Status | Evidence |
| --- | --- | --- |
| Graph orchestration, not a prompt chain | **Partial** | Fixed nodes in code: intake, governance, required fields, run (plan, investigate, verify, commit), review. No intent-detection node because there is one alert type |
| Typed state + durable checkpoints | **Built (coarse)** | `harness/state.py` (`CaseState`, data classes), `harness/checkpoint.py` (append-only; torn last line tolerated). Resume test: a finished case makes no model calls and no duplicate writes. Checkpoints are per node; a crash inside the run node restarts that node, protected by idempotent commit |
| Orchestrator vs execution | **Built** | Code decides control flow; the Investigator executes with read-only tools and separate context; the Planner never sees evidence text |
| Normalization (shared response contract, task id, context id) | **Partial** | Tool receipt contract + `context_id`/`task_id` on every trace step |
| Human-in-the-loop on missing parameters | **Built** | `required_fields_check`: an email passed as `account_id`, a missing window, or an unresolvable identity interrupts to a human before any model call. Budget exhaustion also goes to an analyst as insufficient evidence |
| Governance gates early (no tokens on non-compliant work) | **Built** | Unsupported alert type, unknown policy version, disallowed tenant, uncertified agent: rejected with zero model calls (tested) |
| No hallucinated assumptions | **Built** | Schema-constrained outputs on every agent (`schemas.py`, verified live on Crusoe), code-recomputed numbers, verbatim-quote checks, loop guard |

## Pull-request gate (PayPal slide: PCI exposure, data classification, API-contract changes, regulatory surface)
| Criterion | Status | Evidence |
| --- | --- | --- |
| Gate checks the four items before merge | **Built** | `src/casefile/gate_mcp/` (checks, decision, MCP server), `scripts/pr_gate.py` for CI, 37 tests; details in `docs/GATE_MCP.md` |
| Regulatory research through You.com finance MCP | **Not connected** | The endpoint requires OAuth; it must be authorized in an MCP client. The gate returns research queries and validates the evidence; nothing has been researched through it yet |

## Safety and audit extras
| Control | Status | Evidence |
| --- | --- | --- |
| Tamper-evident audit trail | **Built** | `harness/audit.py` hash chain; editing a line breaks `verify_chain()` |
| Analyst review queue; decision stored as the label | **Built** | `harness/review.py`; escalations, insufficient evidence and budget stops open a task; decisions are append-only |
| No money movement or account freezes by the agent | **Built** | `commit_disposition` is the only write tool and no role except the commit step may call it; injected instructions to call it are denied in code (tested) |
| Prompt-injection resistance | **Built** | Tool results are data; role authorization is enforced in code; schema-constrained outputs |

## What the talk's "System 1" point does and does not support here
The summaries say small decision models can be 40 to 500 times cheaper than large LLMs. On Crusoe's prices (from `/v1/models`) the cheapest and next models are
only 2 times (Lightning vs Super VL output price) to 12 times (Lightning vs Super 120B) apart, and we make most decisions in plain code. We therefore report
our own measured cost per correct case and do not repeat the 40 to 500 times figure.

## Open gaps, in priority order
1. Wire semantic and procedural memory into the agents and the Version N+1 loop.
2. Finer checkpoints inside the run node (plan, investigate, verify, commit).
3. Real authentication/identity for the gateway.
4. Per-model throttling that adapts to the account's real rate limit.
5. Apply the enterprise runner to the case-file (records) mode; it currently has its own loop and the same router/masking can wrap it.
