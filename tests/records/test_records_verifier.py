"""Claim-level checks, all in code. Each test names the failure it prevents."""
import pytest

from casefile.records.models import ClaimType, RecordClaim, Verdict
from casefile.records.verifier import verify_claim
from tests.records.conftest import ENTITY, F, GAP_FINDINGS, doc, docs, gap_claim, result  # noqa: F401


def failed(r):
    return {f.check for f in r.failures}


def test_date_gap_supported_when_recomputation_matches(docs):
    assert verify_claim(gap_claim(), result(Verdict.SUPPORTED, GAP_FINDINGS), docs).passed


def test_supported_verdict_is_wrong_when_recomputed_gap_differs(docs):
    r = verify_claim(gap_claim(days=10), result(Verdict.SUPPORTED, GAP_FINDINGS), docs)
    assert "computation_correct" in failed(r)
    assert verify_claim(gap_claim(days=10), result(Verdict.CONTRADICTED, GAP_FINDINGS), docs).passed


def test_comparison_operators(docs):
    assert verify_claim(gap_claim(days=30, comparison="<="), result(Verdict.SUPPORTED, GAP_FINDINGS), docs).passed
    assert "computation_correct" in failed(
        verify_claim(gap_claim(days=5, comparison="<="), result(Verdict.SUPPORTED, GAP_FINDINGS), docs))


def test_date_gap_accepts_dates_written_as_month_names(docs):
    findings = [
        F("formation_date", "February 3, 2025", "Date of formation: February 3, 2025", "d_reg"),
        F("award_date", "February 14, 2025", "Award date: February 14, 2025", "d_award"),
    ]
    natural_docs = {
        **docs,
        "d_reg": doc("d_reg", docs["d_reg"].text.replace("2025-02-03", "February 3, 2025")),
        "d_award": doc("d_award", docs["d_award"].text.replace("2025-02-14", "February 14, 2025"),
                       publisher="Federal Award Database"),
    }

    assert verify_claim(gap_claim(), result(Verdict.SUPPORTED, findings), natural_docs).passed


def test_missing_inputs_force_insufficient_evidence(docs):
    only_one = GAP_FINDINGS[:1]
    assert "computation_correct" in failed(verify_claim(gap_claim(), result(Verdict.SUPPORTED, only_one), docs))
    assert verify_claim(gap_claim(), result(Verdict.INSUFFICIENT_EVIDENCE, only_one), docs).passed


def test_fabricated_quote_fails(docs):
    bad = [F("formation_date", "2025-02-03", "Date of formation: 2025-02-01", "d_reg"), GAP_FINDINGS[1]]
    assert "quotes_verbatim" in failed(verify_claim(gap_claim(), result(Verdict.SUPPORTED, bad), docs))


def test_quote_match_ignores_case_and_whitespace(docs):
    ok = [F("formation_date", "2025-02-03", "date  of FORMATION:\n2025-02-03", "d_reg"), GAP_FINDINGS[1]]
    assert verify_claim(gap_claim(), result(Verdict.SUPPORTED, ok), docs).passed


def test_unknown_document_fails(docs):
    bad = [F("formation_date", "2025-02-03", "x", "d_missing"), GAP_FINDINGS[1]]
    assert "quotes_verbatim" in failed(verify_claim(gap_claim(), result(Verdict.SUPPORTED, bad), docs))


def test_supported_requires_at_least_one_finding(docs):
    assert "quotes_verbatim" in failed(verify_claim(gap_claim(), result(Verdict.SUPPORTED, []), docs))


def test_lookalike_entity_document_fails_entity_match(docs):
    look = [F("formation_date", "2019-05-01", "Date of formation: 2019-05-01", "d_look"), GAP_FINDINGS[1]]
    r = verify_claim(gap_claim(), result(Verdict.CONTRADICTED, look), docs)
    assert "entity_match" in failed(r)
    assert "Holdings" in next(f.reason for f in r.failures if f.check == "entity_match")


def test_total_amount_recomputed_by_code(docs):
    claim = RecordClaim(id="c1", text="Two awards totalled 220 million.", attributed_to="Official A",
                        claim_type=ClaimType.AMOUNT, params={"claimed_total": 220_000_000})
    fs = [F("award_amount", "$143,000,000", "Award amount: $143,000,000", "d_award"),
          F("award_amount", "$77,000,000", "Award amount: $77,000,000", "d_award2")]
    assert verify_claim(claim, result(Verdict.SUPPORTED, fs), docs).passed
    wrong = claim.model_copy(update={"params": {"claimed_total": 300_000_000}})
    assert "computation_correct" in failed(verify_claim(wrong, result(Verdict.SUPPORTED, fs), docs))
    assert verify_claim(wrong, result(Verdict.CONTRADICTED, fs), docs).passed


