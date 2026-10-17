"""Pseudonymized synthetic documents modeled on a public-procurement structure. Not real filings."""
import hashlib
from datetime import datetime, timezone

import pytest

from casefile.records.models import ClaimResult, ClaimType, DocType, Document, Finding, RecordClaim, Verdict

NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)
ENTITY = "Northwind Signal Media LLC"


def doc(id, text, doc_type=DocType.PRIMARY, publisher="State Registry", title="t"):
    return Document(id=id, url=f"https://example.test/{id}", doc_type=doc_type, title=title, publisher=publisher,
                    retrieved_at=NOW, sha256=hashlib.sha256(text.encode()).hexdigest(), text=text)


REG = doc("d_reg", f"Entity: {ENTITY}\nFile number: 7788\nDate of formation: 2025-02-03\nStatus: Active")
AWARD = doc("d_award", f"Recipient: {ENTITY}\nAward date: 2025-02-14\nAward amount: $143,000,000\n"
                       "Extent competed: NOT COMPETED\nNote: urgent need exception cited", publisher="Federal Award Database")
AWARD2 = doc("d_award2", "Recipient: Lakeshore Ads Inc.\nAward amount: $77,000,000", publisher="Federal Award Database")
LOOKALIKE = doc("d_look", "Entity: Northwind Signal Holdings LLC\nDate of formation: 2019-05-01")
NEWS1 = doc("d_n1", f"Outlet One reports that {ENTITY} was formed eleven days before award.",
            DocType.SECONDARY, publisher="Outlet One")
NEWS2 = doc("d_n2", f"Outlet Two confirms {ENTITY} was a new company at award time.",
            DocType.SECONDARY, publisher="Outlet Two")
NEWS1B = doc("d_n1b", f"Outlet One follow-up: {ENTITY} was new.", DocType.SECONDARY, publisher="Outlet One")
DOCS = {d.id: d for d in [REG, AWARD, AWARD2, LOOKALIKE, NEWS1, NEWS2, NEWS1B]}


def F(field, value, quote, doc_id):
    return Finding(field=field, value=value, quote=quote, doc_id=doc_id)


GAP_FINDINGS = [F("formation_date", "2025-02-03", "Date of formation: 2025-02-03", "d_reg"),
                F("award_date", "2025-02-14", "Award date: 2025-02-14", "d_award")]


def gap_claim(days=11, comparison="=="):
    return RecordClaim(id="c1", text="Contractor B was formed 11 days before the award.", attributed_to="Official A (hearing)",
                       claim_type=ClaimType.DATE_GAP,
                       params={"entity_canonical": ENTITY, "a": "formation_date", "b": "award_date",
                               "days": days, "comparison": comparison})


def result(verdict, findings=(), explanation="Recomputed from the cited records.", conflicts=()):
    return ClaimResult(claim_id="c1", verdict=verdict, findings=list(findings), explanation=explanation,
                       conflicts=list(conflicts))


@pytest.fixture
def docs():
    return dict(DOCS)
