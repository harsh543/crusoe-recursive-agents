"""Markdown report. Pseudonymized by default; quotes are shown verbatim except for pseudonyms."""
from .models import Verdict


def render_markdown(*, title, claims, results, docs, pseudonyms, reveal=False) -> str:
    by_claim = {r.claim_id: r for r in results}
    rows, out_scope = [], []
    for c in claims:
        r = by_claim.get(c.id)
        if r is None:
            continue
        ev = []
        for f in r.findings:
            d = docs[f.doc_id]
            ev.append(f'{f.field} = {f.value}: "{f.quote}" '
                      f'({d.title}, {d.publisher}, retrieved {d.retrieved_at:%Y-%m-%d}, {d.url})')
        entity = c.params.get("entity_canonical")
        if entity and r.verdict != Verdict.OUT_OF_SCOPE:        # nothing is researched for out-of-scope statements
            ev.insert(0, f"Entity checked: {entity}")
        if r.conflicts:
            ev.append("Sources disagree on: " + ", ".join(r.conflicts))
        if r.verdict == Verdict.OUT_OF_SCOPE:
            out_scope.append(c)
            ev.append("Attributed, not verified (outside what public records can establish).")
        rows.append(f"| {c.id} | {c.text} | {c.attributed_to} | **{r.verdict.value}** | " + "<br>".join(ev + [r.explanation]) + " |")
    counts = {v.value: sum(1 for r in results if r.verdict == v) for v in Verdict}
    lines = [f"# {title}", "", "**Not a legal finding.** This report checks individual, attributed statements against "
             "cited records. It does not assess anyone's intent or conduct.", "",
             "| # | Claim (as stated) | Attributed to | Verdict | Evidence |", "|---|---|---|---|---|", *rows, "",
             "## What the record does and does not establish", "",
             "- Verdict counts: " + ", ".join(f"{k}: {v}" for k, v in counts.items() if v),
             "- `supported` / `contradicted` mean the quoted records match or do not match the specific statement, "
             "as recomputed by code.",
             "- `insufficient_evidence` means the cited records do not settle the statement.",
             f"- {len(out_scope)} statement(s) are conclusions or concern private individuals and were attributed but not researched."]
    text = "\n".join(lines) + "\n"
    return text if reveal else pseudonyms.apply(text)
