# Certified enterprise memory

This implementation follows the supplied “Memory with certification” slide as a behavioral requirement. The slide is treated as architectural
guidance, not as independently verified documentation about any external organization.

## Criteria matrix

| Layer | Required behavior | Casefile implementation | Enforcement |
| --- | --- | --- | --- |
| Working | Discard on completion | `WorkingMemory` holds process-local task context and deletes the full task entry with `discard()` | A discarded task cannot be retrieved |
| Episodic | Preserve one session/run | `EpisodicMemory` records agent/version, actions, evidence IDs, outcome, and review label | Events are episode-scoped; a closed episode rejects late writes; retrieval is capped |
| Semantic | Store distilled facts | `SemanticMemory` stores evidence-backed proposals with expiry, author, and proposing team | Proposals are invisible until an independent reviewer certifies them |
| Procedural | Store step-by-step workflow | `ProceduralMemory` stores versioned playbook proposals linked to source episodes | Promotion requires a different approver and a strictly better measured score |
| Certification | Human review blocks unverified facts | Semantic certification records reviewer and verifying team; self-certification is rejected | Organizational retrieval returns certified rows only |
| Long-term organizational memory | Persistent, bounded, traceable | `OrganizationalMemory` is the single capped retrieval interface over semantic and procedural JSONL stores | Every returned fact includes evidence IDs, certifier, team, certification date, and expiry |
| Forgetting | Stale facts actively disappear | Expired certified facts receive append-only `forgotten` tombstones | Expired/tombstoned facts cannot be retrieved, while the audit history remains intact |

## Demonstration

```bash
.venv/bin/python scripts/memory_certification_demo.py
```

The demo proves that working memory is discarded, closed episodes are immutable, unreviewed facts are hidden, self-certification is blocked,
non-improving procedures cannot ship, expired facts are tombstoned, retrieval is capped, and every approved item identifies its certifying team.

## Boundary

This is a governed persistent memory service with local JSONL durability. The Supabase grounding corpus remains the shared policy/document store.
Centralizing the semantic/procedural certification rows in Supabase and automatically proposing N+1 candidates from completed episodes are the next
integration steps; neither is claimed as complete here.