def test_competition_status_comes_from_the_record(docs):
    f = [F("extent_competed", "NOT COMPETED", "Extent competed: NOT COMPETED", "d_award")]
    base = dict(id="c1", text="The award was not competed.", attributed_to="Official A",
                claim_type=ClaimType.COMPETITION_STATUS)
    yes = RecordClaim(**base, params={"claimed_status": "not_competed", "entity_canonical": ENTITY})
    no = RecordClaim(**base, params={"claimed_status": "competed", "entity_canonical": ENTITY})
    assert verify_claim(yes, result(Verdict.SUPPORTED, f), docs).passed
    assert "computation_correct" in failed(verify_claim(no, result(Verdict.SUPPORTED, f), docs))
    assert verify_claim(no, result(Verdict.CONTRADICTED, f), docs).passed


def test_competition_status_accepts_schema_style_underscore(docs):
    f = [F("extent_competed", "not_competed", "Extent competed: NOT COMPETED", "d_award")]
    claim = RecordClaim(id="c1", text="The award was not competed.", attributed_to="Official A",
                        claim_type=ClaimType.COMPETITION_STATUS,
                        params={"claimed_status": "not_competed", "entity_canonical": ENTITY})

    assert verify_claim(claim, result(Verdict.SUPPORTED, f), docs).passed


def _rel_claim():
    return RecordClaim(id="c1", text="The firm was new at award time.", attributed_to="Official A",
                       claim_type=ClaimType.OTHER, params={"entity_canonical": ENTITY})


def test_single_secondary_source_is_not_enough(docs):
    f = [F("age", "new", f"{ENTITY} was formed eleven days before award", "d_n1")]
    assert "source_adequate" in failed(verify_claim(_rel_claim(), result(Verdict.SUPPORTED, f), docs))


def test_two_independent_publishers_are_enough(docs):
    f = [F("age", "new", f"{ENTITY} was formed eleven days before award", "d_n1"),
         F("age", "new", f"{ENTITY} was a new company at award time", "d_n2")]
    assert verify_claim(_rel_claim(), result(Verdict.SUPPORTED, f), docs).passed


def test_two_articles_from_the_same_publisher_do_not_count_as_independent(docs):
    f = [F("age", "new", f"{ENTITY} was formed eleven days before award", "d_n1"),
         F("age", "new", f"{ENTITY} was new", "d_n1b")]
    assert "source_adequate" in failed(verify_claim(_rel_claim(), result(Verdict.SUPPORTED, f), docs))


def test_primary_source_alone_is_enough(docs):
    f = [F("formation_date", "2025-02-03", "Date of formation: 2025-02-03", "d_reg")]
    claim = _rel_claim().model_copy(update={"params": {"entity_canonical": ENTITY}})
    assert "source_adequate" not in failed(verify_claim(claim, result(Verdict.SUPPORTED, f), docs))


def test_conflicting_values_must_be_acknowledged(docs):
    conflicting = [GAP_FINDINGS[0], GAP_FINDINGS[1],
                   F("award_date", "2025-02-20", "Award date: 2025-02-14", "d_award2")]
    quiet = verify_claim(gap_claim(), result(Verdict.SUPPORTED, conflicting), docs)
    assert "conflicts_addressed" in failed(quiet)
    loud = verify_claim(gap_claim(), result(Verdict.SUPPORTED, conflicting, conflicts=["award_date"]), docs)
    assert "conflicts_addressed" not in failed(loud)


def test_wrongdoing_vocabulary_in_the_explanation_fails(docs):
    r = verify_claim(gap_claim(), result(Verdict.SUPPORTED, GAP_FINDINGS, "This shows fraud by Vendor B."), docs)
    assert "neutral_language" in failed(r)


def test_wrongdoing_words_inside_a_quote_are_allowed(docs):
    expl = 'Official A said, "this looks like fraud", which is an allegation, not a finding.'
    assert verify_claim(gap_claim(), result(Verdict.SUPPORTED, GAP_FINDINGS, expl), docs).passed


@pytest.mark.parametrize("claim_type,private", [(ClaimType.LEGAL_CONCLUSION, False), (ClaimType.RELATIONSHIP, True)])
def test_out_of_scope_claims_are_not_researched(docs, claim_type, private):
    c = RecordClaim(id="c1", text="x", attributed_to="Official A", claim_type=claim_type,
                    subject_private_individual=private)
    assert "scope_respected" in failed(verify_claim(c, result(Verdict.SUPPORTED, GAP_FINDINGS), docs))
    assert "scope_respected" in failed(verify_claim(c, result(Verdict.OUT_OF_SCOPE, GAP_FINDINGS), docs))  # findings = researched
    assert verify_claim(c, result(Verdict.OUT_OF_SCOPE, []), docs).passed


def test_in_scope_claim_cannot_be_dodged_as_out_of_scope(docs):
    assert "scope_respected" in failed(verify_claim(gap_claim(), result(Verdict.OUT_OF_SCOPE, []), docs))


def test_claims_must_carry_an_attribution():
    with pytest.raises(Exception):
        RecordClaim(id="c1", text="x", attributed_to="", claim_type=ClaimType.OTHER)


