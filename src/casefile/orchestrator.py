"""Code state machine (no LLM decides control flow). Configurations: C1 single, C2 critic, C3 Casefile."""
import dataclasses
import time
from dataclasses import dataclass, field

from .agents import attributor, critic, investigator, planner
from .attribution import Attribution
from .contract import build_contract
from .features import IncompleteEvidence, compute_sequence_features, detect_contradictions
from .gate import Gate, GateRefused, Receipt, WriteInterrupted
from .harness.registry import build_registry
from .loop_guard import GuardDecision, LoopGuard
from .models import CLOSURE_OUTCOMES, Case, EvidenceStatus, Outcome, Recommendation
from .policy import Policy
from .tools import FaultPlan, ToolBox
from .verifier import VerificationResult, verify

GOAL = "Investigate the alert: decide whether to close it as benign or escalate it, with cited evidence."


@dataclass
class RunRecord:
    config: str
    case_id: str
    outcome: Outcome
    claimed_complete: bool
    evidence: list
    cost_usd: float = 0.0
    latency_s: float = 0.0
    replans: int = 0
    attributions: list[Attribution] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)       # gate/verifier refusals, shown in the demo
    verification: VerificationResult | None = None
    receipt: Receipt | None = None
    notes: list[str] = field(default_factory=list)
    recommendation: Recommendation | None = None            # last investigator answer, kept for durable persistence


def _window(case: Case) -> str:
    return f"{case.window_start:%Y-%m-%d}..{case.window_end:%Y-%m-%d}"


def _outcome_of(rec: Recommendation | None) -> Outcome:
    return rec.outcome if rec else Outcome.INSUFFICIENT_EVIDENCE


def run_single(case: Case, faults: FaultPlan, llm, ledger, trace, *, config="C1", data_source=None) -> RunRecord:
    """C1: one investigator, its conclusion is written as-is. No contract, no verifier."""
    t0, c0 = time.monotonic(), ledger.total_usd
    tb, store, guard = ToolBox(case, faults, data_source), {}, LoopGuard(max_replans=0, max_tool_calls=20, deadline_s=180)
    rec, _ = investigator.run(llm, tb, store, guard, trace, alert_id=case.id, email=case.email, window=_window(case))
    out = _outcome_of(rec)
    return RunRecord(config, case.id, out, out in CLOSURE_OUTCOMES, list(store.values()),
                     ledger.total_usd - c0, time.monotonic() - t0)


def run_critic(case: Case, faults: FaultPlan, llm, ledger, trace, *, data_source=None) -> RunRecord:
    """C2: investigator + an LLM critic. The critic can send it back once; nothing is verified by code."""
    t0, c0 = time.monotonic(), ledger.total_usd
    tb, store, guard = ToolBox(case, faults, data_source), {}, LoopGuard(max_replans=0, max_tool_calls=30, deadline_s=240)
    rec, msgs = investigator.run(llm, tb, store, guard, trace, alert_id=case.id, email=case.email, window=_window(case))
    notes = []
    if rec:
        approve, reason = critic.review(llm, msgs, rec)
        trace.add("critic", "review", approve=approve, reason=reason)
        notes.append(f"critic approve={approve}")
        if not approve:
            rec, _ = investigator.run(llm, tb, store, guard, trace, alert_id=case.id, email=case.email,
                                      window=_window(case), repair_note=f"A reviewer rejected your conclusion: {reason}")
    out = _outcome_of(rec)
    r = RunRecord("C2", case.id, out, out in CLOSURE_OUTCOMES, list(store.values()),
                  ledger.total_usd - c0, time.monotonic() - t0)
    r.notes = notes
    return r


def _commit(gate, verification, case, outcome, version, key):
    for _ in range(3):                              # an interrupted write is retried with the SAME key
        try:
            return gate.commit_disposition(verification=verification, case_id=case.id, outcome=outcome,
                                           contract_version=version, idempotency_key=key)
        except WriteInterrupted:
            continue
    raise WriteInterrupted("final write failed after retries")


