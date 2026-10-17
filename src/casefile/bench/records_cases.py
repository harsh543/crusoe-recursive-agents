"""Seeded synthetic case files for the records benchmark: fictional names, known truth, injected faults."""
import hashlib
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from ..records.models import ClaimResult, ClaimType, DocType, Document, Finding, RecordClaim, Verdict

NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)
FAULTS = ["none", "lookalike_entity", "missing_doc", "conflicting_source", "off_by_one"]
SPLITS = {"dev": [0], "heldout": [1]}
COMPANIES = ["Northwind Signal Media LLC", "Evergreen Harbor Media LLC", "Pinecrest Creative LLC", "Ridgeway Consulting Group LLC",
             "Maple Court Strategies LLC", "Bluebird Outreach LLC", "Copperline Analytics LLC", "Stonebridge Media LLC",
             "Harborlight Partners LLC", "Juniper Ridge Marketing LLC"]
SENATORS = ["Senator Hale", "Senator Ortiz", "Senator Lindqvist"]
OFFICIALS = ["Secretary Rowan", "Secretary Idowu", "Secretary Marek"]


@dataclass
class RecordsCase:
    id: str
    fault: str
    casefile: str
    claims: list[RecordClaim]
    docs: list[Document]
    expected: dict          # claim id -> Verdict value (oracle data; agents never see it)
    ideal: dict             # claim id -> ClaimResult a perfect agent would give
    needs_conflict: set     # claim ids where a correct answer that cites rival values must list the conflict


def _doc(id, text, doc_type=DocType.PRIMARY, publisher="Federal Award Database", title=None):
    return Document(id=id, url=f"https://records.example.test/{id}", doc_type=doc_type, title=title or f"SYNTHETIC record {id}",
                    publisher=publisher, retrieved_at=NOW, sha256=hashlib.sha256(text.encode()).hexdigest(), text=text)


def _f(field, value, quote, doc_id):
    return Finding(field=field, value=value, quote=quote, doc_id=doc_id)