def test_irrelevant_cited_document_does_not_fail_entity_match_when_another_names_the_entity(docs):
    """Citing the prime award (which never names the subcontractor) next to the subaward report is fine."""
    claim = RecordClaim(id="c1", text="Most funds went to Harbor.", attributed_to="Official A",
                        claim_type=ClaimType.OTHER, params={"entity_canonical": "Lakeshore Ads Inc."})
    fs = [F("award_amount", "$77,000,000", "Award amount: $77,000,000", "d_award2"),
          F("award_amount", "$143,000,000", "Award amount: $143,000,000", "d_award")]
    assert "entity_match" not in failed(verify_claim(claim, result(Verdict.SUPPORTED, fs), docs))


def test_entity_absent_from_every_cited_document_fails(docs):
    claim = RecordClaim(id="c1", text="x", attributed_to="Official A", claim_type=ClaimType.OTHER,
                        params={"entity_canonical": "Harbor Strategy Group LLC"})
    fs = [F("award_amount", "$143,000,000", "Award amount: $143,000,000", "d_award")]
    assert "entity_match" in failed(verify_claim(claim, result(Verdict.SUPPORTED, fs), docs))


def test_quote_failure_shows_the_closest_real_line(docs):
    bad = [F("formation_date", "2025-02-03", "Date of formation 3 Feb 2025", "d_reg"), GAP_FINDINGS[1]]
    r = verify_claim(gap_claim(), result(Verdict.SUPPORTED, bad), docs)
    assert "Date of formation: 2025-02-03" in next(f.reason for f in r.failures if f.check == "quotes_verbatim")


def test_numeric_finding_values_are_accepted_as_text():
    assert F("award_amount", 143000000, "Award amount: $143,000,000", "d_award").value == "143000000"


def test_numeric_award_amount_matches_a_formatted_quote(docs):
    """The model may give 143000000 while the document says $143,000,000: compare numbers, not substrings."""
    claim = RecordClaim(id="c1", text="Two awards totalled 220 million.", attributed_to="Official A",
                        claim_type=ClaimType.AMOUNT, params={"claimed_total": 220_000_000})
    fs = [F("award_amount", 143000000, "Award amount: $143,000,000", "d_award"),
          F("award_amount", 77000000.0, "Award amount: $77,000,000", "d_award2")]
    assert verify_claim(claim, result(Verdict.SUPPORTED, fs), docs).passed
    wrong = [F("award_amount", 150000000, "Award amount: $143,000,000", "d_award"), fs[1]]
    assert "quotes_verbatim" in failed(verify_claim(claim, result(Verdict.CONTRADICTED, wrong), docs))


def test_money_scale_words_are_normalized_before_comparison(docs):
    claim = RecordClaim(id="c1", text="The award was $143 million.", attributed_to="Official A",
                        claim_type=ClaimType.AMOUNT, params={"claimed_total": 143_000_000})
    findings = [F("award_amount", "$143 million", "Award amount: $143,000,000", "d_award")]

    assert verify_claim(claim, result(Verdict.SUPPORTED, findings), docs).passed


def test_flow_through_with_scale_words_is_recomputed_as_a_ratio(docs):
    claim = RecordClaim(id="c1", text="At least half went to the subcontractor.",
                        attributed_to="Official A", claim_type=ClaimType.FLOW_THROUGH,
                        params={"entity_canonical": ENTITY, "claimed_share_min": 0.5})
    findings = [
        F("prime_total", "$143 million", "Award amount: $143,000,000", "d_award"),
        F("subaward_total", "$77 million", "Award amount: $77,000,000", "d_award2"),
    ]

    assert verify_claim(claim, result(Verdict.SUPPORTED, findings), docs).passed


def test_flow_through_rejects_reversed_prime_and_subaward_amounts(docs):
    claim = RecordClaim(id="c1", text="Most of the award went to the subcontractor.",
                        attributed_to="Official A", claim_type=ClaimType.FLOW_THROUGH,
                        params={"entity_canonical": ENTITY, "claimed_share_min": 0.5})
    inverted = [
        F("prime_total", "$77,000,000", "Award amount: $77,000,000", "d_award2"),
        F("subaward_total", "$143,000,000", "Award amount: $143,000,000", "d_award"),
    ]

    r = verify_claim(claim, result(Verdict.SUPPORTED, inverted), docs)

    assert "computation_correct" in failed(r)
    assert "fields may be reversed" in next(f.reason for f in r.failures if f.check == "computation_correct")


def test_flow_through_amount_must_appear_in_its_quote(docs):
    claim = RecordClaim(id="c1", text="Some of the award went to the subcontractor.",
                        attributed_to="Official A", claim_type=ClaimType.FLOW_THROUGH,
                        params={"entity_canonical": ENTITY, "claimed_share_min": 0.001})
    findings = [
        F("prime_total", "$143,000,000", "Award amount: $143,000,000", "d_award"),
        F("subaward_total", "$226,137.17", "Extent competed: NOT COMPETED", "d_award"),
    ]

    assert "quotes_verbatim" in failed(verify_claim(claim, result(Verdict.SUPPORTED, findings), docs))
