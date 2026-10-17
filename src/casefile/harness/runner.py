"""Enterprise runner: intake -> governance -> identity/required fields -> run -> review task -> done.
Gates run in code before any model call; every node checkpoints; commits are audited; nothing moves money."""
from dataclasses import dataclass
from typing import Optional

from ..errors import BudgetExceeded
from ..models import Case, Outcome
from ..orchestrator import RunRecord, run_casefile
from .gates import GovernanceConfig, governance_gate, required_fields_check
from .state import Alert, CaseState

NEEDS_REVIEW = {Outcome.ESCALATED.value, Outcome.INSUFFICIENT_EVIDENCE.value, Outcome.COLLECTION_FAILED.value}


@dataclass
class EnterpriseResult:
    state: CaseState
    run: Optional[RunRecord] = None


def run_enterprise(alert: Alert, raw: dict, faults, llm, ledger, trace, *, config: GovernanceConfig, checkpoints, audit,
                   review, identity: dict | None = None, agents=None) -> EnterpriseResult:
    if hasattr(trace, "context_id"):
        trace.context_id = alert.alert_id                        # one context id across trace, audit and checkpoints
    state = checkpoints.latest(alert.alert_id)
    if state and (state.status in ("done", "rejected") and state.alert == alert):
        return EnterpriseResult(state)                              # already finished: no model calls, no duplicate writes
    if state is None or state.alert != alert:
        state = CaseState(case_id=alert.alert_id, alert=alert)

    def advance(node, **upd):
        nonlocal state
        state = state.model_copy(update={"completed": [*state.completed, node], **upd})
        checkpoints.save(state)

    def stop(status, key, reason):
        nonlocal state
        state = state.model_copy(update={"status": status, key: reason})
        checkpoints.save(state)
        audit.append("rejected" if status == "rejected" else "interrupt", alert.alert_id, {"reason": reason})
        return EnterpriseResult(state)

    advance("intake")
    audit.append("intake", alert.alert_id, state.model_view())    # model-safe view only: no PII in the audit payload either

    d = governance_gate(alert, config, agents)
    if not d.allowed:
        return stop("rejected", "reject_reason", d.reason)        # no tokens spent
    advance("governance")

    account_id, prov = alert.account_id, "provided"
    if account_id is None and alert.email:                        # deterministic identity lookup, not a model guess
        account_id = (identity or {}).get(alert.email)
        prov = "resolved:resolve_account"
    checked = alert.model_copy(update={"account_id": account_id})
    missing = required_fields_check(checked)
    if missing:
        return stop("interrupted", "interrupt_reason", f"required fields missing or invalid: {missing}; a human must supply them")
    advance("required_fields", account_id=account_id, provenance={"account_id": prov})

    case = Case(id=alert.alert_id, email=alert.email or "", account_id=account_id, tenant_id=alert.tenant_id,
                window_start=alert.window_start, window_end=alert.window_end, raw=raw)
    try:
        run = run_casefile(case, faults, llm, ledger, trace)
    except BudgetExceeded as e:                                    # out of budget: a person decides, nobody guesses
        audit.append("budget_exhausted", alert.alert_id, {"reason": str(e)})
        task_id = review.open_task(alert.alert_id, Outcome.INSUFFICIENT_EVIDENCE.value,
                                   {"evidence": [], "reason": "per-case budget exhausted before the contract was satisfied"})
        advance("run", outcome=Outcome.INSUFFICIENT_EVIDENCE.value)
        advance("review", review_task_id=task_id)
        state = state.model_copy(update={"status": "done"})
        checkpoints.save(state)
        return EnterpriseResult(state)
    audit.append("commit", alert.alert_id, {"outcome": run.outcome.value, "receipt": run.receipt.id if run.receipt else None,
                                           "replans": run.replans, "cost_usd": round(run.cost_usd, 6)})
    advance("run", outcome=run.outcome.value, receipt_id=run.receipt.id if run.receipt else None)

    task_id = None
    if run.outcome.value in NEEDS_REVIEW:
        packet = {"evidence": [{"id": r.id, "source": r.source, "status": r.status.value} for r in run.evidence],
                  "refusals": run.refusals, "attributions": [a.model_dump(mode="json") for a in run.attributions],
                  "failed_checks": [f.check for f in (run.verification.failures if run.verification else [])]}
        task_id = review.open_task(alert.alert_id, run.outcome.value, packet)
        audit.append("review_task_opened", alert.alert_id, {"task_id": task_id})
    advance("review", review_task_id=task_id)
    state = state.model_copy(update={"status": "done"})
    checkpoints.save(state)
    return EnterpriseResult(state, run)
