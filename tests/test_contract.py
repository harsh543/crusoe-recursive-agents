"""FR-01..03: allowlisted checks, mandatory checks, immutability, versioning."""
import pytest
from pydantic import ValidationError

from casefile.contract import (
    CHECKS, MANDATORY_CHECKS, ContractViolation, UnknownCheckError, build_contract,
)
from tests.conftest import W0, W1


def _build(policy, **kw):
    args = dict(case_id="A-104", account_id="acct_104", tenant_id="t1",
                window_start=W0, window_end=W1, planner_checks=[], policy=policy)
    args.update(kw)
    return build_contract(**args)


def test_planner_cannot_remove_mandatory_checks(policy):
    c = _build(policy, planner_checks=[])
    assert set(MANDATORY_CHECKS) <= set(c.checks)


def test_unknown_check_is_rejected(policy):
    with pytest.raises(UnknownCheckError):
        _build(policy, planner_checks=["trust_me"])


def test_all_known_checks_are_accepted(policy):
    c = _build(policy, planner_checks=sorted(CHECKS))
    assert set(c.checks) == set(CHECKS)


def test_policy_required_sources_cannot_be_dropped(policy):
    c = _build(policy, planner_sources=[])
    assert {"device_history", "transactions"} <= set(c.required_sources)


def test_contract_is_frozen(contract):
    with pytest.raises((ValidationError, TypeError)):
        contract.checks = ()


def test_revise_creates_new_version_and_keeps_original(contract):
    v2 = contract.revise(required_sources=(*contract.required_sources, "kyc_profile"))
    assert (contract.version, v2.version) == (1, 2)
    assert "kyc_profile" not in contract.required_sources


def test_revise_cannot_drop_mandatory_check(contract):
    with pytest.raises(ContractViolation):
        contract.revise(checks=("window_covered",))


def test_revise_cannot_drop_required_source(contract):
    with pytest.raises(ContractViolation):
        contract.revise(required_sources=("transactions",))
