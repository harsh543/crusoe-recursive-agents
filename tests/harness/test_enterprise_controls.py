"""PayPal-style platform controls: certified agent registry, role-based model access, shared context ids, memory rules."""
import json
from datetime import date, timedelta

import pytest

from casefile.agents.investigator import INVESTIGATOR_TOOLS
from casefile.agents.planner import PLANNER_TOOLS
from casefile.bench.cases import build_case, make_faults
from casefile.cost import CostLedger, Price
from casefile.errors import ModelNotAllowed
from casefile.harness.agents import DEFAULT_AGENTS, AgentRegistry, AgentSpec, NotCertified
from casefile.harness.gates import governance_gate
from casefile.harness.memory import (
    EpisodicMemory,
    MemoryRejected,
    OrganizationalMemory,
    ProceduralMemory,
    SemanticMemory,
    WorkingMemory,
)
from casefile.harness.router import ModelRouter
from casefile.harness.runner import run_enterprise
from casefile.trace import Trace
from tests.fakes import FakeLLM
from tests.harness.test_harness import CFG, IDENT, alert, dirs
from tests.harness.test_router_masking import FakeCrusoe, PRICES

TODAY = date(2026, 10, 17)


# ---- agent registry and certification ---------------------------------------------------------------------------
def test_default_agents_are_registered_certified_and_match_the_tool_allowlists():
    reg = AgentRegistry(DEFAULT_AGENTS)
    reg.require_certified(["planner", "investigator", "attributor"])
    assert set(reg.get("investigator").tools) == set(INVESTIGATOR_TOOLS)
    assert set(reg.get("planner").tools) == set(PLANNER_TOOLS)
    assert all(a.owner and a.version and a.certified_by for a in DEFAULT_AGENTS)


def test_an_uncertified_or_unknown_agent_cannot_run():
    reg = AgentRegistry([AgentSpec("investigator", "casefile", "1.0", "investigator", tuple(INVESTIGATOR_TOOLS), None)])
    with pytest.raises(NotCertified, match="investigator"):
        reg.require_certified(["investigator"])
    with pytest.raises(NotCertified, match="ghost"):
        reg.require_certified(["ghost"])


def test_governance_gate_rejects_uncertified_agents_before_any_model_call(tmp_path):
    reg = AgentRegistry([a if a.name != "investigator" else AgentSpec(a.name, a.owner, a.version, a.model_role, a.tools, None)
                         for a in DEFAULT_AGENTS])
    assert not governance_gate(alert(), CFG, agents=reg).allowed
    llm, case = FakeLLM({}), build_case("A-104", 0)
    res = run_enterprise(alert(), case.raw, make_faults("none"), llm, CostLedger({}), Trace(), config=CFG, identity=IDENT,
                         agents=reg, **dirs(tmp_path))
    assert res.state.status == "rejected" and "investigator" in res.state.reject_reason and llm.calls == []


# ---- role-based model access ---------------------------------------------------------------------------------------
def rbac_router(tmp_path, **kw):
    return ModelRouter(FakeCrusoe(), allowlist={"m1", "m2"}, prices={"m1": Price(1, 1, 1), "m2": Price(1, 1, 1)}, max_usd=1.0,
                       case_id="c", role_models={"planner": {"m2"}, "investigator": {"m1"}}, **kw)


def test_each_role_may_only_use_its_own_models_and_unmapped_roles_are_denied(tmp_path):
    r = rbac_router(tmp_path)
    r.chat("m2", [{"role": "user", "content": "x"}], role="planner")
    r.chat("m1", [{"role": "user", "content": "x"}], role="investigator")
    for model, role in (("m1", "planner"), ("m2", "investigator"), ("m1", "intake"), ("m1", None)):
        with pytest.raises(ModelNotAllowed):
            r.chat(model, [{"role": "user", "content": "x"}], role=role)


