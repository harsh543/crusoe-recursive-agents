"""Independent ground truth. Agent code must never import this module (enforced by a test)."""
import json
from pathlib import Path

from .models import Outcome

LABELS = Path(__file__).resolve().parents[2] / "labels" / "cases.json"


def load_labels(path: Path = LABELS) -> dict[str, str]:
    return json.loads(Path(path).read_text())


def expected_outcome(case_id: str, labels: dict | None = None) -> Outcome:
    return Outcome((labels or load_labels())[case_id])


def judge(case_id: str, outcome, evidence, labels: dict | None = None) -> bool:
    """Complete = right disposition AND the oracle itself sees ok device+transaction evidence for the account."""
    try:
        want = expected_outcome(case_id, labels)
    except KeyError:
        return False
    if Outcome(outcome) != want:
        return False
    if want in (Outcome.CLOSED_BENIGN, Outcome.ESCALATED):   # a closure must rest on ok evidence
        ok_sources = {r.source for r in evidence if r.status.value == "ok"}
        return {"device_history", "transactions"} <= ok_sources
    return True
