"""Sources (integrity + swap-ability), Gate, and the report."""
import hashlib

import pytest
from pydantic import ValidationError

from casefile.gate import GateRefused, WriteInterrupted
from casefile.records.gate import RecordsGate
from casefile.records.models import DocType, Document, Verdict
from casefile.records.neutrality import lint
from casefile.records.pseudonym import Pseudonymizer
from casefile.records.report import render_markdown
from casefile.records.sources import EvidenceSource, FixtureSource
from casefile.records.verifier import verify_claim
from tests.records.conftest import AWARD, DOCS, ENTITY, GAP_FINDINGS, NOW, REG, docs, gap_claim, result  # noqa: F401


def test_document_integrity_is_enforced_on_construction():
    with pytest.raises(ValidationError):
        Document(id="x", url="https://e.test/x", doc_type=DocType.PRIMARY, title="t", publisher="p",
                 retrieved_at=NOW, sha256="0" * 64, text="tampered")


def test_fixture_source_search_ranks_by_term_overlap_and_fetches_by_id_or_url():
    src = FixtureSource(list(DOCS.values()))
    assert isinstance(src, EvidenceSource)
    assert src.search("Date of formation Northwind Signal Media", k=1)[0].id == "d_reg"
    assert src.fetch("d_award").id == "d_award" and src.fetch(AWARD.url).id == "d_award"
    with pytest.raises(KeyError):
        src.fetch("https://example.test/nope")


def _passed(docs):
    return verify_claim(gap_claim(), result(Verdict.SUPPORTED, GAP_FINDINGS), docs)


def _failed(docs):
    return verify_claim(gap_claim(days=10), result(Verdict.SUPPORTED, GAP_FINDINGS), docs)


def test_gate_writes_closure_verdicts_only_after_verification(docs):
    g = RecordsGate()
    assert g.commit(verification=_passed(docs), claim_id="c1", verdict=Verdict.SUPPORTED, idempotency_key="k1").written
    with pytest.raises(GateRefused):
        g.commit(verification=_failed(docs), claim_id="c2", verdict=Verdict.SUPPORTED, idempotency_key="k2")
    assert len(g.writes) == 1


@pytest.mark.parametrize("v", [Verdict.INSUFFICIENT_EVIDENCE, Verdict.COLLECTION_FAILED, Verdict.OUT_OF_SCOPE])
def test_non_closure_verdicts_need_no_passing_verification(docs, v):
    assert RecordsGate().commit(verification=_failed(docs), claim_id="c1", verdict=v, idempotency_key="k").written


def test_gate_is_idempotent_allowlisted_and_retryable(docs):
    g = RecordsGate(fail_next_write=True)
    with pytest.raises(WriteInterrupted):
        g.commit(verification=_passed(docs), claim_id="c1", verdict=Verdict.SUPPORTED, idempotency_key="k1")
    a = g.commit(verification=_passed(docs), claim_id="c1", verdict=Verdict.SUPPORTED, idempotency_key="k1")
    b = g.commit(verification=_passed(docs), claim_id="c1", verdict=Verdict.SUPPORTED, idempotency_key="k1")
    assert a.id == b.id and len(g.writes) == 1
    with pytest.raises(GateRefused):
        g.commit(verification=_passed(docs), claim_id="c1", verdict="guilty", idempotency_key="k9")


MAPPING = {ENTITY: "Contractor B", "Official A (hearing)": "Official A (hearing)"}


def _report(reveal=False):
    return render_markdown(title="Illustrative case file", claims=[gap_claim()],
                           results=[result(Verdict.SUPPORTED, GAP_FINDINGS)], docs=DOCS,
                           pseudonyms=Pseudonymizer(MAPPING), reveal=reveal)


def test_report_has_no_real_names_by_default_and_reveals_on_toggle():
    assert ENTITY not in _report() and "Contractor B" in _report()
    assert ENTITY in _report(reveal=True)


def test_report_states_it_is_not_a_legal_finding_and_attributes_claims():
    text = _report()
    assert "Not a legal finding" in text and "Official A (hearing)" in text
    assert "supported" in text.lower() and "Date of formation: 2025-02-03" in text


def test_report_text_outside_quotes_passes_the_neutrality_lint():
    assert lint(_report()) == []
