"""Planner: one-line goal -> allowlisted checks. Sees typed metadata only, never raw customer text."""
from ..errors import BudgetExceeded
from ..schemas import PLANNER
from ..contract import CHECKS, MANDATORY_CHECKS, UnknownCheckError

PLANNER_TOOLS = ("get_policy",)
DEFAULT_OPTIONAL = ["window_covered", "contradictions_addressed"]

SYSTEM = f"""You are the Planner in a fraud case system. Turn the goal into a definition of done.
Allowed checks (choose only from these): {sorted(CHECKS)}.
The policy already forces these checks and you cannot remove them: {sorted(MANDATORY_CHECKS)}.
Reply with JSON only: {{"planner_checks": [<extra checks to add>], "planner_sources": [<extra evidence sources, optional>]}}"""


def plan(llm, trace, *, goal: str, alert_id: str, window: str, policy):
    user = (f"Goal: {goal}\nAlert: {alert_id}\nWindow: {window}\n"
            f"Policy {policy.version} requires evidence sources: {list(policy.required_sources)}")
    last = None
    for _ in range(2):
        try:
            out = llm.call_json("planner", [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                                max_tokens=1024, schema=PLANNER)
            checks = [c for c in out.get("planner_checks", [])]
            if set(checks) - CHECKS:
                raise UnknownCheckError(sorted(set(checks) - CHECKS))
            return checks, [str(s) for s in out.get("planner_sources", [])]
        except BudgetExceeded:
            raise                          # a spent budget is never swallowed by the fallback
        except Exception as e:           # invalid plan: retry once, then fall back to defaults (recorded)
            last = e
    trace.add("planner", "fallback", reason=f"{type(last).__name__}: {last}")
    return list(DEFAULT_OPTIONAL), []
