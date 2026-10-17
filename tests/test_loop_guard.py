"""FR-11: repeated calls without new evidence force a re-plan; ceilings stop the run."""
import pytest

from casefile.loop_guard import GuardDecision, LoopGuard


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def guard(clock):
    return LoopGuard(max_replans=2, max_tool_calls=10, deadline_s=60, clock=clock)


def test_first_call_continues(guard):
    assert guard.record_tool_call("get_device_history", {"account_id": "a"}, []) == GuardDecision.CONTINUE


def test_same_call_without_new_evidence_forces_replan(guard):
    guard.record_tool_call("get_device_history", {"account_id": "a"}, [])
    d = guard.record_tool_call("get_device_history", {"account_id": "a"}, [])
    assert d == GuardDecision.FORCE_REPLAN


def test_same_call_with_new_evidence_continues(guard):
    guard.record_tool_call("get_transactions", {"account_id": "a"}, ["ev1"])
    d = guard.record_tool_call("get_transactions", {"account_id": "a"}, ["ev2"])
    assert d == GuardDecision.CONTINUE


def test_argument_order_does_not_hide_a_repeat(guard):
    guard.record_tool_call("t", {"a": 1, "b": 2}, [])
    assert guard.record_tool_call("t", {"b": 2, "a": 1}, []) == GuardDecision.FORCE_REPLAN


def test_different_arguments_are_not_a_repeat(guard):
    guard.record_tool_call("get_device_history", {"account_id": "email@x.com"}, [])
    d = guard.record_tool_call("get_device_history", {"account_id": "acct_104"}, [])
    assert d == GuardDecision.CONTINUE


def test_at_most_two_replans(guard):
    assert guard.record_replan() == GuardDecision.CONTINUE
    assert guard.record_replan() == GuardDecision.CONTINUE
    assert guard.record_replan() == GuardDecision.STOP


def test_tool_call_ceiling_stops(guard):
    decisions = [guard.record_tool_call("t", {"i": i}, [f"e{i}"]) for i in range(11)]
    assert decisions[:10] == [GuardDecision.CONTINUE] * 10
    assert decisions[10] == GuardDecision.STOP


def test_deadline_stops(guard, clock):
    clock.t = 61.0
    assert guard.record_tool_call("t", {}, ["e"]) == GuardDecision.STOP
