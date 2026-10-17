"""LLM critic: the BASELINE reviewer (configuration C2). It is never the gate in Casefile."""
import json

from ..schemas import CRITIC

SYSTEM = """You review a fraud investigator's work. Decide if the conclusion is well supported.
Reply with JSON only: {"approve": true|false, "reason": "..."}"""


def review(llm, messages, recommendation):
    transcript = [m for m in messages if m["role"] != "system"]
    user = (f"Investigation transcript:\n{json.dumps(transcript)}\n\nFinal conclusion: "
            f"{recommendation.outcome.value}; claims: {[c.text for c in recommendation.claims]}")
    out = llm.call_json("critic", [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                        max_tokens=1024, schema=CRITIC)
    return bool(out.get("approve")), str(out.get("reason", ""))
