#!/usr/bin/env python3
"""Demonstrate working, episodic, semantic, and procedural memory certification."""

from __future__ import annotations

import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from casefile.harness.memory import (  # noqa: E402
    EpisodicMemory,
    MemoryRejected,
    OrganizationalMemory,
    ProceduralMemory,
    SemanticMemory,
    WorkingMemory,
)


def blocked(callable_) -> bool:
    try:
        callable_()
    except MemoryRejected:
        return True
    return False


def main() -> None:
    today = date(2026, 10, 17)
    out = ROOT / "runs" / f"memory-certification-{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True, exist_ok=False)

    working = WorkingMemory()
    working.start("case:A-104", {"step": "investigate"})
    working.update("case:A-104", evidence_ids=["ev_dev"])
    working.discard("case:A-104")

    episodic = EpisodicMemory(out / "episodes.jsonl")
    episodic.record(
        "episode:A-104",
        "tool_call",
        agent="investigator",
        agent_version="1.0",
        evidence_ids=["ev_dev"],
    )
    episodic.close("episode:A-104", outcome="escalated", label_id="review:A-104")

    semantic = SemanticMemory(out / "semantic.jsonl")
    semantic_id = semantic.propose(
        "acct_1040",
        {"home_country": "US"},
        ["ev_dev"],
        today + timedelta(days=30),
        author="agent:distiller",
        proposing_team="casefile",
        evidence_index={"ev_dev"},
        today=today,
    )
    hidden_before_review = semantic.facts(on=today) == []
    self_certification_blocked = blocked(
        lambda: semantic.certify(
            semantic_id,
            reviewer="agent:distiller",
            verifying_team="risk-operations",
            today=today,
        )
    )
    semantic.certify(
        semantic_id,
        reviewer="analyst_1",
        verifying_team="risk-operations",
        today=today,
    )

    procedural = ProceduralMemory(out / "procedural.jsonl")
    version = procedural.propose(
        "Resolve an account identifier before account-scoped evidence calls.",
        author="attributor",
        proposing_team="casefile",
        source_episode_ids=["episode:A-104"],
    )
    self_approval_blocked = blocked(
        lambda: procedural.approve(version, approver="attributor", score_before=0.6, score_after=0.8)
    )
    no_gain_blocked = blocked(
        lambda: procedural.approve(version, approver="analyst_1", score_before=0.8, score_after=0.8)
    )
    procedural.approve(
        version,
        approver="analyst_1",
        verifying_team="agent-governance",
        evaluation_id="eval:wrong-identifier",
        score_before=0.6,
        score_after=0.8,
    )

    organization = OrganizationalMemory(semantic, procedural)
    retrieved = organization.retrieve(subject="acct_1040", on=today, limit=2)
    stale_hidden = semantic.facts(on=today + timedelta(days=31)) == []

    result = {
        "working_discarded_on_completion": not working.active("case:A-104"),
        "episode_closed_and_immutable": episodic.closed("episode:A-104") and blocked(
            lambda: episodic.record(
                "episode:A-104",
                "late_write",
                agent="investigator",
                agent_version="1.0",
            )
        ),
        "unreviewed_fact_hidden": hidden_before_review,
        "semantic_self_certification_blocked": self_certification_blocked,
        "certified_fact_retrieved": len(retrieved["semantic"]) == 1,
        "certifying_team": retrieved["semantic"][0]["verifying_team"],
        "stale_fact_forgotten": stale_hidden,
        "procedural_self_approval_blocked": self_approval_blocked,
        "procedural_no_gain_blocked": no_gain_blocked,
        "certified_workflow_retrieved": len(retrieved["procedural"]) == 1,
        "retrieval_cap": retrieved["cap"],
    }
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"audit artifacts: {out}")


if __name__ == "__main__":
    main()

