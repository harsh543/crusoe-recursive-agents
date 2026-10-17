"""Certified enterprise memory.

Working memory is transient and discarded on completion. Episodic memory is an
append-only record of one run. Semantic facts and procedural workflows become
retrievable organizational memory only after independent certification.
"""

import json
from datetime import date
from pathlib import Path


class MemoryRejected(Exception):
    pass


class _Jsonl:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def rows(self):
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def add(self, row):
        with self.path.open("a") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


class WorkingMemory:
    """Process-local task context. Completion deletes the entire task entry."""

    def __init__(self):
        self._tasks: dict[str, dict] = {}

    def start(self, task_id: str, initial: dict | None = None) -> None:
        if task_id in self._tasks:
            raise MemoryRejected(f"working memory for {task_id} already exists")
        self._tasks[task_id] = dict(initial or {})

    def update(self, task_id: str, **values) -> None:
        if task_id not in self._tasks:
            raise MemoryRejected(f"working memory for {task_id} is not active")
        self._tasks[task_id].update(values)

    def snapshot(self, task_id: str) -> dict:
        if task_id not in self._tasks:
            raise MemoryRejected(f"working memory for {task_id} is not active")
        return dict(self._tasks[task_id])

    def discard(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)

    def active(self, task_id: str) -> bool:
        return task_id in self._tasks


class EpisodicMemory(_Jsonl):
    """Auditable events scoped to one episode; closed episodes are immutable."""

    MAX_RETRIEVAL = 100

    def record(
        self,
        episode_id: str,
        action: str,
        *,
        agent: str,
        agent_version: str,
        data: dict | None = None,
        evidence_ids: list[str] | None = None,
    ) -> int:
        if self.closed(episode_id):
            raise MemoryRejected(f"episode {episode_id} is already closed")
        seq = 1 + sum(row.get("episode_id") == episode_id for row in self.rows())
        self.add({
            "kind": "event",
            "episode_id": episode_id,
            "seq": seq,
            "action": action,
            "agent": agent,
            "agent_version": agent_version,
            "data": data or {},
            "evidence_ids": list(evidence_ids or []),
        })
        return seq

    def close(self, episode_id: str, *, outcome: str, label_id: str | None = None) -> None:
        if self.closed(episode_id):
            raise MemoryRejected(f"episode {episode_id} is already closed")
        self.add({"kind": "closed", "episode_id": episode_id, "outcome": outcome, "label_id": label_id})

    def closed(self, episode_id: str) -> bool:
        return any(row.get("kind") == "closed" and row.get("episode_id") == episode_id for row in self.rows())

    def events(self, episode_id: str, *, limit: int = 50) -> list[dict]:
        cap = max(0, min(int(limit), self.MAX_RETRIEVAL))
        return [
            row for row in self.rows()
            if row.get("kind") == "event" and row.get("episode_id") == episode_id
        ][:cap]


class SemanticMemory(_Jsonl):
    """Evidence-backed facts hidden from retrieval until independently certified."""

    MAX_RETRIEVAL = 50

    def propose(
        self,
        subject,
        fact: dict,
        evidence_ids: list,
        expires: date,
        *,
        author: str = "agent:distiller",
        proposing_team: str = "casefile",
        evidence_index=None,
        today=None,
    ) -> str:
        today = today or date.today()
        if not evidence_ids:
            raise MemoryRejected("a fact needs at least one evidence id")
        if evidence_index is not None and not set(evidence_ids) <= set(evidence_index):
            raise MemoryRejected(f"unknown evidence ids: {sorted(set(evidence_ids) - set(evidence_index))}")
        if expires <= today:
            raise MemoryRejected("a fact must expire in the future")
        proposal_id = f"sem_{1 + sum(row.get('kind') == 'proposal' for row in self.rows())}"
        self.add({
            "kind": "proposal",
            "proposal_id": proposal_id,
            "subject": subject,
            "fact": fact,
            "source_evidence": list(evidence_ids),
            "expires": expires.isoformat(),
            "proposed_on": today.isoformat(),
            "author": author,
            "proposing_team": proposing_team,
        })
        return proposal_id

    def _proposal(self, proposal_id: str) -> dict:
        proposal = next(
            (row for row in self.rows() if row.get("kind") == "proposal" and row.get("proposal_id") == proposal_id),
            None,
        )
        if proposal is None:
            raise MemoryRejected(f"semantic proposal {proposal_id} is unknown")
        return proposal

    def _decided(self, proposal_id: str) -> bool:
        return any(
            row.get("kind") in {"certification", "rejection"} and row.get("proposal_id") == proposal_id
            for row in self.rows()
        )

    def certify(
        self,
        proposal_id: str,
        *,
        reviewer: str,
        verifying_team: str,
        today: date | None = None,
    ) -> None:
        today = today or date.today()
        proposal = self._proposal(proposal_id)
        if self._decided(proposal_id):
            raise MemoryRejected(f"semantic proposal {proposal_id} is already decided")
        if reviewer == proposal["author"]:
            raise MemoryRejected("the fact author cannot certify their own proposal")
        if not reviewer.strip() or not verifying_team.strip():
            raise MemoryRejected("certification requires a reviewer and verifying team")
        if date.fromisoformat(proposal["expires"]) <= today:
            raise MemoryRejected("an expired fact cannot be certified")
        self.add({
            "kind": "certification",
            "proposal_id": proposal_id,
            "certified_on": today.isoformat(),
            "certified_by": reviewer,
            "verifying_team": verifying_team,
        })

    def reject(self, proposal_id: str, *, reviewer: str, verifying_team: str, reason: str) -> None:
        proposal = self._proposal(proposal_id)
        if self._decided(proposal_id):
            raise MemoryRejected(f"semantic proposal {proposal_id} is already decided")
        if reviewer == proposal["author"]:
            raise MemoryRejected("the fact author cannot review their own proposal")
        self.add({
            "kind": "rejection",
            "proposal_id": proposal_id,
            "reviewed_by": reviewer,
            "verifying_team": verifying_team,
            "reason": reason,
        })

    def forget_expired(self, *, on: date | None = None) -> list[str]:
        """Append expiry tombstones so stale truth is removed without erasing the audit trail."""
        on = on or date.today()
        rows = self.rows()
        certified = {row["proposal_id"] for row in rows if row.get("kind") == "certification"}
        forgotten = {row["proposal_id"] for row in rows if row.get("kind") == "forgotten"}
        expired = [
            row["proposal_id"] for row in rows
            if row.get("kind") == "proposal"
            and row["proposal_id"] in certified
            and row["proposal_id"] not in forgotten
            and date.fromisoformat(row["expires"]) <= on
        ]
        for proposal_id in expired:
            self.add({"kind": "forgotten", "proposal_id": proposal_id, "forgotten_on": on.isoformat(), "reason": "expired"})
        return expired

    def facts(self, on: date | None = None, *, subject: str | None = None, limit: int = 20) -> list[dict]:
        on = on or date.today()
        self.forget_expired(on=on)
        rows = self.rows()
        certifications = {row["proposal_id"]: row for row in rows if row.get("kind") == "certification"}
        unavailable = {row["proposal_id"] for row in rows if row.get("kind") in {"rejection", "forgotten"}}
        cap = max(0, min(int(limit), self.MAX_RETRIEVAL))
        facts = []
        for proposal in rows:
            proposal_id = proposal.get("proposal_id")
            if proposal.get("kind") != "proposal" or proposal_id not in certifications or proposal_id in unavailable:
                continue
            if date.fromisoformat(proposal["expires"]) <= on:
                continue
            if subject is not None and proposal["subject"] != subject:
                continue
            certification = certifications[proposal_id]
            facts.append({
                **proposal,
                "certified_on": certification["certified_on"],
                "certified_by": certification["certified_by"],
                "verifying_team": certification["verifying_team"],
            })
        return facts[:cap]


