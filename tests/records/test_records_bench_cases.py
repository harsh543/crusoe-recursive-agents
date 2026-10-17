"""The generator, the labels and the verifier must agree: a perfect agent passes verification on every case."""
import pytest

from casefile.bench.records_cases import FAULTS, build_case, split_cases
from casefile.records.models import Verdict
from casefile.records.verifier import verify_claim


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
@pytest.mark.parametrize("fault", FAULTS)
def test_ideal_answers_pass_the_verifier_and_match_labels(seed, fault):
    case = build_case(seed, fault)
    docs = {d.id: d for d in case.docs}
    for c in case.claims:
        ideal = case.ideal[c.id]
        assert ideal.verdict.value == case.expected[c.id]
        r = verify_claim(c, ideal, docs)
        assert r.passed, (case.id, c.id, [f.reason for f in r.failures])


def test_cases_are_deterministic_and_cover_every_verdict():
    assert build_case(0, "none").casefile == build_case(0, "none").casefile
    seen = {v for s in range(6) for f in FAULTS for v in build_case(s, f).expected.values()}
    assert seen == {"supported", "contradicted", "insufficient_evidence", "out_of_scope"}


def test_faults_change_the_expected_answer_where_intended():
    assert build_case(0, "missing_doc").expected["c1"] == "insufficient_evidence"
    assert build_case(0, "lookalike_entity").expected["c1"] == "insufficient_evidence"
    assert build_case(0, "off_by_one").expected["c1"] == "contradicted"


def test_a_wrong_but_fluent_answer_on_the_lookalike_case_is_refused():
    case = build_case(0, "lookalike_entity")
    docs = {d.id: d for d in case.docs}
    from casefile.records.models import ClaimResult, Finding
    reg = docs["d_reg"]
    wrong = ClaimResult(claim_id="c1", verdict=Verdict.SUPPORTED, explanation="Matches the registry.", findings=[
        Finding(field="formation_date", value=reg.text.split("Date of formation: ")[1][:10], quote="Date of formation: " + reg.text.split("Date of formation: ")[1][:10], doc_id="d_reg"),
        case.ideal["c2"].findings[0].model_copy(update={"field": "award_date", "value": "2025-01-01", "quote": "Award date: " + docs["d_award"].text.split("Award date: ")[1][:10]})])
    assert not verify_claim(case.claims[0], wrong, docs).passed


def test_dev_and_heldout_are_disjoint():
    assert {c.id for c in split_cases("dev")}.isdisjoint({c.id for c in split_cases("heldout")})
