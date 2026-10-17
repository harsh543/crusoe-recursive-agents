"""Fail-closed routing for You.com evidence enrichment.

The finance index is useful for issuer identity checks, SEC filings, market data,
and nonprofit financial leads.  It is not a substitute for the public system of
record for contracts, grants, campaign finance, registrations, cases, or rules.
"""

from dataclasses import dataclass
from enum import StrEnum


class EvidenceTopic(StrEnum):
    ISSUER_IDENTITY = "issuer_identity"
    ISSUER_FINANCIALS = "issuer_financials"
    MARKET_DATA = "market_data"
    NONPROFIT_FINANCIALS = "nonprofit_financials"
    PROCUREMENT = "procurement"
    GRANTS = "grants"
    CAMPAIGN_FINANCE = "campaign_finance"
    CORPORATE_REGISTRATION = "corporate_registration"
    CRIMINAL_OR_COURT = "criminal_or_court"
    REGULATORY_POLICY = "regulatory_policy"


class EvidenceRoute(StrEnum):
    YOU_FINANCE = "you-finance"
    YOU_SEARCH_CONTENTS = "you-search+you-contents"


class EvidenceRole(StrEnum):
    EVIDENCE = "evidence"
    LEAD_ONLY = "lead_only"
    NOT_ELIGIBLE = "not_eligible"


@dataclass(frozen=True)
class RoutingDecision:
    route: EvidenceRoute
    role: EvidenceRole
    reason: str
    system_of_record: str

    @property
    def eligible(self) -> bool:
        return self.role != EvidenceRole.NOT_ELIGIBLE


_PRIMARY_ROUTES = {
    EvidenceTopic.PROCUREMENT: "USAspending, SAM.gov, and the agency award file",
    EvidenceTopic.GRANTS: "the awarding agency, state auditor, and grant records",
    EvidenceTopic.CAMPAIGN_FINANCE: "FEC or the relevant state campaign-finance system",
    EvidenceTopic.CORPORATE_REGISTRATION: "the relevant Secretary of State or national corporate registry",
    EvidenceTopic.CRIMINAL_OR_COURT: "DOJ, the court docket, and filed case documents",
    EvidenceTopic.REGULATORY_POLICY: "the issuing regulator, legislature, or standards body",
}


def route_evidence(
    topic: EvidenceTopic | str,
    *,
    verified_ticker: str | None = None,
    verified_cik: str | None = None,
) -> RoutingDecision:
    """Choose the enrichment tool and state what can count as evidence.

    A ticker or CIK is "verified" only when exact legal-entity matching has been
    checked against an authoritative issuer record.  Search absence is never
    evidence that an entity is privately held.
    """
    topic = EvidenceTopic(topic)
    identifier = (verified_cik or verified_ticker or "").strip()

    if topic == EvidenceTopic.ISSUER_IDENTITY:
        return RoutingDecision(
            EvidenceRoute.YOU_FINANCE,
            EvidenceRole.LEAD_ONLY,
            "Use finance search to propose a ticker or CIK, then verify the exact legal entity in SEC EDGAR or the relevant exchange record.",
            "SEC EDGAR or the relevant securities regulator/exchange",
        )

    if topic in {EvidenceTopic.ISSUER_FINANCIALS, EvidenceTopic.MARKET_DATA}:
        if not identifier:
            return RoutingDecision(
                EvidenceRoute.YOU_FINANCE,
                EvidenceRole.NOT_ELIGIBLE,
                "Issuer-level finance enrichment requires a previously verified ticker or CIK; a name-only or empty match must fail closed.",
                "SEC EDGAR, audited issuer filings, and the relevant exchange",
            )
        return RoutingDecision(
            EvidenceRoute.YOU_FINANCE,
            EvidenceRole.EVIDENCE,
            f"Query the verified issuer identifier {identifier!r}; retain the filing or market source URL and the as-of period for every value.",
            "SEC EDGAR, audited issuer filings, and the relevant exchange",
        )

    if topic == EvidenceTopic.NONPROFIT_FINANCIALS:
        return RoutingDecision(
            EvidenceRoute.YOU_FINANCE,
            EvidenceRole.LEAD_ONLY,
            "Finance research may locate Form 990s and audit reports, but line items count only after the underlying return or audit is opened and preserved.",
            "IRS Tax Exempt Organization Search, the filed Form 990, or the signed audit report",
        )

    system = _PRIMARY_ROUTES[topic]
    return RoutingDecision(
        EvidenceRoute.YOU_SEARCH_CONTENTS,
        EvidenceRole.EVIDENCE,
        "Discover an actual primary-source URL with search, then extract that exact URL; do not use finance synthesis as a substitute.",
        system,
    )