def test_llm_layer_passes_the_role_to_a_router():
    from casefile.llm import LLM
    r = rbac_router(tmp_path=None)
    llm = LLM(r, CostLedger({"m1": Price(1, 1, 1), "m2": Price(1, 1, 1)}), Trace(), {"planner": "m1"})
    with pytest.raises(ModelNotAllowed):
        llm.call_json("planner", [{"role": "user", "content": "x"}])           # planner is wired to m1 but only allowed m2


# ---- shared context id ---------------------------------------------------------------------------------------------
def test_every_trace_step_and_audit_event_carries_the_case_context_id(tmp_path):
    case = build_case("A-104", 0)
    t = Trace(tmp_path / "t.jsonl")
    run_enterprise(alert(alert_type="chargeback"), case.raw, make_faults("none"), FakeLLM({}), CostLedger({}), t, config=CFG,
                   identity=IDENT, **dirs(tmp_path))
    t.add("investigator", "tool", tool="x")
    assert t.context_id == "A-104" and all(s["context_id"] == "A-104" and s["task_id"].startswith("A-104:") for s in t.steps)
    assert all(json.loads(l)["context_id"] == "A-104" for l in (tmp_path / "t.jsonl").read_text().splitlines())


# ---- certified memory ----------------------------------------------------------------------------------------------
def test_working_memory_is_discarded_on_completion():
    memory = WorkingMemory()
    memory.start("case:A-104", {"step": "investigate"})
    memory.update("case:A-104", evidence_ids=["ev_dev"])
    assert memory.snapshot("case:A-104")["evidence_ids"] == ["ev_dev"]
    memory.discard("case:A-104")
    assert not memory.active("case:A-104")
    with pytest.raises(MemoryRejected):
        memory.snapshot("case:A-104")


def test_episodic_memory_is_scoped_capped_and_immutable_after_close(tmp_path):
    memory = EpisodicMemory(tmp_path / "episodes.jsonl")
    memory.record("ep_1", "tool_call", agent="investigator", agent_version="1.0", evidence_ids=["ev_dev"])
    memory.record("ep_1", "verify", agent="verifier", agent_version="1.0", data={"passed": True})
    memory.record("ep_2", "tool_call", agent="investigator", agent_version="1.0")
    assert len(memory.events("ep_1", limit=1)) == 1
    assert all(row["episode_id"] == "ep_1" for row in memory.events("ep_1"))
    memory.close("ep_1", outcome="escalated", label_id="review_1")
    with pytest.raises(MemoryRejected):
        memory.record("ep_1", "late_write", agent="investigator", agent_version="1.0")


def test_semantic_facts_need_evidence_expiry_and_independent_certification(tmp_path):
    m = SemanticMemory(tmp_path / "sem.jsonl")
    proposal_id = m.propose(
        "acct_1040",
        {"home_country": "US"},
        ["ev_dev"],
        TODAY + timedelta(days=30),
        author="agent:distiller",
        proposing_team="casefile",
        evidence_index={"ev_dev"},
        today=TODAY,
    )
    assert m.facts(on=TODAY) == []  # proposed facts are not organizational truth
    with pytest.raises(MemoryRejected):
        m.propose("acct_1040", {"x": 1}, [], TODAY + timedelta(days=30), evidence_index={"ev_dev"}, today=TODAY)       # no evidence
    with pytest.raises(MemoryRejected):
        m.propose("acct_1040", {"x": 1}, ["ev_nope"], TODAY + timedelta(days=30), evidence_index={"ev_dev"}, today=TODAY)  # unknown id
    with pytest.raises(MemoryRejected):
        m.propose("acct_1040", {"x": 1}, ["ev_dev"], TODAY - timedelta(days=1), evidence_index={"ev_dev"}, today=TODAY)  # already expired
    with pytest.raises(MemoryRejected):
        m.certify(proposal_id, reviewer="agent:distiller", verifying_team="risk-operations", today=TODAY)
    m.certify(proposal_id, reviewer="analyst_1", verifying_team="risk-operations", today=TODAY)
    fact = m.facts(on=TODAY)[0]
    assert fact["fact"] == {"home_country": "US"}
    assert fact["certified_by"] == "analyst_1" and fact["verifying_team"] == "risk-operations"
    assert m.facts(on=TODAY + timedelta(days=31)) == []                                                                   # expired facts disappear
    assert any(row["kind"] == "forgotten" and row["proposal_id"] == proposal_id for row in m.rows())


