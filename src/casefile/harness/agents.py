"""Agent registry: every agent has an owner, a version, a model role, a tool list and a certification. Uncertified agents cannot run."""
from dataclasses import dataclass
from typing import Optional

from ..agents.investigator import INVESTIGATOR_TOOLS
from ..agents.planner import PLANNER_TOOLS


class NotCertified(Exception):
    pass


@dataclass(frozen=True)
class AgentSpec:
    name: str
    owner: str
    version: str
    model_role: str
    tools: tuple
    certified_by: Optional[str] = None

    @property
    def certified(self) -> bool:
        return bool(self.certified_by)


# Hackathon build: certification is a recorded self-attestation, not an independent platform review.
_CERT = "hackathon-self-certification"
DEFAULT_AGENTS = [
    AgentSpec("planner", "casefile", "1.0", "planner", tuple(PLANNER_TOOLS), _CERT),
    AgentSpec("investigator", "casefile", "1.0", "investigator", tuple(INVESTIGATOR_TOOLS), _CERT),
    AgentSpec("attributor", "casefile", "1.0", "attributor", (), _CERT),
]


class AgentRegistry:
    def __init__(self, agents):
        self._agents = {a.name: a for a in agents}

    def get(self, name: str) -> AgentSpec:
        return self._agents[name]

    def manifest(self) -> list[dict]:
        return [{"name": a.name, "owner": a.owner, "version": a.version, "model_role": a.model_role, "tools": list(a.tools),
                 "certified_by": a.certified_by} for a in self._agents.values()]

    def require_certified(self, names) -> None:
        bad = [n for n in names if n not in self._agents or not self._agents[n].certified]
        if bad:
            raise NotCertified(f"agent(s) not registered or not certified: {', '.join(bad)}")
