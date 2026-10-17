"""Independent oracle for the records benchmark (own quote check; agents never import this module)."""
import re

from ..records.models import ClaimResult


def _n(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip().lower()


def quotes_ok(result: ClaimResult, docs: dict):
    """None if there are no findings; else True only if every quote is verbatim in its cited document."""
    if not result.findings:
        return None
    return all(f.doc_id in docs and _n(f.quote) in _n(docs[f.doc_id].text) for f in result.findings)


def judge(expected: str, result: ClaimResult, docs: dict, needs_conflict: bool = False) -> bool:
    if result.verdict.value != expected:
        return False
    if expected in ("supported", "contradicted"):
        if quotes_ok(result, docs) is not True:
            return False
        if needs_conflict:
            by_field: dict[str, set] = {}
            for f in result.findings:
                by_field.setdefault(f.field, set()).add(_n(f.value))
            if any(len(v) > 1 for v in by_field.values()) and not result.conflicts:
                return False
    return True
