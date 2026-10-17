"""Live checks against Crusoe. Skipped by default; run with: pytest -m live"""

import pytest

from crusoe_client import MODELS, Crusoe, reply_text

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def crusoe():
    c = Crusoe()  # exits if CRUSOE_API_KEY is missing
    return c


def test_our_model_roles_exist_in_v1_models(crusoe):
    ids = {m["id"] for m in crusoe.list_models()}
    missing = {role: mid for role, mid in MODELS.items() if mid not in ids}
    assert not missing, f"not in /v1/models (check casing/prefix): {missing}"


def test_cheap_model_replies_with_budget_headroom(crusoe):
    resp = crusoe.chat(MODELS["cheap"], [{"role": "user", "content": "Reply with exactly: pong"}],
                       max_tokens=1024)
    text, _ = reply_text(resp)
    assert resp.choices[0].finish_reason != "length"
    assert "pong" in text.lower()


def test_investigator_model_supports_tools_per_v1_models(crusoe):
    rec = next(m for m in crusoe.list_models() if m["id"] == MODELS["subagent"])
    assert "tools" in rec.get("supported_parameters", [])


def test_response_format_support_is_known_for_planner_model(crusoe):
    rec = next(m for m in crusoe.list_models() if m["id"] == MODELS["planner"])
    # Not asserting True: the design falls back to JSON-in-prompt when absent. We assert it is knowable.
    assert "supported_parameters" in rec


def test_prefix_cache_reports_cached_tokens_on_second_identical_prefix(crusoe):
    prefix = "You are a fraud investigator. " + "Policy rule. " * 400
    msgs = [{"role": "system", "content": prefix}]
    crusoe.chat(MODELS["cheap"], msgs + [{"role": "user", "content": "one"}], max_tokens=1024)
    crusoe.chat(MODELS["cheap"], msgs + [{"role": "user", "content": "two"}], max_tokens=1024)
    assert crusoe.cached_tokens > 0, "no cached tokens reported; check prefix stability"


def test_router_masks_pii_on_the_wire_restores_it_and_captures_rate_limit_headers(crusoe, tmp_path):
    import json

    from casefile.config import LIGHTNING, prices_from_records
    from casefile.harness.router import ModelRouter

    router = ModelRouter(crusoe, allowlist={LIGHTNING}, prices=prices_from_records(crusoe.list_models()), max_usd=0.05,
                         case_id="live-1", log_path=tmp_path / "router.jsonl")
    resp = router.chat(LIGHTNING, [{"role": "user", "content": "Repeat this token exactly and nothing else: sam.private@example.test"}],
                       max_tokens=256, extra_body={"chat_template_kwargs": {"enable_thinking": False}})
    assert "sam.private@example.test" in resp.choices[0].message.content          # restored on the way back
    log = json.loads((tmp_path / "router.jsonl").read_text().splitlines()[0])
    assert log["pii_tokens"] == 1 and "sam.private" not in json.dumps(log)           # masked on the way out
    # Observed Oct 17 2026: 200 responses carry NO x-ratelimit-* headers (skill file says they should). Capture must still work.
    assert isinstance(crusoe.last_headers, dict) and crusoe.last_headers
    print("rate-limit headers seen:", {k: v for k, v in crusoe.last_headers.items() if "ratelimit" in k} or "none")


@pytest.mark.parametrize("name", ["PLANNER", "ATTRIBUTION", "CRITIC", "INVESTIGATOR_STEP", "RECORDS_STEP", "INTAKE"])
def test_every_agent_schema_is_accepted_by_crusoe_and_obeyed(crusoe, name):
    import json

    from casefile import schemas
    from casefile.config import LIGHTNING, SUPER_VL

    schema = schemas.records_step_schema(True) if name == "RECORDS_STEP" else getattr(schemas, name)
    model = SUPER_VL if name in ("PLANNER", "INTAKE") else LIGHTNING
    prompt = {"INTAKE": "Case file: 1. Senator X: \"Acme LLC was formed 5 days before the award.\" Extract claims.",
              "PLANNER": "Define done for alert A-1.", "ATTRIBUTION": "Failure at step s003 (get_device_history error). Blame whom?",
              "CRITIC": "Is 'benign' supported when the lookup errored?", "INVESTIGATOR_STEP": "Look up device history for acct_1.",
              "RECORDS_STEP": "Read document d_reg."}[name]
    resp = crusoe.chat(model, [{"role": "system", "content": "Reply with one JSON object."}, {"role": "user", "content": prompt}], max_tokens=1500,
                       extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                       response_format={"type": "json_schema", "json_schema": {"name": name.lower(), "schema": schema, "strict": True}})
    out = json.loads(reply_text(resp)[0])
    assert isinstance(out, dict) and out, out
    if name == "INTAKE":
        assert set(out) == {"entities", "claims"} and out["claims"]
        assert all(c["claim_type"] in schema["properties"]["claims"]["items"]["properties"]["claim_type"]["enum"] for c in out["claims"])
    if name == "PLANNER":
        assert set(out["planner_checks"]) <= set(schema["properties"]["planner_checks"]["items"]["enum"])
