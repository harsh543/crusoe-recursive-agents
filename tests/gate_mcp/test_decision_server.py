"""Decision rules, evidence guardrails, and the MCP server surface (read-only checks, capped inputs, audited decisions)."""
import asyncio
import json

import pytest

from casefile.gate_mcp.checks import check_pci_exposure, classify_fields, diff_contract, diff_tool_specs, regulatory_surface
from casefile.gate_mcp.decision import EvidenceItem, decide, validate_evidence
from tests.gate_mcp.test_checks import PAN

GOOD_URL = "https://www.fincen.gov/resources/statutes-regulations"


def item(**kw):
    base = dict(topic="aml_reporting", statement="FinCEN publishes suspicious-activity reporting rules.",
                url=GOOD_URL, quote="Suspicious activity reports must be filed within the required period.", retrieved_at="2026-10-17")
    base.update(kw)
    return EvidenceItem(**base)


# ---- evidence guardrails ------------------------------------------------------------------------------------------------
def test_evidence_from_official_domains_is_accepted_but_marked_unverified():
    r = validate_evidence([item(), item(url="https://eur-lex.europa.eu/eli/reg/2016/679"), item(url="https://www.pcisecuritystandards.org/x")])
    assert len(r.accepted) == 3 and all(a["verified_by_gate"] is False for a in r.accepted)


@pytest.mark.parametrize("kw,why", [(dict(url="https://random-blog.example.com/post"), "domain"), (dict(url="http://www.fincen.gov/x"), "https"),
                                    (dict(url="https://www.google.com/search?q=sar"), "domain"), (dict(quote="too short"), "quote"),
                                    (dict(statement="With this change we are compliant with the law."), "legal conclusion")])
def test_evidence_that_breaks_the_guardrails_is_rejected_with_a_reason(kw, why):
    r = validate_evidence([item(**kw)])
    assert r.accepted == [] and why in r.rejected[0]["reason"]


# ---- decision ------------------------------------------------------------------------------------------------------------
def run(text="x = 1\n", summary="Rename a helper", fields=("account_id",), old=None, new=None, old_t=None, new_t=None, evidence=(), approved=False):
    sch = {"type": "object", "properties": {"a": {"type": "string"}}}
    return decide(pci=check_pci_exposure(text), classes=classify_fields(list(fields)),
                  contract_changes=diff_contract(old or sch, new or sch) + diff_tool_specs(old_t or {}, new_t or {}),
                  surface=regulatory_surface(summary, []), evidence=validate_evidence(list(evidence)), security_approved=approved)


def test_a_clean_change_passes():
    d = run()
    assert d.status == "pass" and d.reasons == []


def test_a_real_card_number_blocks():
    d = run(text=f'card = "{PAN}"\n')
    assert d.status == "block" and any("PCI" in r for r in d.reasons)


def test_unclassified_fields_and_breaking_changes_need_review():
    assert run(fields=["account_id", "foo_bar"]).status == "needs_review"
    sch2 = {"type": "object", "properties": {}}
    assert run(new=sch2).status == "needs_review"


def test_regulatory_topics_need_review_until_accepted_evidence_exists_for_each():
    assert run(summary="Add a step that freezes the account").status == "needs_review"
    ok = item(topic="account_actions", url="https://www.consumerfinance.gov/rules-policy/regulations/1005/")
    assert run(summary="Add a step that freezes the account", evidence=[ok]).status == "pass"
    assert run(summary="Add a step that freezes the account", evidence=[item(topic="other")]).status == "needs_review"


def test_permission_expansion_blocks_unless_security_approved():
    old, new = {"t": {"access": "read", "roles": ["investigator"]}}, {"t": {"access": "write", "roles": ["investigator"]}}
    assert run(old_t=old, new_t=new).status == "block"
    assert run(old_t=old, new_t=new, approved=True).status == "needs_review"          # still a breaking change: a human reviews it


# ---- MCP server --------------------------------------------------------------------------------------------------------------
@pytest.fixture
def server(tmp_path):
    from casefile.gate_mcp.server import build_server
    return build_server(audit_path=tmp_path / "gate_audit.jsonl"), tmp_path / "gate_audit.jsonl"


def with_client(srv, coro):
    from mcp.shared.memory import create_connected_server_and_client_session

    async def go():
        async with create_connected_server_and_client_session(srv._mcp_server) as client:
            return await coro(client)
    return asyncio.run(go())


def payload(result):
    return json.loads(result.content[0].text)


def test_server_exposes_only_the_expected_tools_and_marks_checks_read_only(server):
    srv, _ = server
    tools = {t.name: t for t in with_client(srv, lambda c: c.list_tools()).tools}
    assert set(tools) == {"check_pci_exposure", "classify_data_fields", "check_api_contract", "check_tool_permissions",
                          "check_regulatory_surface", "record_regulatory_evidence", "gate_decide"}
    for name, t in tools.items():
        assert t.annotations.readOnlyHint is (name != "gate_decide"), name
        assert t.annotations.destructiveHint is False


def test_pci_tool_over_mcp_never_returns_the_full_card_number(server):
    srv, _ = server
    res = with_client(srv, lambda c: c.call_tool("check_pci_exposure", {"text": f'card = "{PAN}"'}))
    body = res.content[0].text
    assert PAN not in body and PAN.replace(" ", "") not in body
    assert payload(res)["blocking"] is True


def test_decisions_are_audited_without_the_raw_diff_or_card_data(server):
    srv, audit = server
    args = {"change_id": "PR-7", "diff": f'+card = "{PAN}"\n', "change_summary": "Store the card number"}
    res = with_client(srv, lambda c: c.call_tool("gate_decide", args))
    assert payload(res)["status"] == "block"
    from casefile.harness.audit import AuditLog
    log = AuditLog(audit)
    assert log.verify_chain() and log.events()[-1]["type"] == "pr_gate_decision" and log.events()[-1]["case_id"] == "PR-7"
    raw = audit.read_text()
    assert PAN not in raw and PAN.replace(" ", "") not in raw and "card =" not in raw


def test_oversized_input_is_rejected(server):
    srv, _ = server
    res = with_client(srv, lambda c: c.call_tool("check_pci_exposure", {"text": "x" * 300_000}))
    assert res.isError


def test_policy_resource_and_review_prompt_are_published(server):
    srv, _ = server

    async def go(c):
        prompts = [p.name for p in (await c.list_prompts()).prompts]
        res = [str(r.uri) for r in (await c.list_resources()).resources]
        text = (await c.read_resource("gate://policy")).contents[0].text
        return prompts, res, text
    prompts, resources, text = with_client(srv, go)
    assert "pr_gate_review" in prompts and "gate://policy" in resources and "not legal advice" in text.lower()