class ProceduralMemory(_Jsonl):
    """Versioned workflows promoted only after independent review and measured gain."""

    MAX_RETRIEVAL = 20

    def propose(
        self,
        text: str,
        author: str,
        *,
        proposing_team: str = "casefile",
        source_episode_ids: list[str] | None = None,
    ) -> int:
        version = sum(1 for row in self.rows() if row.get("kind") == "proposal") + 1
        self.add({
            "kind": "proposal",
            "version": version,
            "text": text,
            "author": author,
            "proposing_team": proposing_team,
            "source_episode_ids": list(source_episode_ids or []),
        })
        return version

    def approve(
        self,
        version: int,
        *,
        approver: str,
        score_before: float,
        score_after: float,
        verifying_team: str = "enterprise-review",
        evaluation_id: str | None = None,
    ) -> None:
        rows = self.rows()
        proposal = next((row for row in rows if row.get("kind") == "proposal" and row.get("version") == version), None)
        if proposal is None or any(row.get("kind") in {"approval", "rejection"} and row.get("version") == version for row in rows):
            raise MemoryRejected(f"version {version} is unknown or already decided")
        if approver == proposal["author"]:
            raise MemoryRejected("the author cannot approve their own edit")
        if not score_after > score_before:
            raise MemoryRejected(f"no measured improvement ({score_before} -> {score_after})")
        if not verifying_team.strip():
            raise MemoryRejected("approval requires a verifying team")
        self.add({
            "kind": "approval",
            "version": version,
            "approver": approver,
            "verifying_team": verifying_team,
            "evaluation_id": evaluation_id,
            "score_before": score_before,
            "score_after": score_after,
        })

    def certified(self, *, limit: int = 20) -> list[dict]:
        rows = self.rows()
        approvals = {row["version"]: row for row in rows if row.get("kind") == "approval"}
        cap = max(0, min(int(limit), self.MAX_RETRIEVAL))
        result = []
        for proposal in rows:
            if proposal.get("kind") != "proposal" or proposal["version"] not in approvals:
                continue
            approval = approvals[proposal["version"]]
            result.append({**proposal, **{key: value for key, value in approval.items() if key != "kind"}})
        return result[-cap:] if cap else []

    def active(self):
        certified = self.certified(limit=self.MAX_RETRIEVAL)
        return max(certified, key=lambda row: row["version"]) if certified else None


class OrganizationalMemory:
    """One capped interface over certified semantic and procedural memory."""

    MAX_RETRIEVAL = 20

    def __init__(self, semantic: SemanticMemory, procedural: ProceduralMemory):
        self.semantic = semantic
        self.procedural = procedural

    def retrieve(self, *, subject: str | None = None, on: date | None = None, limit: int = 10) -> dict:
        cap = max(0, min(int(limit), self.MAX_RETRIEVAL))
        procedure = self.procedural.active()
        semantic_limit = max(0, cap - int(procedure is not None))
        facts = self.semantic.facts(on=on, subject=subject, limit=semantic_limit)
        return {
            "semantic": facts,
            "procedural": [procedure] if procedure is not None and cap else [],
            "returned": len(facts) + int(procedure is not None and cap > 0),
            "cap": cap,
        }
