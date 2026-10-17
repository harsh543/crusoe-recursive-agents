"""Supabase adapter for the database-enforced four-layer memory contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..store import Store
from .memory import MemoryRejected


def _scalar(value: Any) -> Any:
    """PostgREST returns scalar RPCs as scalars, but tolerate one-cell rows in fakes."""
    if isinstance(value, list) and len(value) == 1:
        row = value[0]
        if isinstance(row, dict) and len(row) == 1:
            return next(iter(row.values()))
        return row
    return value


class SupabaseEnterpriseMemory:
    """Backend-only access to certified organizational memory in Supabase.

    The database owns all important policy: closing an episode deletes working
    memory, closed episodes reject events, and certification cannot be bypassed
    by this adapter.
    """

    MAX_ORGANIZATIONAL_RETRIEVAL = 20
    MAX_EPISODE_RETRIEVAL = 100

    def __init__(self, store: Store | None = None, *, require_remote: bool = True):
        self.store = store or Store()
        if require_remote and not self.store.remote:
            raise MemoryRejected("certified enterprise memory requires configured Supabase credentials")

    def start_working(
        self,
        tenant_id: str,
        task_id: str,
        owner_agent: str,
        content: dict | None = None,
        *,
        case_id: str | None = None,
        ttl_minutes: int = 180,
    ) -> str:
        return str(_scalar(self.store.rpc(
            "start_working_memory",
            p_tenant_id=tenant_id,
            p_task_id=task_id,
            p_owner_agent=owner_agent,
            p_content=content or {},
            p_case_id=case_id,
            p_ttl_minutes=ttl_minutes,
        )))

    def update_working(self, tenant_id: str, task_id: str, patch: dict) -> None:
        self.store.rpc(
            "update_working_memory",
            p_tenant_id=tenant_id,
            p_task_id=task_id,
            p_patch=patch,
        )

    def working_snapshot(self, tenant_id: str, task_id: str) -> dict | None:
        result = _scalar(self.store.rpc(
            "working_memory_snapshot", p_tenant_id=tenant_id, p_task_id=task_id
        ))
        return result if isinstance(result, dict) else None

    def discard_working(self, tenant_id: str, task_id: str) -> bool:
        return bool(_scalar(self.store.rpc(
            "discard_working_memory", p_tenant_id=tenant_id, p_task_id=task_id
        )))

    def open_episode(
        self,
        tenant_id: str,
        task_id: str,
        owner_agent: str,
        agent_version: str,
        *,
        initial_working_memory: dict | None = None,
        case_id: str | None = None,
        ttl_minutes: int = 180,
    ) -> str:
        return str(_scalar(self.store.rpc(
            "open_memory_episode",
            p_tenant_id=tenant_id,
            p_task_id=task_id,
            p_owner_agent=owner_agent,
            p_agent_version=agent_version,
            p_initial_working_memory=initial_working_memory or {},
            p_case_id=case_id,
            p_ttl_minutes=ttl_minutes,
        )))

    def record_episode_event(
        self,
        episode_id: str,
        action: str,
        *,
        agent: str,
        agent_version: str,
        data: dict | None = None,
        evidence_ids: list[str] | None = None,
    ) -> int:
        return int(_scalar(self.store.rpc(
            "record_memory_episode_event",
            p_episode_id=episode_id,
            p_action=action,
            p_agent=agent,
            p_agent_version=agent_version,
            p_data=data or {},
            p_evidence_ids=evidence_ids or [],
        )))

    def episode_events(self, episode_id: str, *, limit: int = 50) -> list[dict]:
        cap = max(0, min(int(limit), self.MAX_EPISODE_RETRIEVAL))
        return self.store.rpc("get_memory_episode_events", p_episode_id=episode_id, p_k=cap)

    def close_episode(self, episode_id: str, *, outcome: str, review_label: str | None = None) -> None:
        self.store.rpc(
            "close_memory_episode",
            p_episode_id=episode_id,
            p_outcome=outcome,
            p_review_label=review_label,
        )

    def propose_semantic(
        self,
        tenant_id: str,
        subject: str,
        content: dict,
        *,
        author_identity: str,
        proposing_team: str,
        evidence_ids: list[str],
        automated_confidence: float,
        valid_until: datetime,
        source_episode_ids: list[str] | None = None,
        confidence_threshold: float = 0.85,
    ) -> str:
        return str(_scalar(self.store.rpc(
            "propose_semantic_memory",
            p_tenant_id=tenant_id,
            p_subject=subject,
            p_content=content,
            p_author_identity=author_identity,
            p_proposing_team=proposing_team,
            p_evidence_ids=evidence_ids,
            p_automated_confidence=automated_confidence,
            p_valid_until=valid_until.isoformat(),
            p_source_episode_ids=source_episode_ids or [],
            p_confidence_threshold=confidence_threshold,
        )))

    def propose_procedural(
        self,
        tenant_id: str,
        subject: str,
        workflow: dict,
        *,
        author_identity: str,
        proposing_team: str,
        source_episode_ids: list[str],
        automated_confidence: float,
        evidence_ids: list[str] | None = None,
        confidence_threshold: float = 0.85,
    ) -> str:
        return str(_scalar(self.store.rpc(
            "propose_procedural_memory",
            p_tenant_id=tenant_id,
            p_subject=subject,
            p_workflow=workflow,
            p_author_identity=author_identity,
            p_proposing_team=proposing_team,
            p_source_episode_ids=source_episode_ids,
            p_automated_confidence=automated_confidence,
            p_evidence_ids=evidence_ids or [],
            p_confidence_threshold=confidence_threshold,
        )))

    def review(
        self,
        candidate_id: str,
        *,
        decision: str,
        reviewer_identity: str,
        reviewer_team: str,
        reviewer_role: str,
        rationale: str,
        evaluation_id: str | None = None,
        score_before: float | None = None,
        score_after: float | None = None,
    ) -> str:
        return str(_scalar(self.store.rpc(
            "review_enterprise_memory",
            p_candidate_id=candidate_id,
            p_decision=decision,
            p_reviewer_identity=reviewer_identity,
            p_reviewer_team=reviewer_team,
            p_reviewer_role=reviewer_role,
            p_rationale=rationale,
            p_evaluation_id=evaluation_id,
            p_score_before=score_before,
            p_score_after=score_after,
        )))

    def retrieve(self, tenant_id: str, *, subject: str | None = None, limit: int = 10) -> list[dict]:
        cap = max(0, min(int(limit), self.MAX_ORGANIZATIONAL_RETRIEVAL))
        return self.store.rpc(
            "retrieve_organizational_memory", p_tenant_id=tenant_id, p_subject=subject, p_k=cap
        )

    def forget_expired(self, tenant_id: str | None = None) -> int:
        return int(_scalar(self.store.rpc("forget_expired_enterprise_memory", p_tenant_id=tenant_id)))

    def retire(
        self,
        candidate_id: str,
        *,
        retired_by: str,
        retiring_team: str,
        reason: str,
        detail: str | None = None,
    ) -> str:
        return str(_scalar(self.store.rpc(
            "retire_enterprise_memory",
            p_candidate_id=candidate_id,
            p_retired_by=retired_by,
            p_retiring_team=retiring_team,
            p_reason=reason,
            p_detail=detail,
        )))

    def record_model_route(
        self,
        tenant_id: str,
        task_id: str,
        *,
        role: str,
        task_class: str,
        system_level: str,
        selected_model: str,
        reason: str,
        confidence: float | None = None,
        estimated_cost_usd: float | None = None,
        actual_cost_usd: float | None = None,
        case_id: str | None = None,
        escalated_from_id: str | None = None,
    ) -> dict:
        return self.store.insert("model_routing_decisions", {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "case_id": case_id,
            "role": role,
            "task_class": task_class,
            "system_level": system_level,
            "selected_model": selected_model,
            "reason": reason,
            "confidence": confidence,
            "estimated_cost_usd": estimated_cost_usd,
            "actual_cost_usd": actual_cost_usd,
            "escalated_from_id": escalated_from_id,
        })

