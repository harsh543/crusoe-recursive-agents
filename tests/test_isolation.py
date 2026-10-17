"""FR-14/15: agents cannot write, cannot see ground truth. Enforced structurally, not by prompt."""
import ast
from pathlib import Path

from casefile import oracle  # noqa: F401  (must exist; agents must not import it)
from casefile.agents.investigator import INVESTIGATOR_TOOLS
from casefile.agents.planner import PLANNER_TOOLS

AGENTS_DIR = Path(__file__).resolve().parent.parent / "src" / "casefile" / "agents"
FORBIDDEN = {"casefile.oracle", "casefile.gate", "labels"}


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names |= {f"{node.module}.{a.name}" for a in node.names}
    return names


def test_agent_modules_do_not_import_oracle_labels_or_gate():
    files = list(AGENTS_DIR.glob("*.py"))
    assert files, "agents package must contain modules"
    for f in files:
        bad = {i for i in _imports(f) if any(i == b or i.startswith(b + ".") for b in FORBIDDEN)}
        assert not bad, f"{f.name} imports {bad}"


def test_investigator_has_exactly_the_four_read_tools():
    assert set(INVESTIGATOR_TOOLS) == {
        "resolve_account", "get_device_history", "get_transactions", "compute_sequence_features"}


def test_planner_may_only_read_policy():
    assert set(PLANNER_TOOLS) == {"get_policy"}


def test_no_agent_has_the_write_tool():
    assert "commit_disposition" not in set(INVESTIGATOR_TOOLS) | set(PLANNER_TOOLS)