def test_semantic_retrieval_is_capped_and_rejected_facts_never_surface(tmp_path):
    m = SemanticMemory(tmp_path / "sem.jsonl")
    for i in range(SemanticMemory.MAX_RETRIEVAL + 5):
        proposal_id = m.propose(
            "acct_1040", {"n": i}, [f"ev_{i}"], TODAY + timedelta(days=30),
            author="agent:distiller", evidence_index={f"ev_{i}"}, today=TODAY,
        )
        if i == 0:
            m.reject(proposal_id, reviewer="analyst_1", verifying_team="risk-operations", reason="not established")
        else:
            m.certify(proposal_id, reviewer="analyst_1", verifying_team="risk-operations", today=TODAY)
    facts = m.facts(on=TODAY, limit=10_000)
    assert len(facts) == SemanticMemory.MAX_RETRIEVAL
    assert all(fact["fact"]["n"] != 0 for fact in facts)


def test_a_playbook_edit_ships_only_with_a_different_approver_and_a_better_held_out_score(tmp_path):
    p = ProceduralMemory(tmp_path / "proc.jsonl")
    v1 = p.propose(
        "Resolve the account id before any device lookup.",
        author="attributor",
        proposing_team="casefile",
        source_episode_ids=["ep_wrong_identifier_1"],
    )
    assert p.active() is None                                                    # proposals are inert until approved
    with pytest.raises(MemoryRejected):
        p.approve(v1, approver="attributor", score_before=0.6, score_after=0.8)    # no self-approval
    with pytest.raises(MemoryRejected):
        p.approve(v1, approver="analyst_1", score_before=0.8, score_after=0.8)     # no measured improvement
    p.approve(
        v1,
        approver="analyst_1",
        verifying_team="agent-governance",
        evaluation_id="eval_1",
        score_before=0.6,
        score_after=0.8,
    )
    assert p.active()["version"] == v1 and "Resolve the account id" in p.active()["text"]
    assert p.active()["verifying_team"] == "agent-governance"
    with pytest.raises(MemoryRejected):
        p.approve(v1, approver="analyst_2", score_before=0.6, score_after=0.9)     # already decided


def test_organizational_memory_returns_only_certified_content_under_one_cap(tmp_path):
    semantic = SemanticMemory(tmp_path / "sem.jsonl")
    procedural = ProceduralMemory(tmp_path / "proc.jsonl")
    unverified = semantic.propose(
        "acct_1040", {"ignore": True}, ["ev_0"], TODAY + timedelta(days=30),
        evidence_index={"ev_0"}, today=TODAY,
    )
    verified = semantic.propose(
        "acct_1040", {"home_country": "US"}, ["ev_1"], TODAY + timedelta(days=30),
        evidence_index={"ev_1"}, today=TODAY,
    )
    semantic.certify(verified, reviewer="analyst_1", verifying_team="risk-operations", today=TODAY)
    version = procedural.propose("Resolve account identity first.", author="attributor")
    procedural.approve(version, approver="analyst_1", score_before=0.6, score_after=0.8)

    result = OrganizationalMemory(semantic, procedural).retrieve(subject="acct_1040", on=TODAY, limit=2)
    assert result["returned"] == 2 and result["cap"] == 2
    assert [fact["proposal_id"] for fact in result["semantic"]] == [verified]
    assert unverified not in json.dumps(result)
    assert result["procedural"][0]["version"] == version
