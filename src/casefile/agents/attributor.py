"""Attributor: names the agent and step that broke. Output is schema-validated; invalid output escalates once."""
import json

from pydantic import ValidationError

from ..attribution import Attribution
from ..schemas import ATTRIBUTION as ATTRIBUTION_SCHEMA

SYSTEM = """You attribute failures in a multi-agent fraud investigation. You are given the tool steps taken and the
failed completion checks. Name the ONE agent and the ONE decisive step that caused the failure.
agent must be one of: planner, investigator, verifier, gate. step must be a step id from the list (like s003).
category: specification (wrong/missing requirement), inter_agent_misalignment (wrong hand-off), or
task_verification (a result was accepted or produced without being checked).
Reply with JSON only: {"agent": "...", "step": "sNNN", "category": "..."}"""


def attribute(llm, trace_steps, failures):
    steps = [s for s in trace_steps if s["kind"] == "tool"]
    user = (f"Steps:\n{json.dumps(steps, default=str)}\n\nFailed checks:\n"
            + json.dumps([{"check": f.check, "reason": f.reason} for f in failures]))
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    valid_steps = {s["step"] for s in steps}
    for role in ("attributor", "attributor_escalate"):       # Lightning first, escalate only if invalid
        try:
            out = llm.call_json(role, msgs, max_tokens=1024, schema=ATTRIBUTION_SCHEMA)
            a = Attribution(**out)
            if a.step in valid_steps:
                return a
        except (ValidationError, TypeError, ValueError):
            continue
    return None
