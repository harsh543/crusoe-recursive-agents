"""E2: one governed path to the model provider. PII is tokenized on the way out and restored on the way back."""
import json
from types import SimpleNamespace

import pytest

from casefile.bench.cases import build_case, make_faults
from casefile.cost import CostLedger, Price
from casefile.harness.audit import AuditLog
from casefile.harness.checkpoint import CheckpointStore
from casefile.harness.gates import GovernanceConfig
from casefile.harness.masking import PiiVault
from casefile.harness.review import ReviewQueue
from casefile.harness.router import BudgetExceeded, ModelNotAllowed, ModelRouter, pace_seconds
from casefile.harness.runner import run_enterprise
from casefile.harness.state import Alert
from casefile.llm import LLM
from casefile.trace import Trace
from tests.fakes import FakeLLM
from tests.harness.test_harness import CFG, IDENT, alert, dirs

PRICES = {"m1": Price(1.0, 0.5, 2.0)}                       # $/1M tokens, illustrative


class FakeCrusoe:
    def __init__(self, reply="ok", in_tok=1000, out_tok=500):
        self.reply, self.in_tok, self.out_tok, self.sent, self.last_headers = reply, in_tok, out_tok, [], {}

    def chat(self, model, messages, max_tokens=1024, **kw):
        self.sent.append(messages)
        msg = SimpleNamespace(content=self.reply, model_dump=lambda: {"content": self.msg.content})
        self.msg = msg
        usage = SimpleNamespace(prompt_tokens=self.in_tok, completion_tokens=self.out_tok,
                                prompt_tokens_details=SimpleNamespace(cached_tokens=0))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")], usage=usage)


def router(fake, tmp_path, **kw):
    return ModelRouter(fake, allowlist={"m1"}, prices=PRICES, max_usd=kw.pop("max_usd", 1.0), case_id="A-104",
                       log_path=tmp_path / "router.jsonl", **kw)


# ---- masking ---------------------------------------------------------------------------------------------------
def test_emails_phones_and_valid_cards_are_tokenized_and_restored():
    v = PiiVault()
    text = "Contact sam@example.test or +1 415 555 2671 / 415-555-2671, card 4111 1111 1111 1111."
    masked = v.mask(text)
    for secret in ("sam@example.test", "555-2671", "4111"):
        assert secret not in masked
    assert "EMAIL_1" in masked and "PHONE_" in masked and "CARD_1" in masked
    assert v.unmask(masked) == text                      # every value restores to its exact original text


def test_same_value_gets_the_same_token_and_different_values_differ():
    v = PiiVault()
    assert v.mask("a@x.test") == v.mask("a@x.test") != v.mask("b@x.test")


def test_amounts_dates_ids_and_invalid_card_like_numbers_are_left_alone():
    v = PiiVault()
    text = "Award $143,000,000 on 2026-09-20T10:05:00Z for acct_1040, ref 1234 5678 9012 3456."
    assert v.mask(text) == text


# ---- router -------------------------------------------------------------------------------------------------------
def test_model_outside_the_allowlist_is_refused_before_any_call(tmp_path):
    fake = FakeCrusoe()
    with pytest.raises(ModelNotAllowed):
        router(fake, tmp_path).chat("gpt-anything", [{"role": "user", "content": "hi"}])
    assert fake.sent == []


def test_outbound_text_is_masked_and_the_reply_is_unmasked(tmp_path):
    fake = FakeCrusoe(reply='{"action":"tool","args":{"email":"EMAIL_1"}}')
    r = router(fake, tmp_path)
    resp = r.chat("m1", [{"role": "user", "content": "customer sam@example.test"}])
    assert "sam@example.test" not in json.dumps(fake.sent) and "EMAIL_1" in json.dumps(fake.sent)
    assert "sam@example.test" in resp.choices[0].message.content


def test_budget_is_enforced_per_case_and_every_call_is_logged(tmp_path):
    fake = FakeCrusoe(in_tok=1_000_000, out_tok=0)          # $1.00 per call at $1/1M input
    r = router(fake, tmp_path, max_usd=1.0)
    r.chat("m1", [{"role": "user", "content": "x"}])
    with pytest.raises(BudgetExceeded):
        r.chat("m1", [{"role": "user", "content": "y"}])
    lines = [json.loads(l) for l in (tmp_path / "router.jsonl").read_text().splitlines()]
    assert len(lines) == 1 and lines[0]["case_id"] == "A-104" and lines[0]["cost_usd"] == pytest.approx(1.0)
    assert lines[0]["model"] == "m1" and lines[0]["pii_tokens"] == 0


def test_log_never_contains_the_raw_prompt_or_pii(tmp_path):
    r = router(FakeCrusoe(), tmp_path)
    r.chat("m1", [{"role": "user", "content": "sam@example.test"}])
    assert "sam@example.test" not in (tmp_path / "router.jsonl").read_text()


def test_throttle_waits_only_when_the_rate_limit_headers_show_little_headroom():
    assert pace_seconds(None, None) == 0 and pace_seconds(25, 30) == 0
    assert 0 < pace_seconds(1, 30) < pace_seconds(0, 30) <= 20


def test_router_works_as_the_llm_layers_provider(tmp_path):
    fake = FakeCrusoe(reply='{"x": 1}')
    llm = LLM(router(fake, tmp_path), CostLedger(PRICES), Trace(), {"role": "m1"})
    assert llm.call_json("role", [{"role": "user", "content": "hi"}]) == {"x": 1}


# ---- runner: a budget stop becomes a human review task, not a guess ----------------------------------------------
def test_budget_exhaustion_sends_the_case_to_an_analyst_as_insufficient_evidence(tmp_path):
    class BrokeLLM:
        def call_json(self, *a, **k):
            raise BudgetExceeded("case budget exhausted")

    case = build_case("A-104", 0)
    res = run_enterprise(alert(), case.raw, make_faults("none"), BrokeLLM(), CostLedger({}), Trace(), config=CFG,
                         identity=IDENT, **dirs(tmp_path))
    assert res.state.outcome == "insufficient_evidence" and res.state.review_task_id
    assert any(e["type"] == "budget_exhausted" for e in AuditLog(tmp_path / "audit.jsonl").events())
