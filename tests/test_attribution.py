"""FR-12: failure attribution is schema-validated and scored by exact match (never substring)."""
import pytest
from pydantic import ValidationError

from casefile.attribution import Attribution, Category, attribution_accuracy, score_attribution


def attr(agent="investigator", step="s003", cat=Category.TASK_VERIFICATION):
    return Attribution(agent=agent, step=step, category=cat)


def test_exact_agent_and_step_match():
    assert score_attribution(attr(), attr())


def test_substring_step_is_not_a_match():
    assert not score_attribution(attr(step="s003"), attr(step="s0031"))
    assert not score_attribution(attr(step="s0031"), attr(step="s003"))


def test_wrong_agent_is_wrong_even_with_right_step():
    assert not score_attribution(attr(agent="planner"), attr(agent="investigator"))


def test_unknown_agent_name_fails_validation():
    with pytest.raises(ValidationError):
        Attribution(agent="the investigator agent, probably", step="s003",
                    category=Category.SPECIFICATION)


def test_category_is_one_of_three():
    assert {c.value for c in Category} == {
        "specification", "inter_agent_misalignment", "task_verification"}


def test_accuracy_over_a_list():
    preds = [attr(step="s1"), attr(step="s2"), attr(step="s3"), attr(step="s4")]
    truth = [attr(step="s1"), attr(step="s2"), attr(step="s9"), attr(agent="gate", step="s4")]
    assert attribution_accuracy(preds, truth) == pytest.approx(0.5)


def test_accuracy_rejects_empty_or_mismatched_lists():
    with pytest.raises(ValueError):
        attribution_accuracy([], [])
    with pytest.raises(ValueError):
        attribution_accuracy([attr()], [attr(), attr()])


def test_attributor_escalates_to_larger_model_when_output_invalid():
    from casefile.agents.attributor import attribute
    from casefile.verifier import Failure
    from tests.fakes import FakeLLM

    steps = [{"step": "s003", "role": "investigator", "kind": "tool", "tool": "get_device_history", "status": "error"}]
    llm = FakeLLM({
        "attributor": [{"agent": "nobody", "step": "s003", "category": "specification"}],
        "attributor_escalate": [{"agent": "investigator", "step": "s003", "category": "task_verification"}],
    })
    a = attribute(llm, steps, [Failure("required_evidence", "device_history status=error")])
    assert (a.agent, a.step) == ("investigator", "s003")
    assert [r for r, _ in llm.calls] == ["attributor", "attributor_escalate"]


def test_attributor_rejects_a_step_id_not_in_the_trace():
    from casefile.agents.attributor import attribute
    from casefile.verifier import Failure
    from tests.fakes import FakeLLM

    steps = [{"step": "s003", "role": "investigator", "kind": "tool", "tool": "x", "status": "error"}]
    bad = {"agent": "investigator", "step": "s099", "category": "specification"}
    llm = FakeLLM({"attributor": [bad], "attributor_escalate": [bad]})
    assert attribute(llm, steps, [Failure("c", "r")]) is None
