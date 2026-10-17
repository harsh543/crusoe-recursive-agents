"""Records loop against a scripted model: control flow, repair, scope handling, pseudonyms."""
import pytest

from casefile.records.agents.intake import enforce_scope
from casefile.records.gate import RecordsGate
from casefile.records.models import ClaimType, RecordClaim, Verdict
from casefile.records.orchestrator import build_pseudonymizer, run_case_file, verify_one
from casefile.records.sources import FixtureSource
from casefile.trace import Trace
from tests.fakes import FakeLLM
from tests.records.conftest import DOCS, ENTITY, gap_claim


def tool(name, **a):
    return {"action": "tool", "tool": name, "args": a}


def final(verdict, findings, explanation="Recomputed from the cited records."):
    return {"action": "final", "verdict": verdict, "findings": findings, "explanation": explanation, "conflicts": []}


GOOD = [{"field": "formation_date", "value": "2025-02-03", "quote": "Date of formation: 2025-02-03", "doc_id": "d_reg"},
        {"field": "award_date", "value": "2025-02-14", "quote": "Award date: 2025-02-14", "doc_id": "d_award"}]
BAD_QUOTE = [{**GOOD[0], "quote": "Date of formation: 2025-02-01"}, GOOD[1]]
SRC = FixtureSource(list(DOCS.values()))


def test_fabricated_quote_is_refused_then_repaired():
    llm = FakeLLM({"records_investigator": [
        tool("read_document", doc_id="d_reg"), tool("read_document", doc_id="d_award"),
        final("supported", BAD_QUOTE), final("supported", GOOD)],
        "attributor": [{"agent": "investigator", "step": "s001", "category": "task_verification"}]})
    t = Trace()
    run = verify_one(gap_claim(), SRC, llm, t, RecordsGate())
    assert run.result.verdict == Verdict.SUPPORTED and run.claimed_complete and run.replans == 1
    assert len(run.refusals) == 1 and "quote" in run.refusals[0]


def test_wrong_verdict_is_refused_even_with_valid_quotes():
    llm = FakeLLM({"records_investigator": [
        tool("read_document", doc_id="d_reg"), tool("read_document", doc_id="d_award"),
        final("contradicted", GOOD), final("supported", GOOD)],
        "attributor": [{"agent": "investigator", "step": "s001", "category": "task_verification"}]})
    run = verify_one(gap_claim(), SRC, llm, Trace(), RecordsGate())
    assert run.result.verdict == Verdict.SUPPORTED and run.replans == 1


def test_missing_documents_degrade_to_collection_failed_never_supported():
    llm = FakeLLM({"records_investigator": [tool("read_document", doc_id="nope"), final("insufficient_evidence", []),
                                            final("insufficient_evidence", []), final("insufficient_evidence", [])],
                   "attributor": [{"agent": "investigator", "step": "s001", "category": "task_verification"}] * 3,
                   "attributor_escalate": [{"agent": "investigator", "step": "s001", "category": "task_verification"}] * 3})
    run = verify_one(gap_claim(), SRC, llm, Trace(), RecordsGate())
    assert run.result.verdict in (Verdict.COLLECTION_FAILED, Verdict.INSUFFICIENT_EVIDENCE)
    assert not run.claimed_complete and run.receipt.written


def test_out_of_scope_claims_are_never_researched():
    llm = FakeLLM({})                                    # any model call would raise AssertionError
    c = RecordClaim(id="c7", text='A commentator called it a "fraudulent scheme".', attributed_to="A commentator",
                    claim_type=ClaimType.LEGAL_CONCLUSION)
    run = verify_one(c, SRC, llm, Trace(), RecordsGate())
    assert run.result.verdict == Verdict.OUT_OF_SCOPE and llm.calls == []


@pytest.mark.parametrize("text,expect_type,expect_private", [
    ("This was a fraudulent scheme to enrich insiders.", ClaimType.LEGAL_CONCLUSION, False),
    ("The chief executive is married to the former spokesperson.", ClaimType.OTHER, True),
    ("The award date was 2025-02-14.", ClaimType.OTHER, False)])
