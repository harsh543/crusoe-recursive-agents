"""casefile-gate: an MCP server for the pull-request gate (PCI exposure, data classification, API-contract changes, regulatory surface).
Guardrails: read-only checks, capped inputs, card numbers never echoed, no network access, evidence limited to official domains,
every decision appended to a hash-chained audit log without the raw diff. Research is done by the HOST through You.com search and
exact-URL extraction; finance is reserved for verified issuer/financial questions. This server never holds You.com credentials."""
import os
import sys
from dataclasses import asdict
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..harness.audit import AuditLog
from .checks import NOTICE, check_pci_exposure as _pci, classify_fields, diff_contract, diff_tool_specs, regulatory_surface
from .decision import decide, validate_evidence

MAX_TEXT, MAX_ITEMS = 200_000, 500
POLICY = f"""casefile-gate policy
- PCI exposure: a Luhn-valid card number, CVV/CVC or track data anywhere in the change blocks it. Known test card numbers are low severity.
  Card-related fields or logging added in a diff need review.
- Data classification: every new field must be classified (pii, payment, credential, internal); unclassified fields need review.
- API-contract changes: removed properties, type changes, new required fields, narrowed enums are breaking and need review; widening a tool's
  access class or roles blocks unless security has approved (a named approver is recorded in the audit log).
- Regulatory surface: topics found in the change need accepted evidence (https, official domain, verbatim quote) before the gate passes.
- Evidence is informational and is not verified by this server. {NOTICE}
- The gate only reads. It never approves a block and never moves money or changes accounts."""


def _cap(value, name: str, limit: int = MAX_TEXT):
    if isinstance(value, str) and len(value) > limit:
        raise ValueError(f"{name} exceeds {limit} characters")
    if isinstance(value, (list, dict)) and len(value) > MAX_ITEMS:
        raise ValueError(f"{name} exceeds {MAX_ITEMS} items")
    return value


def _pci_dict(r) -> dict:
    return {"blocking": r.blocking, "findings": [asdict(f) for f in r.findings]}


def build_server(audit_path=None) -> FastMCP:
    mcp = FastMCP("casefile-gate", instructions="PR gate for PCI exposure, data classification, API-contract changes and regulatory surface. "
                                                 + NOTICE)
    audit = AuditLog(audit_path or Path(os.environ.get("CASEFILE_GATE_AUDIT", "runs/gate_audit.jsonl")))
    ro = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    audited = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)

    @mcp.tool(annotations=ro)
    def check_pci_exposure(text: str) -> dict:
        """Scan text or a unified diff for card numbers (Luhn-checked), CVV/CVC, track data, card fields and card data in logs. Never echoes a full card number."""
        return _pci_dict(_pci(_cap(text, "text")))

    @mcp.tool(annotations=ro)
    def classify_data_fields(fields: list[str] | dict) -> dict:
        """Classify field names (or a JSON-schema object) as pii, payment, credential, internal or unclassified."""
        return {"fields": [asdict(c) for c in classify_fields(_cap(fields, "fields"))]}

    @mcp.tool(annotations=ro)
    def check_api_contract(old_schema: dict, new_schema: dict) -> dict:
        """Diff two JSON schemas and list breaking and non-breaking contract changes."""
        return {"changes": [asdict(c) for c in diff_contract(_cap(old_schema, "old_schema"), _cap(new_schema, "new_schema"))]}

    @mcp.tool(annotations=ro)
    def check_tool_permissions(old_tools: dict, new_tools: dict) -> dict:
        """Diff tool specs ({name: {access, roles, version}}): removed tools, access-class changes and widened roles."""
        return {"changes": [asdict(c) for c in diff_tool_specs(_cap(old_tools, "old_tools"), _cap(new_tools, "new_tools"))]}

    @mcp.tool(annotations=ro)
    def check_regulatory_surface(change_summary: str, touched_paths: list[str] | None = None) -> dict:
        """Map a change to possible regulatory topics and return queries for the host to run through web search and exact-URL extraction."""
        r = regulatory_surface(_cap(change_summary, "change_summary", 20_000), _cap(touched_paths or [], "touched_paths"))
        return {"needs_research": r.needs_research, "topics": [asdict(t) for t in r.topics], "notice": r.notice}

    @mcp.tool(annotations=ro)
    def record_regulatory_evidence(items: list[dict]) -> dict:
        """Validate research evidence: https, official domain, 20-1000 character verbatim quote, no legal-conclusion language."""
        r = validate_evidence(_cap(items, "items"))
        return {"accepted": r.accepted, "rejected": r.rejected, "notice": NOTICE}

    @mcp.tool(annotations=audited)
    def gate_decide(change_id: str, diff: str = "", change_summary: str = "", touched_paths: list[str] | None = None,
                    old_schema: dict | None = None, new_schema: dict | None = None, old_tools: dict | None = None,
                    new_tools: dict | None = None, fields: list[str] | None = None, evidence: list[dict] | None = None,
                    security_approved_by: str = "") -> dict:
        """Run all four checks and return pass / needs_review / block. Appends a hash-chained audit event with counts only (no diff, no card data)."""
        pci = _pci(_cap(diff, "diff"))
        classes = classify_fields(_cap(fields or [], "fields"))
        changes = (diff_contract(_cap(old_schema, "old_schema"), _cap(new_schema, "new_schema")) if old_schema and new_schema else []) \
            + (diff_tool_specs(_cap(old_tools, "old_tools"), _cap(new_tools, "new_tools")) if old_tools or new_tools else [])
        surface = regulatory_surface(_cap(change_summary, "change_summary", 20_000), _cap(touched_paths or [], "touched_paths"))
        ev = validate_evidence(_cap(evidence or [], "evidence"))
        d = decide(pci=pci, classes=classes, contract_changes=changes, surface=surface, evidence=ev,
                   security_approved=bool(security_approved_by.strip()))
        counts = {"pci_findings": len(pci.findings), "unclassified_fields": sum(c.data_class == "unclassified" for c in classes),
                  "breaking_changes": sum(c.breaking for c in changes), "regulatory_topics": len(surface.topics),
                  "evidence_accepted": len(ev.accepted), "evidence_rejected": len(ev.rejected)}
        audit.append("pr_gate_decision", change_id, {"status": d.status, "reasons": d.reasons, "counts": counts,
                                                      "security_approved_by": security_approved_by.strip() or None})
        return {"status": d.status, "reasons": d.reasons, "required_actions": d.required_actions, "counts": counts, "notice": NOTICE,
                "research_queries": [q for t in surface.topics for q in t.research_queries]}

    @mcp.resource("gate://policy")
    def policy() -> str:
        """The rules this gate applies."""
        return POLICY

    @mcp.prompt()
    def pr_gate_review(change_summary: str) -> str:
        """Review a pull request with this gate, using You.com web tools for primary-source regulatory research."""
        return (f"Review this change with the casefile-gate tools: {change_summary}\n"
                "1. Call check_pci_exposure on the diff, classify_data_fields on new fields, check_api_contract / check_tool_permissions on schema changes.\n"
                "2. Call check_regulatory_surface. For each returned topic, use you-search to discover an official source and you-contents to "
                "extract that exact URL. Keep only government, regulator, or standards-body sources. Do not use you-finance for general policy research.\n"
                "3. Pass each finding to record_regulatory_evidence with the exact URL and a verbatim quote. Do not state that the change is compliant.\n"
                "4. Call gate_decide. Never override a block; report required_actions to the author.\n" + NOTICE)

    return mcp


if __name__ == "__main__":
    server = build_server()
    server.run(transport="streamable-http" if "--http" in sys.argv else "stdio")
