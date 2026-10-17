"""Evidence guardrails and the gate decision. The decision comes from these rules in code, never from a model."""
import re
from dataclasses import asdict, dataclass, field
from urllib.parse import urlparse

ALLOWED_SUFFIXES = (".gov", ".europa.eu")
ALLOWED_HOSTS = {"pcisecuritystandards.org", "nacha.org", "law.cornell.edu"}
_CONCLUSION = re.compile(r"(?i)\b(we|this|it|the change)\s+(is|are|makes? us|will be)\s+(fully\s+)?(compliant|legal|lawful|approved)\b")
_ORDER = {"pass": 0, "needs_review": 1, "block": 2}


@dataclass(frozen=True)
class EvidenceItem:
    topic: str
    statement: str
    url: str
    quote: str
    retrieved_at: str


@dataclass
class EvidenceResult:
    accepted: list = field(default_factory=list)
    rejected: list = field(default_factory=list)


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _reject_reason(e: EvidenceItem) -> str | None:
    u = urlparse(e.url)
    if u.scheme != "https":
        return "https is required for evidence URLs"
    h = _host(e.url)
    if not (h in ALLOWED_HOSTS or h.endswith(ALLOWED_SUFFIXES)):
        return f"domain {h!r} is not on the official-source allowlist"
    if not 20 <= len(e.quote) <= 1000:
        return "quote must be between 20 and 1000 characters"
    if len(e.statement) > 500:
        return "statement is too long (max 500 characters)"
    if _CONCLUSION.search(e.statement):
        return "legal conclusion language is not accepted; state what the source says, not whether we comply"
    return None


def validate_evidence(items) -> EvidenceResult:
    out = EvidenceResult()
    for raw in items:
        try:
            e = raw if isinstance(raw, EvidenceItem) else EvidenceItem(**raw)
        except TypeError as ex:
            out.rejected.append({"item": str(raw)[:120], "reason": f"malformed evidence item: {ex}"})
            continue
        why = _reject_reason(e)
        if why:
            out.rejected.append({"item": asdict(e), "reason": why})
        else:                                   # the gate cannot fetch the page, so the quote is not verified by it
            out.accepted.append({**asdict(e), "verified_by_gate": False, "informational": True})
    return out


@dataclass
class Decision:
    status: str
    reasons: list = field(default_factory=list)
    required_actions: list = field(default_factory=list)


def decide(*, pci, classes, contract_changes, surface, evidence: EvidenceResult, security_approved: bool = False) -> Decision:
    d = Decision("pass")

    def raise_to(status, reason, action=None):
        if _ORDER[status] > _ORDER[d.status]:
            d.status = status
        d.reasons.append(reason)
        if action:
            d.required_actions.append(action)

    blocking = [f for f in pci.findings if f.blocking]
    if blocking:
        raise_to("block", f"PCI exposure: {len(blocking)} blocking finding(s) ({', '.join(sorted({f.kind for f in blocking}))})",
                 "Remove card numbers and sensitive authentication data from the change; use tokens.")
    elif any(f.severity == "high" for f in pci.findings):
        raise_to("needs_review", "PCI exposure: card-related fields or logging were added", "Confirm card data never reaches logs, prompts or storage.")
    unclassified = [c.name for c in classes if c.data_class == "unclassified"]
    if unclassified:
        raise_to("needs_review", f"Data classification: unclassified fields {unclassified}", "A data owner must classify each new field before merge.")
    perm = [c for c in contract_changes if c.kind in ("access_class_changed", "roles_widened")]
    if perm and not security_approved:
        raise_to("block", f"API contract: permission expansion on {sorted({c.path for c in perm})}", "Needs explicit security approval.")
    breaking = [c for c in contract_changes if c.breaking]
    if breaking:
        raise_to("needs_review", f"API contract: {len(breaking)} breaking change(s)", "Version the contract and notify consumers.")
    have = {e["topic"] for e in evidence.accepted}
    missing = [t.topic for t in surface.topics if t.topic not in have]
    if missing:
        raise_to("needs_review", f"Regulatory surface: no accepted evidence for {missing}", f"Research and record official-source evidence for: {missing}.")
    return d
