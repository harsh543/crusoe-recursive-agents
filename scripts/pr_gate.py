"""CI-friendly PR gate: runs the same checks as the casefile-gate MCP server.
  git diff main | .venv/bin/python scripts/pr_gate.py --change-id PR-12 --summary "Add account freeze step"
Exit code: 0 pass, 1 needs_review, 2 block. Prints JSON (never the diff or a full card number)."""
import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from casefile.gate_mcp.checks import check_pci_exposure, classify_fields, diff_tool_specs, regulatory_surface  # noqa: E402
from casefile.gate_mcp.decision import decide, validate_evidence  # noqa: E402
from casefile.harness.audit import AuditLog  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--change-id", required=True)
ap.add_argument("--summary", default="")
ap.add_argument("--paths", nargs="*", default=[])
ap.add_argument("--fields", nargs="*", default=[])
ap.add_argument("--old-tools", help="JSON file: tool specs before the change")
ap.add_argument("--new-tools", help="JSON file: tool specs after the change")
ap.add_argument("--evidence", help="JSON file with a list of evidence items")
ap.add_argument("--audit", default=str(ROOT / "runs" / "gate_audit.jsonl"))
a = ap.parse_args()

diff = sys.stdin.read() if not sys.stdin.isatty() else ""
pci, classes, surface = check_pci_exposure(diff), classify_fields(a.fields), regulatory_surface(a.summary, a.paths)
ev = validate_evidence(json.loads(Path(a.evidence).read_text()) if a.evidence else [])
changes = diff_tool_specs(json.loads(Path(a.old_tools).read_text()), json.loads(Path(a.new_tools).read_text())) if a.old_tools and a.new_tools else []
d = decide(pci=pci, classes=classes, contract_changes=changes, surface=surface, evidence=ev)
AuditLog(a.audit).append("pr_gate_decision", a.change_id, {"status": d.status, "reasons": d.reasons})
print(json.dumps({"status": d.status, "reasons": d.reasons, "required_actions": d.required_actions,
                  "pci": [asdict(f) for f in pci.findings], "regulatory_topics": [t.topic for t in surface.topics],
                  "tool_changes": [asdict(c) for c in changes]}, indent=2))
sys.exit({"pass": 0, "needs_review": 1, "block": 2}[d.status])
