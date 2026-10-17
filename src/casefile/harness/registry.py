"""Tool registry: every tool has an owner, a version and an access class; every call is authorized per role in code
and returns one receipt shape (status, evidence_id, coverage, record_count). A tool can move behind MCP without
changing the verifier."""
import dataclasses
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..features import IncompleteEvidence, compute_sequence_features
from ..models import EvidenceStatus


class PermissionDenied(Exception):
    pass


class ToolNotFound(KeyError):
    pass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    owner: str
    version: str
    access: str                      # "read" | "write"
    roles: frozenset
    fn: Optional[Callable] = None    # None: executed only by the code that holds the scope (the commit step)


@dataclass
class ToolReceipt:
    status: str                      # ok | partial | empty | stale | error
    evidence_id: Optional[str] = None
    coverage: Optional[str] = None
    record_count: int = 0
    data: dict = field(default_factory=dict)
    error: Optional[str] = None
    record: Any = None


class Registry:
    def __init__(self):
        self._specs: dict[str, ToolSpec] = {}
        self.ctx: dict = {}

    def register(self, spec: ToolSpec):
        self._specs[spec.name] = spec

    def specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def authorize(self, role: str, name: str) -> ToolSpec:
        spec = self._specs.get(name)
        if spec is None:
            raise ToolNotFound(name)
        if role not in spec.roles or (spec.access == "write" and role != "commit"):
            raise PermissionDenied(f"role {role!r} may not call {name!r}")
        return spec

    def call(self, role: str, name: str, args: dict) -> ToolReceipt:
        spec = self.authorize(role, name)
        if spec.fn is None:
            raise PermissionDenied(f"{name!r} is executed only by the {sorted(spec.roles)} step")
        try:
            return spec.fn(**args)
        except TypeError as e:
            return ToolReceipt(status="error", error=f"bad arguments for {name}: {e}")


def _record_receipt(rec, key: str) -> ToolReceipt:
    n = len(rec.data.get(key, [])) if rec.status in (EvidenceStatus.OK, EvidenceStatus.STALE, EvidenceStatus.PARTIAL) else 0
    cov = None if rec.status == EvidenceStatus.ERROR else f"{rec.covers_from:%Y-%m-%d}..{rec.covers_to:%Y-%m-%d}"
    return ToolReceipt(status=rec.status.value, evidence_id=rec.id, coverage=cov, record_count=n, error=rec.error, record=rec)


def build_registry(toolbox, policy) -> Registry:
    reg, inv = Registry(), frozenset({"investigator"})

    def resolve_account(email):
        try:
            return ToolReceipt(status="ok", record_count=1, data={"account_id": toolbox.resolve_account(email)})
        except LookupError as e:
            return ToolReceipt(status="error", error=str(e))

    def features():
        try:
            return ToolReceipt(status="ok", record_count=1, data=dataclasses.asdict(compute_sequence_features(reg.ctx.get("evidence", []))))
        except IncompleteEvidence as e:
            return ToolReceipt(status="error", error=str(e))

    reg.register(ToolSpec("resolve_account", "identity-service", "1.0", "read", inv, resolve_account))
    reg.register(ToolSpec("get_device_history", "device-service", "1.0", "read", inv,
                          lambda account_id: _record_receipt(toolbox.get_device_history(account_id), "devices")))
    reg.register(ToolSpec("get_transactions", "ledger-service", "1.0", "read", inv,
                          lambda account_id: _record_receipt(toolbox.get_transactions(account_id), "transactions")))
    reg.register(ToolSpec("compute_sequence_features", "casefile", "1.0", "read", inv, features))
    if "device_sharing" in policy.required_sources:     # tool exists only under a policy that requires the source
        reg.register(ToolSpec("get_device_sharing", "fraud-engine-mcp", "1.0", "read", inv,
                              lambda account_id: _record_receipt(toolbox.get_device_sharing(account_id), "peer_accounts")))
    reg.register(ToolSpec("get_policy", "policy-service", "1.0", "read", frozenset({"planner"}),
                          lambda: ToolReceipt(status="ok", record_count=1, data={"version": policy.version,
                                                                                  "required_sources": list(policy.required_sources)})))
    reg.register(ToolSpec("commit_disposition", "casefile-gate", "1.0", "write", frozenset({"commit"}), None))
    return reg
