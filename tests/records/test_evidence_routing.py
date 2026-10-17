import pytest

from casefile.records.evidence_routing import EvidenceRole, EvidenceRoute, EvidenceTopic, route_evidence


@pytest.mark.parametrize("topic", [EvidenceTopic.ISSUER_FINANCIALS, EvidenceTopic.MARKET_DATA])
def test_issuer_finance_fails_closed_without_verified_identifier(topic):
    decision = route_evidence(topic)
    assert decision.route == EvidenceRoute.YOU_FINANCE
    assert decision.role == EvidenceRole.NOT_ELIGIBLE
    assert not decision.eligible


def test_verified_issuer_can_use_finance_with_as_of_provenance():
    decision = route_evidence(EvidenceTopic.ISSUER_FINANCIALS, verified_cik="0000123456")
    assert decision.route == EvidenceRoute.YOU_FINANCE
    assert decision.role == EvidenceRole.EVIDENCE
    assert "0000123456" in decision.reason
    assert "SEC EDGAR" in decision.system_of_record


def test_name_only_issuer_identity_check_is_a_lead_not_evidence():
    decision = route_evidence(EvidenceTopic.ISSUER_IDENTITY)
    assert decision.route == EvidenceRoute.YOU_FINANCE
    assert decision.role == EvidenceRole.LEAD_ONLY
    assert "exact legal entity" in decision.reason


def test_nonprofit_finance_requires_underlying_return_or_audit():
    decision = route_evidence(EvidenceTopic.NONPROFIT_FINANCIALS)
    assert decision.route == EvidenceRoute.YOU_FINANCE
    assert decision.role == EvidenceRole.LEAD_ONLY
    assert "Form 990" in decision.reason
    assert "IRS" in decision.system_of_record


@pytest.mark.parametrize(
    ("topic", "system_fragment"),
    [
        (EvidenceTopic.PROCUREMENT, "USAspending"),
        (EvidenceTopic.GRANTS, "state auditor"),
        (EvidenceTopic.CAMPAIGN_FINANCE, "FEC"),
        (EvidenceTopic.CORPORATE_REGISTRATION, "Secretary of State"),
        (EvidenceTopic.CRIMINAL_OR_COURT, "DOJ"),
        (EvidenceTopic.REGULATORY_POLICY, "regulator"),
    ],
)
def test_nonissuer_topics_use_search_then_exact_url_contents(topic, system_fragment):
    decision = route_evidence(topic)
    assert decision.route == EvidenceRoute.YOU_SEARCH_CONTENTS
    assert decision.role == EvidenceRole.EVIDENCE
    assert system_fragment in decision.system_of_record
    assert "exact URL" in decision.reason


def test_unknown_topic_is_rejected_instead_of_guessed():
    with pytest.raises(ValueError):
        route_evidence("general_due_diligence")
