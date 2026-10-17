"""Catches drifting and looping: repeats without new evidence, re-plan cap, tool-call ceiling, deadline."""
import json
import time
from enum import StrEnum


class GuardDecision(StrEnum):
    CONTINUE = "continue"
    FORCE_REPLAN = "force_replan"
    STOP = "stop"


class LoopGuard:
    def __init__(self, max_replans=2, max_tool_calls=20, deadline_s=120.0, clock=time.monotonic):
        self.max_replans, self.max_tool_calls, self.deadline_s, self.clock = (
            max_replans, max_tool_calls, deadline_s, clock)
        self._start = clock()
        self._seen: set[str] = set()
        self.calls = 0
        self.replans = 0
        self.stop_reason: str | None = None

    def _stop(self, reason):
        self.stop_reason = reason
        return GuardDecision.STOP

    def record_tool_call(self, tool, args, new_evidence_ids) -> GuardDecision:
        self.calls += 1
        if self.clock() - self._start > self.deadline_s:
            return self._stop("deadline")
        if self.calls > self.max_tool_calls:
            return self._stop("tool-call ceiling")
        key = f"{tool}:{json.dumps(args, sort_keys=True, default=str)}"
        repeat = key in self._seen
        self._seen.add(key)
        return GuardDecision.FORCE_REPLAN if repeat and not new_evidence_ids else GuardDecision.CONTINUE

    def record_replan(self) -> GuardDecision:
        self.replans += 1
        return GuardDecision.CONTINUE if self.replans <= self.max_replans else self._stop("re-plan cap")
