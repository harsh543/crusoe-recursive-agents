"""Claim-level verifier. Every pass/fail and every computed number comes from this code, not a model."""
import re
from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher, get_close_matches

from ..verifier import Failure, VerificationResult
from .models import CLOSURE_VERDICTS, OUT_OF_SCOPE_TYPES, ClaimType, DocType, Verdict
from .neutrality import lint

MONEY_FIELDS = {"award_amount", "prime_total", "subaward_total"}
VALUE_IN_QUOTE_FIELDS = {"formation_date", "award_date", "extent_competed", *MONEY_FIELDS}
_ENTITY_RE = re.compile(r"((?:[A-Z][\w&.'-]*\s+){1,5}(?:LLC|Inc\.?|Corp\.?|Ltd\.?|LLP))")
_MONEY_RE = re.compile(
    r"(?<![\w.])(?:USD\s*|\$\s*)?(-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(trillion|billion|million|thousand|tn|bn|mm|[tbmk])?\b",
    re.IGNORECASE,
)
_MONEY_FACTORS = {
    "": 1.0,
    "k": 1_000.0,
    "thousand": 1_000.0,
    "m": 1_000_000.0,
    "mm": 1_000_000.0,
    "million": 1_000_000.0,
    "b": 1_000_000_000.0,
    "bn": 1_000_000_000.0,
    "billion": 1_000_000_000.0,
    "t": 1_000_000_000_000.0,
    "tn": 1_000_000_000_000.0,
    "trillion": 1_000_000_000_000.0,
}


@dataclass(frozen=True)
class RecordsPolicy:
    min_independent_publishers: int = 2
    lookalike_ratio: float = 0.8
    amount_tolerance: float = 0.001


def _norm(t: str) -> str:
    t = t.replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", t).strip().lower()


def _value_in_quote(field: str, value: str, quote: str) -> bool:
    """Money is compared numerically (143000000 matches '$143,000,000'); other fields as normalized text."""
    if field in MONEY_FIELDS:
        try:
            v = _money(str(value))
        except ValueError:
            return False
        return any(abs(v - n) < 0.5 for n in _money_values(quote))
    if field == "extent_competed":
        return _norm(value).replace("_", " ") in _norm(quote).replace("_", " ")
    return _norm(value) in _norm(quote)


def _money_values(s: str) -> list[float]:
    values = []
    for number, unit in _MONEY_RE.findall(s):
        values.append(float(number.replace(",", "")) * _MONEY_FACTORS[unit.lower()])
    return values


def _money(s: str) -> float:
    values = _money_values(s)
    if len(values) != 1:
        raise ValueError(f"expected one money value, found {len(values)}")
    return values[0]


def _date_value(s: str) -> date:
    value = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", s.strip(), flags=re.IGNORECASE)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value[:10]):
        return date.fromisoformat(value[:10])
    value = re.sub(r"\b(Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.", r"\1", value,
                   flags=re.IGNORECASE)
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"unsupported date value {s!r}")


def _first(findings, field, docs):
    """Prefer a primary-source value for a field."""
    cands = [f for f in findings if f.field == field]
    cands.sort(key=lambda f: docs[f.doc_id].doc_type != DocType.PRIMARY if f.doc_id in docs else True)
    return cands[0] if cands else None


def _expected(claim, findings, docs, policy):
    """(expected verdict | None if not computable, explanation). Recomputed from the findings only."""
    p, t = claim.params, claim.claim_type
    if t == ClaimType.DATE_GAP:
        a, b = _first(findings, p.get("a", ""), docs), _first(findings, p.get("b", ""), docs)
        if not a or not b:
            return Verdict.INSUFFICIENT_EVIDENCE, f"required fields missing: {p.get('a')}, {p.get('b')}"
        gap = (_date_value(b.value) - _date_value(a.value)).days
        cmp_, n = p.get("comparison", "=="), p["days"]
        holds = {"==": gap == n, "<=": gap <= n, ">=": gap >= n}[cmp_]
        return (Verdict.SUPPORTED if holds else Verdict.CONTRADICTED), f"recomputed gap {gap} days; claim says {cmp_} {n}"
    if t == ClaimType.AMOUNT:
        seen, vals = set(), []
        for f in findings:
            if f.field == "award_amount" and (f.doc_id, f.value) not in seen:
                seen.add((f.doc_id, f.value))
                vals.append(_money(f.value))
        if not vals:
            return Verdict.INSUFFICIENT_EVIDENCE, "no award_amount findings"
        total, claimed = sum(vals), p["claimed_total"]
        ok = abs(total - claimed) <= policy.amount_tolerance * claimed
        return (Verdict.SUPPORTED if ok else Verdict.CONTRADICTED), f"recomputed total {total:,.0f}; claim says {claimed:,.0f}"
    if t == ClaimType.COMPETITION_STATUS:
        f = _first(findings, "extent_competed", docs)
        if not f:
            return Verdict.INSUFFICIENT_EVIDENCE, "no extent_competed finding"
        v = _norm(f.value).replace("_", " ")
        status = "not_competed" if ("not competed" in v or "not available" in v) else "competed"
        ok = status == p["claimed_status"]
        return (Verdict.SUPPORTED if ok else Verdict.CONTRADICTED), f"record says {status}; claim says {p['claimed_status']}"
    if t == ClaimType.FLOW_THROUGH:
        s, pr = _first(findings, "subaward_total", docs), _first(findings, "prime_total", docs)
        if not s or not pr:
            return Verdict.INSUFFICIENT_EVIDENCE, "subaward_total / prime_total missing"
        subaward, prime = _money(s.value), _money(pr.value)
        if prime <= 0 or subaward < 0 or subaward > prime:
            return Verdict.INSUFFICIENT_EVIDENCE, (
                f"invalid flow-through amounts (subaward {subaward:,.0f}, prime {prime:,.0f}); "
                "fields may be reversed or refer to different awards"
            )
        share = subaward / prime
        ok = share >= p["claimed_share_min"]
        return (Verdict.SUPPORTED if ok else Verdict.CONTRADICTED), f"recomputed share {share:.2f}; claim says >= {p['claimed_share_min']}"
    return None, ""


