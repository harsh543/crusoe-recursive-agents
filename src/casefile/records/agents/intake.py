"""Intake (Super VL): case file text -> atomic, attributed claims. Scope is then enforced by CODE, not by the model."""
import re

from pydantic import ValidationError

from ...schemas import INTAKE
from ..models import ClaimType, RecordClaim
from ..neutrality import lint

SYSTEM = """You prepare a case file for claim verification. Do NOT judge whether anything is true.
Split the text into ATOMIC statements, each attributed to the person or body who made it (as written in the text).
Reply with JSON only:
{"entities":[{"name":"...","kind":"official|company|person|committee"}],
 "claims":[{"id":"c1","text":"...","attributed_to":"...","claim_type":"date_gap|amount|competition_status|flow_through|rule_text|relationship|policy_internal|legal_conclusion|other",
            "subject_private_individual":false,"params":{}}]}
params by claim_type:
- date_gap: {"entity_canonical":"<exact legal name>","a":"formation_date","b":"award_date","days":N,"comparison":"==|<=|>="}
- amount: {"claimed_total":<number in dollars>}
- competition_status: {"entity_canonical":"...","claimed_status":"competed|not_competed"}
- flow_through: {"entity_canonical":"...","claimed_share_min":<0..1>}
- others: {"entity_canonical":"..."} if a company is the subject, else {}
Use legal_conclusion for statements of wrongdoing, intent, or legality. Set subject_private_individual true for statements
about a private person's family, marriage, or personal records. Do not invent claims that are not in the text."""

PRIVATE_HINTS = re.compile(r"\b(married|marriage|spouse|wife|husband|divorce|family member|girlfriend|boyfriend)\b", re.I)


def enforce_scope(claim: RecordClaim) -> RecordClaim:
    """Code overrides the model: wrongdoing vocabulary -> legal conclusion; personal-relationship words -> private."""
    upd = {}
    if lint(claim.text):
        upd["claim_type"] = ClaimType.LEGAL_CONCLUSION
    if PRIVATE_HINTS.search(claim.text):
        upd["subject_private_individual"] = True
    return claim.model_copy(update=upd) if upd else claim


def run(llm, case_text: str):
    out = llm.call_json("intake", [{"role": "system", "content": SYSTEM}, {"role": "user", "content": case_text}],
                        max_tokens=4000, schema=INTAKE)
    claims, skipped = [], []
    for i, c in enumerate(out.get("claims", []), 1):
        try:
            c = {**c, "id": c.get("id") or f"c{i}"}
            claims.append(enforce_scope(RecordClaim(**c)))
        except (ValidationError, TypeError) as e:
            skipped.append(f"claim {i}: {type(e).__name__}")
    return claims, out.get("entities", []), skipped
