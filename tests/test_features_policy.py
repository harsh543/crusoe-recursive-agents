"""FR-04, FR-19: sequence features and policy. A-104 escalates; the lookalike A-105 must not."""
import pytest

from casefile.features import IncompleteEvidence, compute_sequence_features, detect_contradictions
from casefile.models import Outcome
from tests.conftest import a104_device, a104_tx, a105_device, a105_tx, ev


def test_a104_features():
    f = compute_sequence_features([a104_device(), a104_tx()])
    assert f.new_device_foreign is True
    assert f.mfa_reset_after_new_device is True
    assert f.test_charge_count == 3
    assert f.new_beneficiary is True
    assert f.largest_transfer == 4800.0


def test_a105_features():
    f = compute_sequence_features([a105_device(), a105_tx()])
    assert f.new_device_foreign is False
    assert f.mfa_reset_after_new_device is False
    assert f.test_charge_count == 0
    assert f.new_beneficiary is True      # the lookalike signal that must NOT trigger escalation
    assert f.payroll_seen is True


def test_policy_escalates_a104(policy):
    assert policy.decide(compute_sequence_features([a104_device(), a104_tx()])) == Outcome.ESCALATED


def test_policy_closes_a105_benign(policy):
    assert policy.decide(compute_sequence_features([a105_device(), a105_tx()])) == Outcome.CLOSED_BENIGN


def test_new_beneficiary_alone_does_not_escalate(policy):
    """'Escalate everything unfamiliar' must not look like success."""
    f = compute_sequence_features([a105_device(), a105_tx()])
    assert f.new_beneficiary and policy.decide(f) != Outcome.ESCALATED


@pytest.mark.parametrize("status", ["error", "empty", "partial", "stale"])
def test_features_refuse_incomplete_evidence(status):
    """Missing data must never become 'no signals'."""
    with pytest.raises(IncompleteEvidence):
        compute_sequence_features([a104_device(status=status), a104_tx()])


def test_policy_declares_required_sources_and_version(policy):
    assert set(policy.required_sources) == {"device_history", "transactions"}
    assert policy.version


def test_conflicting_device_timestamps_are_a_contradiction():
    second = ev("ev_dev2", "device_history", data={
        "home_country": "US",
        "devices": [{"id": "d2", "country": "RO", "first_seen": "2026-09-19T10:00:00Z", "known": False}],
        "mfa_resets": [],
    })
    found = detect_contradictions([a104_device(), second])
    assert len(found) == 1
    assert set(found[0].evidence_ids) == {"ev_dev", "ev_dev2"}
    assert found[0].resolution is None


def test_no_contradiction_when_records_agree():
    assert detect_contradictions([a104_device(), a104_tx()]) == []
