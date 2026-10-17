"""FR-09/10: the Gate is the only writer; it refuses unverified closure; writes are idempotent."""
import pytest

from casefile.gate import Gate, GateRefused, WriteInterrupted
from casefile.models import Outcome
from casefile.verifier import verify
from tests.conftest import a104_device, a104_tx


def commit(gate, verification, outcome=Outcome.ESCALATED, key="k1"):
    return gate.commit_disposition(
        verification=verification, case_id="A-104", outcome=outcome,
        contract_version=1, idempotency_key=key,
    )


@pytest.fixture
def passed(good):
    return verify(**good)


@pytest.fixture
def failed(good):
    good["evidence"] = [a104_device(status="error"), a104_tx()]
    return verify(**good)


def test_commits_escalation_after_passing_verification(passed):
    gate = Gate()
    r = commit(gate, passed)
    assert r.written and r.outcome == Outcome.ESCALATED
    assert len(gate.writes) == 1


@pytest.mark.parametrize("outcome", [Outcome.CLOSED_BENIGN, Outcome.ESCALATED])
def test_refuses_closure_when_verification_failed(failed, outcome):
    gate = Gate()
    with pytest.raises(GateRefused):
        commit(gate, failed, outcome)
    assert gate.writes == []


@pytest.mark.parametrize("outcome", [Outcome.INSUFFICIENT_EVIDENCE, Outcome.COLLECTION_FAILED])
def test_non_closure_outcomes_do_not_need_a_passing_verification(failed, outcome):
    gate = Gate()
    assert commit(gate, failed, outcome).written
    assert len(gate.writes) == 1


def test_refuses_actions_outside_the_allowlist(passed):
    gate = Gate()
    with pytest.raises(GateRefused):
        commit(gate, passed, outcome="refund_customer")
    assert gate.writes == []


def test_same_idempotency_key_writes_once_and_returns_same_receipt(passed):
    gate = Gate()
    first = commit(gate, passed, key="k1")
    second = commit(gate, passed, key="k1")
    assert first.id == second.id
    assert len(gate.writes) == 1


def test_different_keys_write_separately(passed):
    gate = Gate()
    commit(gate, passed, key="k1")
    commit(gate, passed, key="k2")
    assert len(gate.writes) == 2


def test_interrupted_write_is_retryable_with_one_final_write(passed):
    gate = Gate(fail_next_write=True)
    with pytest.raises(WriteInterrupted):
        commit(gate, passed, key="k1")
    assert gate.writes == []
    receipt = commit(gate, passed, key="k1")
    assert receipt.written and len(gate.writes) == 1