def verify_claim(claim, result, docs: dict, policy: RecordsPolicy | None = None) -> VerificationResult:
    policy = policy or RecordsPolicy()
    fails: list[Failure] = []
    verdict, findings = result.verdict, list(result.findings)

    # scope: legal conclusions and private individuals are reported as attributed, never researched
    out_of_scope = claim.claim_type in OUT_OF_SCOPE_TYPES or claim.subject_private_individual
    if out_of_scope:
        if verdict != Verdict.OUT_OF_SCOPE or findings:
            fails.append(Failure("scope_respected", f"claim {claim.id} is out of scope (legal conclusion or private "
                                 f"individual): verdict must be out_of_scope with no research findings"))
        return VerificationResult(failures=tuple(fails))
    if verdict == Verdict.OUT_OF_SCOPE:
        fails.append(Failure("scope_respected", f"claim {claim.id} is verifiable from public records; out_of_scope is not allowed"))
        return VerificationResult(failures=tuple(fails))

    closure = verdict in CLOSURE_VERDICTS

    for f in findings:                                              # quotes are verbatim and values come from quotes
        d = docs.get(f.doc_id)
        if d is None:
            fails.append(Failure("quotes_verbatim", f"finding {f.field}: document {f.doc_id} not found", (f.doc_id,)))
        elif _norm(f.quote) not in _norm(d.text):
            near = get_close_matches(f.quote, [ln.strip() for ln in d.text.splitlines() if ln.strip()], n=1, cutoff=0.5)
            hint = f"; closest line in the document: {near[0]!r}" if near else ""
            fails.append(Failure("quotes_verbatim", f"finding {f.field}: quote not found verbatim in {f.doc_id}{hint}", (f.doc_id,)))
        elif f.field in VALUE_IN_QUOTE_FIELDS and not _value_in_quote(f.field, f.value, f.quote):
            fails.append(Failure("quotes_verbatim", f"finding {f.field}: value {f.value!r} is not in its quote", (f.doc_id,)))
    if closure and not findings:
        fails.append(Failure("quotes_verbatim", f"{verdict.value} needs at least one cited finding"))

    cited = [docs[f.doc_id] for f in findings if f.doc_id in docs]
    if closure and cited:                                           # primary source, or independent corroboration
        if not any(d.doc_type == DocType.PRIMARY for d in cited):
            pubs = {d.publisher for d in cited}
            if len(pubs) < policy.min_independent_publishers:
                fails.append(Failure("source_adequate", f"no primary source and only {len(pubs)} independent publisher(s) "
                                     f"(need {policy.min_independent_publishers})", tuple(d.id for d in cited)))

    canonical = claim.params.get("entity_canonical")
    if canonical and cited:
        uniq = {d.id: d for d in cited}.values()
        has = [d for d in uniq if _norm(canonical) in _norm(d.text)]
        for d in uniq:                                              # a similar-but-different name in any cited document fails
            if d in has:
                continue
            near = [c for c in _ENTITY_RE.findall(d.text)
                    if SequenceMatcher(None, c.lower(), canonical.lower()).ratio() >= policy.lookalike_ratio]
            if near:
                fails.append(Failure("entity_match", f"document {d.id} names '{near[0]}', not '{canonical}' (possible look-alike entity)", (d.id,)))
        if not has and not any(f.check == "entity_match" for f in fails):
            fails.append(Failure("entity_match", f"no cited document mentions '{canonical}'", tuple(d.id for d in uniq)))

    if verdict != Verdict.COLLECTION_FAILED:
        try:
            expected, why = _expected(claim, findings, docs, policy)
        except (KeyError, ValueError) as e:
            expected, why = Verdict.INSUFFICIENT_EVIDENCE, f"inputs not computable ({type(e).__name__}: {e})"
        if expected is not None and expected != verdict:
            fails.append(Failure("computation_correct", f"{why} -> code expects {expected.value}, got {verdict.value}"))

    additive = {"award_amount"} if claim.claim_type == ClaimType.AMOUNT else set()   # summands, not rival values
    by_field: dict[str, set] = {}
    for f in findings:
        if f.field not in additive:
            by_field.setdefault(f.field, set()).add(_norm(f.value))
    for fld, vals in by_field.items():
        if len(vals) > 1 and fld not in result.conflicts:
            fails.append(Failure("conflicts_addressed", f"sources disagree on {fld}: {sorted(vals)}; list it in conflicts"))

    bad = lint(result.explanation)
    if bad:
        fails.append(Failure("neutral_language", f"wrongdoing vocabulary outside quotes: {bad}"))
    return VerificationResult(failures=tuple(fails))
