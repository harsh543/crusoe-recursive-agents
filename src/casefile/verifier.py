"""Code-first verifier. Pass/fail comes from these functions, never from a model."""
from dataclasses import dataclass, field

from .features import IncompleteEvidence, compute_sequence_features, recompute
from .models import CLOSURE_OUTCOMES, EvidenceStatus


@dataclass(frozen=True)
class Failure:
    check: str
    reason: str
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerificationResult:
    failures: tuple[Failure, ...] = field(default_factory=tuple)
    phase: str = "pre_commit"

    @property
    def passed(self) -> bool:
        return not self.failures


def verify(*, contract, policy, evidence, recommendation, contradictions=(), receipt=None,
           phase="pre_commit") -> VerificationResult:
    fails: list[Failure] = []
    scoped = [r for r in evidence if r.account_id == contract.account_id and r.tenant_id == contract.tenant_id]
    by_id = {r.id: r for r in evidence}
    closure = recommendation.outcome in CLOSURE_OUTCOMES
    checks = set(contract.checks)

    if "correct_account" in checks:
        for r in evidence:
            if r.account_id != contract.account_id or r.tenant_id != contract.tenant_id:
                fails.append(Failure("correct_account",
                                     f"{r.source} record {r.id} belongs to {r.account_id}/{r.tenant_id}, "
                                     f"case is {contract.account_id}/{contract.tenant_id}", (r.id,)))

    missing_sources = []
    if "required_evidence" in checks:
        for src in contract.required_sources:
            recs = [r for r in scoped if r.source == src]
            if not any(r.status == EvidenceStatus.OK for r in recs):
                status = recs[-1].status.value if recs else "missing"
                missing_sources.append(src)
                fails.append(Failure("required_evidence",
                                     f"{src} status={status}; re-collect {src} (an error, empty or partial "
                                     f"result is not evidence of nothing suspicious)", tuple(r.id for r in recs)))

    if "window_covered" in checks:
        for src in contract.required_sources:
            ok = [r for r in scoped if r.source == src and r.status == EvidenceStatus.OK]
            if ok and (min(r.covers_from for r in ok) > contract.window_start
                       or max(r.covers_to for r in ok) < contract.window_end):
                fails.append(Failure("window_covered",
                                     f"{src} does not cover {contract.window_start:%Y-%m-%d}..{contract.window_end:%Y-%m-%d}",
                                     tuple(r.id for r in ok)))

    if "claims_supported" in checks:
        if closure and not recommendation.claims:
            fails.append(Failure("claims_supported", "closure outcome has no cited claims"))
        usable = [r for r in scoped if r.status == EvidenceStatus.OK]
        for c in recommendation.claims:
            for eid in c.evidence_ids:
                r = by_id.get(eid)
                if r is None:
                    fails.append(Failure("claims_supported", f"claim {c.id} cites unknown evidence {eid}", (eid,)))
                elif r.status != EvidenceStatus.OK:
                    fails.append(Failure("claims_supported",
                                         f"claim {c.id} cites {eid} ({r.source}) with status={r.status.value}", (eid,)))
            if c.numeric is not None:
                actual = recompute(c.numeric.metric, usable)
                if abs(actual - c.numeric.value) > 0.01:
                    fails.append(Failure("claims_supported",
                                         f"claim {c.id}: {c.numeric.metric} recomputes to {actual}, claimed {c.numeric.value}",
                                         tuple(c.evidence_ids)))

    if "policy_followed" in checks:
        if closure:
            try:
                expected = policy.decide(compute_sequence_features([r for r in scoped if r.status == EvidenceStatus.OK]))
                if expected != recommendation.outcome:
                    fails.append(Failure("policy_followed",
                                         f"policy {policy.version} gives {expected.value}, recommendation is "
                                         f"{recommendation.outcome.value}"))
            except IncompleteEvidence as e:
                fails.append(Failure("policy_followed", f"cannot evaluate policy: {e}"))
        elif not missing_sources and "required_evidence" in checks:
            fails.append(Failure("policy_followed",
                                 f"{recommendation.outcome.value} claimed but all required sources are ok"))

    if "contradictions_addressed" in checks:
        for x in contradictions:
            if x.resolution is None:
                fails.append(Failure("contradictions_addressed", f"contradiction {x.id} unresolved", tuple(x.evidence_ids)))

    if phase == "post_commit" and "result_persisted" in checks:
        if receipt is None or not receipt.idempotency_key:
            fails.append(Failure("result_persisted", "no receipt with an idempotency key"))
        elif receipt.outcome != recommendation.outcome:
            fails.append(Failure("result_persisted",
                                 f"receipt outcome {receipt.outcome.value} differs from {recommendation.outcome.value}"))

    return VerificationResult(failures=tuple(fails), phase=phase)