def run_casefile(case: Case, faults: FaultPlan, llm, ledger, trace, *, policy: Policy | None = None,
                 max_replans=2, interrupt_write=False, data_source=None, playbook: str = "", fraud_engine=None) -> RunRecord:
    """C3: frozen contract, code verifier, attributor, targeted re-plan, gate."""
    t0, c0 = time.monotonic(), ledger.total_usd
    policy = policy or Policy()
    tb, store = ToolBox(case, faults, data_source, fraud_engine), {}
    registry = build_registry(tb, policy)
    guard = LoopGuard(max_replans=max_replans, max_tool_calls=30, deadline_s=300)
    gate = Gate(fail_next_write=interrupt_write)

    extra_checks, extra_sources = planner.plan(llm, trace, goal=GOAL, alert_id=case.id,
                                               window=_window(case), policy=policy)
    contract = build_contract(case_id=case.id, account_id=case.account_id, tenant_id=case.tenant_id,
                              window_start=case.window_start, window_end=case.window_end,
                              planner_checks=extra_checks, planner_sources=extra_sources, policy=policy)
    trace.add("planner", "contract", version=contract.version, checks=list(contract.checks),
              sources=list(contract.required_sources))
    contract_text = (f"\nDefinition of done (frozen v{contract.version}): evidence sources "
                     f"{list(contract.required_sources)} must each return status ok; every claim must cite evidence; "
                     f"numeric claims are recomputed by code; the conclusion must satisfy the policy.")
    if playbook:
        contract_text += "\n\nINVESTIGATOR PLAYBOOK:\n" + playbook

    run = RunRecord("C3", case.id, Outcome.INSUFFICIENT_EVIDENCE, False, [])
    repair = None
    for attempt in range(max_replans + 1):
        rec, _ = investigator.run(llm, tb, store, guard, trace, alert_id=case.id, email=case.email,
                                  window=_window(case), system_extra=contract_text, repair_note=repair, registry=registry)
        rec = rec or Recommendation(outcome=Outcome.INSUFFICIENT_EVIDENCE, claims=[])
        run.recommendation = rec
        evidence = list(store.values())
        ver = verify(contract=contract, policy=policy, evidence=evidence, recommendation=rec,
                     contradictions=detect_contradictions(evidence), phase="pre_commit")
        trace.add("verifier", "verify", passed=ver.passed,
                  failures=[{"check": f.check, "reason": f.reason} for f in ver.failures])
        run.verification = ver
        if ver.passed and rec.outcome in CLOSURE_OUTCOMES:
            receipt = _commit(gate, ver, case, rec.outcome, contract.version, f"{case.id}:{contract.version}")
            post = verify(contract=contract, policy=policy, evidence=evidence, recommendation=rec,
                          receipt=receipt, phase="post_commit")
            trace.add("gate", "commit", outcome=rec.outcome.value, receipt=receipt.id, post_passed=post.passed)
            if post.passed:
                run.outcome, run.claimed_complete, run.receipt = rec.outcome, True, receipt
                break
        if rec.outcome in CLOSURE_OUTCOMES and not ver.passed:   # the refusal moment
            try:
                gate.commit_disposition(verification=ver, case_id=case.id, outcome=rec.outcome,
                                        contract_version=contract.version, idempotency_key="probe")
            except GateRefused as e:
                run.refusals.append(str(e))
                trace.add("gate", "refused", outcome=rec.outcome.value, reason=str(e))
        att = attributor.attribute(llm, trace.steps, ver.failures)
        if att:
            run.attributions.append(att)
            trace.add("attributor", "attribution", agent=att.agent, blamed_step=att.step, category=att.category.value)
        if guard.record_replan() == GuardDecision.STOP:
            break
        run.replans += 1
        repair = "\n".join(f"- {f.check}: {f.reason}" for f in ver.failures)
        evidence_checks = {"required_evidence", "correct_account", "window_covered"}
        if att:
            repair += f"\nAttribution: the failure traces to step {att.step} ({att.category.value})."
        if any(f.check in evidence_checks for f in ver.failures):
            repair += "\nRe-collect only the failing source(s); keep evidence that is already ok."
        else:
            try:
                feats = dataclasses.asdict(compute_sequence_features([r for r in store.values()]))
                repair += f"\nFeatures computed by code from this evidence: {feats}"
            except IncompleteEvidence:
                pass
            repair += ("\nThe evidence listed above is complete and correct. Do NOT call tools again. Re-read it and give a "
                       "corrected final answer that satisfies the failed checks, citing evidence for every claim.")
    else:
        pass

    if not run.claimed_complete:                                  # no closure: degrade honestly, never "benign"
        last = {r.source: r.status for r in store.values()}
        errored = any(last.get(s) == EvidenceStatus.ERROR for s in contract.required_sources)
        outcome = Outcome.COLLECTION_FAILED if errored else Outcome.INSUFFICIENT_EVIDENCE
        run.receipt = _commit(gate, run.verification, case, outcome, contract.version, f"{case.id}:final")
        run.outcome = outcome
        trace.add("gate", "commit", outcome=outcome.value, receipt=run.receipt.id)
    run.evidence, run.cost_usd, run.latency_s = list(store.values()), ledger.total_usd - c0, time.monotonic() - t0
    return run
