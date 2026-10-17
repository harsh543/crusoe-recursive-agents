"""The completion contract: allowlisted checks, mandatory checks the Planner cannot remove, frozen versions."""
from datetime import datetime
from typing import Sequence

from pydantic import BaseModel, ConfigDict

CHECKS = frozenset({
    "correct_account", "required_evidence", "window_covered", "claims_supported",
    "policy_followed", "contradictions_addressed", "result_persisted",
})
MANDATORY_CHECKS = frozenset({
    "correct_account", "required_evidence", "claims_supported", "policy_followed", "result_persisted",
})


class UnknownCheckError(ValueError):
    pass


class ContractViolation(ValueError):
    pass


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True)
    version: int = 1
    case_id: str
    account_id: str
    tenant_id: str
    window_start: datetime
    window_end: datetime
    required_sources: tuple[str, ...]
    locked_sources: tuple[str, ...]      # policy minimum; revisions cannot drop these
    checks: tuple[str, ...]

    def revise(self, **changes) -> "Contract":
        for k in ("checks", "required_sources"):
            if k in changes:
                changes[k] = tuple(changes[k])
        new = self.model_copy(update={**changes, "version": self.version + 1})
        _validate(new.checks, new.required_sources, new.locked_sources)
        return new


def _validate(checks, sources, locked):
    unknown = set(checks) - CHECKS
    if unknown:
        raise UnknownCheckError(f"checks not in allowlist: {sorted(unknown)}")
    if not MANDATORY_CHECKS <= set(checks):
        raise ContractViolation(f"mandatory checks removed: {sorted(MANDATORY_CHECKS - set(checks))}")
    if not set(locked) <= set(sources):
        raise ContractViolation(f"policy-required sources removed: {sorted(set(locked) - set(sources))}")


def build_contract(*, case_id: str, account_id: str, tenant_id: str, window_start: datetime,
                   window_end: datetime, planner_checks: Sequence[str], policy,
                   planner_sources: Sequence[str] = ()) -> Contract:
    unknown = set(planner_checks) - CHECKS
    if unknown:
        raise UnknownCheckError(f"checks not in allowlist: {sorted(unknown)}")
    sources = tuple(dict.fromkeys([*policy.required_sources, *planner_sources]))
    return Contract(
        case_id=case_id, account_id=account_id, tenant_id=tenant_id,
        window_start=window_start, window_end=window_end,
        required_sources=sources, locked_sources=tuple(policy.required_sources),
        checks=tuple(sorted(MANDATORY_CHECKS | set(planner_checks))),
    )
