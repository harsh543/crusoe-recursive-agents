"""Per-claim loop: investigate -> code verify -> gate; on failure attribute and repair; degrade honestly. No LLM controls flow."""
import time
from dataclasses import dataclass, field

from ..agents import attributor
from ..gate import GateRefused
from ..loop_guard import GuardDecision, LoopGuard
from ..verifier import Failure, VerificationResult
from .agents import intake
from .agents import investigator as inv
from .gate import RecordsGate
from .models import CLOSURE_VERDICTS, OUT_OF_SCOPE_TYPES, ClaimResult, Verdict
from .pseudonym import Pseudonymizer
from .verifier import verify_claim


@dataclass
class ClaimRun:
    claim: object
    result: ClaimResult
    verification: object
    receipt: object = None
    replans: int = 0
    attributions: list = field(default_factory=list)
    refusals: list = field(default_factory=list)
    claimed_complete: bool = False


def _out_of_scope(c) -> bool:
    return c.claim_type in OUT_OF_SCOPE_TYPES or c.subject_private_individual


def verify_one(claim, source, llm, trace, gate, *, max_replans=2) -> ClaimRun:
    """Investigate and verify a single claim with the full Casefile loop."""
    if _out_of_scope(claim):                                    # decided by code; never researched
        res = ClaimResult(claim_id=claim.id, verdict=Verdict.OUT_OF_SCOPE,
                          explanation="Attributed statement; not verifiable from public records.")
        ver = verify_claim(claim, res, {})
        rec = gate.commit(verification=ver, claim_id=claim.id, verdict=res.verdict, idempotency_key=f"{claim.id}:oos")
        trace.add("gate", "commit", claim=claim.id, verdict=res.verdict.value)
        return ClaimRun(claim, res, ver, rec)

    store, guard = {}, LoopGuard(max_replans=max_replans, max_tool_calls=14, deadline_s=240)
    run = ClaimRun(claim, ClaimResult(claim_id=claim.id, verdict=Verdict.INSUFFICIENT_EVIDENCE), None)
    repair, collection_errors = None, 0
    for _ in range(max_replans + 1):
        res, errs = inv.run(llm, source, claim, store, guard, trace, repair_note=repair)
        collection_errors += errs
        if res is None:
            res = ClaimResult(claim_id=claim.id, verdict=Verdict.INSUFFICIENT_EVIDENCE)
        ver = verify_claim(claim, res, store)
        if res.verdict == Verdict.INSUFFICIENT_EVIDENCE and not store and collection_errors == 0:
            ver = VerificationResult(failures=ver.failures + (Failure(
                "research_done", "abstained without reading any document; search and read at least one before concluding insufficient_evidence"),),
                phase=ver.phase)
        trace.add("verifier", "verify", claim=claim.id, passed=ver.passed,
                  failures=[{"check": f.check, "reason": f.reason} for f in ver.failures])
        run.result, run.verification = res, ver
        if ver.passed and res.verdict in CLOSURE_VERDICTS:
            run.receipt = gate.commit(verification=ver, claim_id=claim.id, verdict=res.verdict, idempotency_key=f"{claim.id}:v")
            run.claimed_complete = True
            trace.add("gate", "commit", claim=claim.id, verdict=res.verdict.value)
            return run
        if res.verdict in CLOSURE_VERDICTS and not ver.passed:
            try:
                gate.commit(verification=ver, claim_id=claim.id, verdict=res.verdict, idempotency_key=f"{claim.id}:probe")
            except GateRefused as e:
                run.refusals.append(str(e))
                trace.add("gate", "refused", claim=claim.id, verdict=res.verdict.value, reason=str(e)[:300])
        if res.verdict == Verdict.INSUFFICIENT_EVIDENCE and ver.passed:   # justified: documents really do not settle it
            run.receipt = gate.commit(verification=ver, claim_id=claim.id, verdict=res.verdict, idempotency_key=f"{claim.id}:ins")
            trace.add("gate", "commit", claim=claim.id, verdict=res.verdict.value)
            return run
        att = attributor.attribute(llm, trace.steps, ver.failures)
        if att:
            run.attributions.append(att)
            trace.add("attributor", "attribution", claim=claim.id, agent=att.agent, blamed_step=att.step, category=att.category.value)
        if guard.record_replan() == GuardDecision.STOP:
            break
        run.replans += 1
        repair = "\n".join(f"- {f.check}: {f.reason}" for f in ver.failures)
        repair += "\nRe-read the documents above (already supplied) and answer again; fetch more only if something is missing."
    verdict = Verdict.COLLECTION_FAILED if (collection_errors and not store) else Verdict.INSUFFICIENT_EVIDENCE
    run.result = ClaimResult(claim_id=claim.id, verdict=verdict,
                             explanation="Could not be verified from the available records within the allowed attempts.")
    run.verification = verify_claim(claim, run.result, store)
    run.receipt = gate.commit(verification=run.verification, claim_id=claim.id, verdict=verdict, idempotency_key=f"{claim.id}:final")
    trace.add("gate", "commit", claim=claim.id, verdict=verdict.value)
    return run


def build_pseudonymizer(entities, claims, runs=()) -> Pseudonymizer:
    """Aliases are assigned by code from intake entities; shorter variants (no LLC/Inc) map to the same alias."""
    mapping, counters = {}, {"official": 0, "company": 0, "person": 0, "committee": 0}
    prefix = {"official": "Official", "company": "Contractor", "person": "Person", "committee": "Body"}
    names = [(e.get("name", ""), e.get("kind", "person")) for e in entities]
    names += [(c.params["entity_canonical"], "company") for c in claims if c.params.get("entity_canonical")]
    for name, kind in names:
        name = name.strip()
        if not name or name in mapping:
            continue
        kind = kind if kind in prefix else "person"
        counters[kind] += 1
        alias = f"{prefix[kind]} {chr(64 + counters[kind])}"
        mapping[name] = alias
        short = name
        for suf in (" LLC", " Inc.", " Inc", " Corp.", " Corp", " Ltd.", " LLP"):
            short = short.removesuffix(suf)
        if short != name:
            mapping.setdefault(short, alias)
    return Pseudonymizer(mapping)


def run_case_file(case_text, source, llm, trace, *, max_replans=2):
    """Full pipeline for an uploaded case file. Returns (claims, entities, skipped, runs, pseudonymizer, seconds)."""
    t0 = time.monotonic()
    claims, entities, skipped = intake.run(llm, case_text)
    trace.add("intake", "claims", n=len(claims), skipped=skipped)
    gate = RecordsGate()
    runs = [verify_one(c, source, llm, trace, gate, max_replans=max_replans) for c in claims]
    return claims, entities, skipped, runs, build_pseudonymizer(entities, claims), time.monotonic() - t0