def test_code_enforces_scope_regardless_of_what_the_model_said(text, expect_type, expect_private):
    c = enforce_scope(RecordClaim(id="c", text=text, attributed_to="X", claim_type=ClaimType.OTHER))
    assert (c.claim_type, c.subject_private_individual) == (expect_type, expect_private)


def test_full_pipeline_scripted_with_pseudonymized_report():
    intake = {"entities": [{"name": ENTITY, "kind": "company"}, {"name": "Senator Hale", "kind": "official"}],
              "claims": [{"id": "c1", "text": f"{ENTITY} was formed 11 days before the award.", "attributed_to": "Senator Hale",
                          "claim_type": "date_gap", "params": gap_claim().params},
                         {"id": "c2", "text": "It was a fraudulent scheme.", "attributed_to": "A commentator", "claim_type": "other"}]}
    llm = FakeLLM({"intake": [intake], "records_investigator": [
        tool("read_document", doc_id="d_reg"), tool("read_document", doc_id="d_award"), final("supported", GOOD)]})
    claims, entities, skipped, runs, pseudo, _ = run_case_file("case", SRC, llm, Trace())
    assert [r.result.verdict for r in runs] == [Verdict.SUPPORTED, Verdict.OUT_OF_SCOPE]
    from casefile.records.report import render_markdown
    report = render_markdown(title="t", claims=claims, results=[r.result for r in runs], docs=DOCS, pseudonyms=pseudo)
    assert pseudo.leaks(report) == []
    assert ENTITY not in report and "Senator Hale" not in report
    assert "Contractor A" in report and "Official A" in report


def test_pseudonymizer_assigns_distinct_aliases_and_short_forms():
    claims = [gap_claim()]
    p = build_pseudonymizer([{"name": "Senator Hale", "kind": "official"}, {"name": "Lakeshore Ads Inc.", "kind": "company"}], claims)
    assert p.apply("Northwind Signal Media LLC and Northwind Signal Media and Lakeshore Ads Inc. and Senator Hale") == \
        "Contractor B and Contractor B and Contractor A and Official A"
    assert p.leaks(p.apply("Northwind Signal Media, Lakeshore Ads Inc., Senator Hale")) == []


RULE = RecordClaim(id="c8", text="Federal rules allow skipping competition when there is an urgency.", attributed_to="Senator Hale",
                   claim_type=ClaimType.RULE_TEXT)
RULE_FINDING = [{"field": "rule_text", "value": "urgency exception", "doc_id": "d_reg",
                 "quote": "Date of formation: 2025-02-03"}]


def test_abstaining_without_reading_any_document_is_refused_then_repaired():
    llm = FakeLLM({"records_investigator": [final("insufficient_evidence", []), tool("search_documents", query="urgency"),
                                            tool("read_document", doc_id="d_reg"), final("supported", RULE_FINDING)],
                   "attributor": [{"agent": "investigator", "step": "s001", "category": "task_verification"}] * 2,
                   "attributor_escalate": [{"agent": "investigator", "step": "s001", "category": "task_verification"}] * 2})
    t = Trace()
    run = verify_one(RULE, SRC, llm, t, RecordsGate())
    assert run.replans == 1 and run.result.verdict == Verdict.SUPPORTED
    assert any("research_done" in str(s.get("failures")) for s in t.steps if s["kind"] == "verify")


def test_rereading_a_document_already_in_context_is_not_treated_as_a_loop():
    llm = FakeLLM({"records_investigator": [tool("read_document", doc_id="d_reg"), tool("read_document", doc_id="d_reg"),
                                            tool("read_document", doc_id="d_reg"), final("supported", RULE_FINDING)]})
    run = verify_one(RULE, SRC, llm, Trace(), RecordsGate())
    assert run.result.verdict == Verdict.SUPPORTED and run.replans == 0