def build_case(seed: int, fault: str) -> RecordsCase:
    rng = random.Random(f"{seed}-{fault}")
    prime, sub, other = rng.sample(COMPANIES, 3)
    sen, sec = rng.choice(SENATORS), rng.choice(OFFICIALS)
    formation = date(2025, 1, 10) + timedelta(days=rng.randint(0, 40))
    gap = rng.randint(5, 25)
    award = formation + timedelta(days=gap)
    a1, a2 = rng.randint(80, 160) * 1_000_000, rng.randint(30, 90) * 1_000_000
    competed = rng.choice(["NOT COMPETED", "FULL AND OPEN COMPETITION"])
    share = rng.choice([0.35, 0.62, 0.8])
    sub_total = int(round(a1 * share, -5))

    claimed_days = gap + rng.choice([0, 0, 0, -2, -1, 1, 2])
    if fault == "off_by_one":
        claimed_days = gap - 1
    claimed_total = a1 + a2 if rng.random() < 0.6 else int((a1 + a2) * 1.1)
    claimed_status = rng.choice(["competed", "not_competed"])
    actual_status = "not_competed" if competed == "NOT COMPETED" else "competed"

    look = prime.replace(" LLC", " Holdings LLC")
    docs = []
    if fault == "lookalike_entity":
        docs.append(_doc("d_reg", f"Entity: {look}\nFile number: 4410\nDate of formation: {formation - timedelta(days=900):%Y-%m-%d}\nStatus: Active",
                         publisher="State Business Registry"))
    elif fault != "missing_doc":
        docs.append(_doc("d_reg", f"Entity: {prime}\nFile number: 7788\nDate of formation: {formation:%Y-%m-%d}\nStatus: Active",
                         publisher="State Business Registry"))
    docs += [
        _doc("d_award", f"Recipient: {prime}\nAward date: {award:%Y-%m-%d}\nAward amount: ${a1:,}\nExtent competed: {competed}"),
        _doc("d_award2", f"Recipient: {other}\nAward date: {award:%Y-%m-%d}\nAward amount: ${a2:,}\nExtent competed: LIMITED COMPETITION"),
        _doc("d_sub", f"Prime recipient: {prime}\nPrime award total: ${a1:,}\nSubawardee: {sub}\nSubaward total: ${sub_total:,}",
             publisher="Federal Subaward Database"),
        _doc("d_n1", f"Outlet One reports that {prime} was a newly formed company when it received the award.", DocType.SECONDARY, "Outlet One"),
    ]
    if fault == "conflicting_source":
        wrong = formation + timedelta(days=rng.choice([-9, -6, 6, 9]))
        docs.append(_doc("d_n2", f"Outlet Two reports that {prime} was formed on {wrong:%Y-%m-%d}.", DocType.SECONDARY, "Outlet Two"))

    claims = [
        RecordClaim(id="c1", text=f"{prime} was formed {claimed_days} days before it received the award.", attributed_to=sen,
                    claim_type=ClaimType.DATE_GAP, params={"entity_canonical": prime, "a": "formation_date", "b": "award_date",
                                                           "days": claimed_days, "comparison": "=="}),
        RecordClaim(id="c2", text=f"The two awards, to {prime} and {other}, totaled ${claimed_total // 1_000_000} million.",
                    attributed_to=sen, claim_type=ClaimType.AMOUNT, params={"claimed_total": claimed_total}),
        RecordClaim(id="c3", text=f"The {prime} award went through a {'competitive process' if claimed_status == 'competed' else 'process with no competition'}.",
                    attributed_to=sec, claim_type=ClaimType.COMPETITION_STATUS,
                    params={"entity_canonical": prime, "claimed_status": claimed_status}),
        RecordClaim(id="c4", text=f"Most of the money was passed on as a subaward to {sub}.", attributed_to=sen,
                    claim_type=ClaimType.FLOW_THROUGH, params={"entity_canonical": sub, "claimed_share_min": 0.5}),
        RecordClaim(id="c5", text="Department policy requires the Secretary to approve every contract over $100 million.",
                    attributed_to=sen, claim_type=ClaimType.POLICY_INTERNAL),
        RecordClaim(id="c6", text="This was a fraudulent scheme to enrich insiders.", attributed_to="A commentator",
                    claim_type=ClaimType.LEGAL_CONCLUSION),
        RecordClaim(id="c7", text=f"The chief executive of {sub} is married to the {sec.split()[0]}'s former spokesperson.",
                    attributed_to=sen, claim_type=ClaimType.RELATIONSHIP, subject_private_individual=True),
    ]
    casefile = ("# Case file (synthetic benchmark case)\n\nAll names and documents are fictional.\n\n" +
                "\n".join(f'{i}. {c.attributed_to}: "{c.text}"' for i, c in enumerate(claims, 1)) + "\n")

    gap_holds = claimed_days == gap
    e = {"c1": ("insufficient_evidence" if fault in ("lookalike_entity", "missing_doc")
                else ("supported" if gap_holds else "contradicted")),
         "c2": "supported" if claimed_total == a1 + a2 else "contradicted",
         "c3": "supported" if claimed_status == actual_status else "contradicted",
         "c4": "supported" if share >= 0.5 else "contradicted",
         "c5": "insufficient_evidence", "c6": "out_of_scope", "c7": "out_of_scope"}
    R = lambda cid, fs=(), ex="Checked against the cited records.": ClaimResult(claim_id=cid, verdict=Verdict(e[cid]), findings=list(fs), explanation=ex)
    ideal = {
        "c1": R("c1", [] if e["c1"] == "insufficient_evidence" else
                [_f("formation_date", f"{formation:%Y-%m-%d}", f"Date of formation: {formation:%Y-%m-%d}", "d_reg"),
                 _f("award_date", f"{award:%Y-%m-%d}", f"Award date: {award:%Y-%m-%d}", "d_award")]),
        "c2": R("c2", [_f("award_amount", f"${a1:,}", f"Award amount: ${a1:,}", "d_award"),
                       _f("award_amount", f"${a2:,}", f"Award amount: ${a2:,}", "d_award2")]),
        "c3": R("c3", [_f("extent_competed", competed, f"Extent competed: {competed}", "d_award")]),
        "c4": R("c4", [_f("prime_total", f"${a1:,}", f"Prime award total: ${a1:,}", "d_sub"),
                       _f("subaward_total", f"${sub_total:,}", f"Subaward total: ${sub_total:,}", "d_sub")]),
        "c5": R("c5"), "c6": R("c6"), "c7": R("c7"),
    }
    return RecordsCase(id=f"R{seed}-{fault}", fault=fault, casefile=casefile, claims=claims, docs=docs, expected=e, ideal=ideal,
                       needs_conflict={"c1"} if fault == "conflicting_source" else set())


def split_cases(split: str) -> list[RecordsCase]:
    return [build_case(s, f) for s in SPLITS[split] for f in FAULTS]
