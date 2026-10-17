"""Benchmark baselines for the records mode. No code verifier, no gate: whatever the model concludes is the answer."""
import json

from ..loop_guard import LoopGuard
from .agents import investigator as inv
from .models import ClaimResult, Verdict

CRITIC_SYSTEM = """You review one verification of an attributed statement against documents.
Decide whether the verdict is well supported by the quotes and documents. Reply with JSON only:
{"approve": true|false, "reason": "..."}"""


def run_single_claim(claim, source, llm, trace, *, store=None, repair_note=None):
    store = {} if store is None else store
    guard = LoopGuard(max_replans=0, max_tool_calls=14, deadline_s=240)
    res, _ = inv.run(llm, source, claim, store, guard, trace, repair_note=repair_note, allow_scope=True)
    return res or ClaimResult(claim_id=claim.id, verdict=Verdict.INSUFFICIENT_EVIDENCE), store


def run_critic_claim(claim, source, llm, trace):
    res, store = run_single_claim(claim, source, llm, trace)
    docs = "\n".join(f'<doc id="{d.id}" publisher="{d.publisher}">{d.text}</doc>' for d in store.values())
    user = (f"Statement ({claim.attributed_to}): {claim.text}\nVerdict: {res.verdict.value}\nExplanation: {res.explanation}\n"
            f"Findings: {json.dumps([f.model_dump() for f in res.findings])}\nDocuments read:\n{docs}")
    out = llm.call_json("critic", [{"role": "system", "content": CRITIC_SYSTEM}, {"role": "user", "content": user}], max_tokens=1024)
    approve, reason = bool(out.get("approve")), str(out.get("reason", ""))
    trace.add("critic", "review", claim=claim.id, approve=approve, reason=reason[:200])
    if not approve:
        res, store = run_single_claim(claim, source, llm, trace, store=store, repair_note=f"A reviewer rejected your answer: {reason}")
    return res, store
