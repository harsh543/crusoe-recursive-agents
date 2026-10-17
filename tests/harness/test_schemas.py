"""E4: every agent output is schema-constrained. Schemas are tied to the code's own enums so they cannot drift."""
import httpx
import openai
import pytest

from casefile.attribution import Attribution, Category
from casefile.contract import CHECKS
from casefile.cost import CostLedger, Price
from casefile.llm import LLM
from casefile.models import Outcome
from casefile.records.models import ClaimType, Verdict
from casefile.schemas import (ATTRIBUTION, CRITIC, INTAKE, INVESTIGATOR_STEP, PLANNER, records_step_schema)
from casefile.trace import Trace
from types import SimpleNamespace


def strict_objects(node):
    """Every object schema in the tree must forbid extra keys (except the explicit free-form params bag)."""
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            assert node.get("additionalProperties") is False, node
            assert set(node.get("required", [])) <= set(node["properties"]), node
        for v in node.values():
            strict_objects(v)
    elif isinstance(node, list):
        for v in node:
            strict_objects(v)


@pytest.mark.parametrize("schema", [PLANNER, ATTRIBUTION, CRITIC, INVESTIGATOR_STEP, records_step_schema(False), records_step_schema(True)])
def test_schemas_are_strict_objects(schema):
    strict_objects(schema)


def test_enums_come_from_the_codes_own_constants():
    assert PLANNER["properties"]["planner_checks"]["items"]["enum"] == sorted(CHECKS)
    assert set(ATTRIBUTION["properties"]["agent"]["enum"]) == set(Attribution.model_fields["agent"].annotation.__args__)
    assert ATTRIBUTION["properties"]["category"]["enum"] == [c.value for c in Category]
    final = next(b for b in INVESTIGATOR_STEP["anyOf"] if b["properties"]["action"].get("const") == "final")
    assert set(final["properties"]["outcome"]["enum"]) == {Outcome.CLOSED_BENIGN, Outcome.ESCALATED, Outcome.INSUFFICIENT_EVIDENCE}
    claim_types = INTAKE["properties"]["claims"]["items"]["properties"]["claim_type"]["enum"]
    assert set(claim_types) == {c.value for c in ClaimType}


def test_records_final_verdicts_include_out_of_scope_only_for_baselines():
    def verdicts(s):
        return set(next(b for b in s["anyOf"] if b["properties"]["action"].get("const") == "final")["properties"]["verdict"]["enum"])
    assert Verdict.OUT_OF_SCOPE not in verdicts(records_step_schema(False))
    assert Verdict.OUT_OF_SCOPE in verdicts(records_step_schema(True))


def test_investigator_tools_in_the_schema_match_the_registry_tool_names():
    from casefile.agents.investigator import INVESTIGATOR_TOOLS
    names = {b["properties"]["tool"]["const"] for b in INVESTIGATOR_STEP["anyOf"] if "tool" in b["properties"]}
    assert names == set(INVESTIGATOR_TOOLS)


# ---- LLM layer passes the schema and falls back if the API rejects it ----------------------------------------------
class RecordingCrusoe:
    def __init__(self, reject_schema=False):
        self.calls, self.reject_schema = [], reject_schema

    def chat(self, model, messages, max_tokens=1024, **kw):
        self.calls.append(kw)
        if self.reject_schema and "response_format" in kw:
            raise openai.BadRequestError("unsupported schema", response=httpx.Response(400, request=httpx.Request("POST", "http://x")), body=None)
        msg = SimpleNamespace(content='{"ok": true}', model_dump=lambda: {"content": '{"ok": true}'})
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, prompt_tokens_details=SimpleNamespace(cached_tokens=0))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")], usage=usage)


def llm_with(crusoe):
    return LLM(crusoe, CostLedger({"m": Price(1, 1, 1)}), Trace(), {"r": "m"})


def test_schema_is_sent_as_strict_json_schema_response_format():
    c = RecordingCrusoe()
    llm_with(c).call_json("r", [{"role": "user", "content": "x"}], schema=CRITIC)
    rf = c.calls[0]["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True and rf["json_schema"]["schema"] == CRITIC


def test_an_api_that_rejects_the_schema_triggers_one_logged_fallback_without_it():
    c, llm = RecordingCrusoe(reject_schema=True), None
    llm = llm_with(c)
    assert llm.call_json("r", [{"role": "user", "content": "x"}], schema=CRITIC) == {"ok": True}
    assert "response_format" not in c.calls[-1] and any(s["kind"] == "schema_fallback" for s in llm.trace.steps)
    llm.call_json("r", [{"role": "user", "content": "x"}], schema=CRITIC)          # remembered: no second rejected attempt
    assert sum("response_format" in k for k in c.calls) == 1
