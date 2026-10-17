"""JSON schemas for every agent output (sent as strict response_format). Enums come from the code's own constants.
A schema guarantees SYNTAX only; truth is still checked by the code verifier."""
from .attribution import Attribution, Category
from .contract import CHECKS
from .models import Outcome
from .records.models import ClaimType, Verdict


def obj(props: dict, required: list | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required if required is not None else list(props),
            "additionalProperties": False}


STR = {"type": "string"}
STR_LIST = {"type": "array", "items": STR}

PLANNER = obj({"planner_checks": {"type": "array", "items": {"enum": sorted(CHECKS)}}, "planner_sources": STR_LIST})
ATTRIBUTION = obj({"agent": {"enum": list(Attribution.model_fields["agent"].annotation.__args__)}, "step": STR,
                   "category": {"enum": [c.value for c in Category]}})
CRITIC = obj({"approve": {"type": "boolean"}, "reason": STR})


def _tool(name: str, args: dict) -> dict:
    return obj({"action": {"const": "tool"}, "tool": {"const": name}, "args": obj(args)})


_NUMERIC = {"anyOf": [{"type": "null"}, obj({"metric": {"enum": ["largest_transfer", "test_charge_count", "transaction_count"]},
                                              "value": {"type": "number"}})]}
_CLAIM = obj({"text": STR, "evidence_ids": STR_LIST, "numeric": _NUMERIC})
_FINAL = obj({"action": {"const": "final"},
              "outcome": {"enum": [Outcome.CLOSED_BENIGN.value, Outcome.ESCALATED.value, Outcome.INSUFFICIENT_EVIDENCE.value]},
              "claims": {"type": "array", "items": _CLAIM}})
INVESTIGATOR_STEP = {"anyOf": [
    _tool("resolve_account", {"email": STR}), _tool("get_device_history", {"account_id": STR}),
    _tool("get_transactions", {"account_id": STR}), _tool("compute_sequence_features", {}), _FINAL]}

INVESTIGATOR_STEP_P2 = {"anyOf": [*INVESTIGATOR_STEP["anyOf"], _tool("get_device_sharing", {"account_id": STR})]}

_FINDING = obj({"field": STR, "value": STR, "quote": STR, "doc_id": STR})


def records_step_schema(allow_scope: bool) -> dict:
    verdicts = [Verdict.SUPPORTED.value, Verdict.CONTRADICTED.value, Verdict.INSUFFICIENT_EVIDENCE.value]
    if allow_scope:
        verdicts.append(Verdict.OUT_OF_SCOPE.value)
    final = obj({"action": {"const": "final"}, "verdict": {"enum": verdicts}, "findings": {"type": "array", "items": _FINDING},
                 "explanation": STR, "conflicts": STR_LIST})
    return {"anyOf": [_tool("search_documents", {"query": STR}), _tool("read_document", {"doc_id": STR}), final]}


_INTAKE_CLAIM = obj({"id": STR, "text": STR, "attributed_to": STR, "claim_type": {"enum": [c.value for c in ClaimType]},
                     "subject_private_individual": {"type": "boolean"},
                     "params": {"type": "object"}})                       # free-form bag: its keys depend on claim_type
INTAKE = obj({"entities": {"type": "array", "items": obj({"name": STR, "kind": {"enum": ["official", "company", "person", "committee"]}})},
              "claims": {"type": "array", "items": _INTAKE_CLAIM}})
