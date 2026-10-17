"""The records source fails closed: discover first, extract exact URLs, never infer links."""
import hashlib
from pathlib import Path

import pytest

from casefile.records.models import DocType
from casefile.records.gate import RecordsGate
from casefile.records.models import ClaimType, RecordClaim, Verdict
from casefile.records.orchestrator import verify_one
from casefile.records.sources import YouComSource, extract_source_urls, validate_source_url
from casefile.trace import Trace
from tests.fakes import FakeLLM


DIRECT = "https://www.justice.gov/example/direct-record"
WRAPPER = "https://www.google.com/search?q=https://www.justice.gov/example/guessed-record"


class FakeYouCom:
    def __init__(self, *, search_error=None):
        self.search_error = search_error
        self.search_calls = []
        self.contents_calls = []

    def search(self, query, **kwargs):
        self.search_calls.append((query, kwargs))
        return {
            "request": {"id": "req-search", "error": self.search_error},
            "data": None if self.search_error else {"results": {"web": [
                {"url": WRAPPER, "title": "Not a source"},
                {"url": DIRECT, "title": "Direct DOJ record"},
            ]}},
            "docs": [],
        }

    def contents(self, urls, **kwargs):
        self.contents_calls.append((list(urls), kwargs))
        docs = []
        for url in urls:
            text = f"Record for Northwind Signal Media LLC at {url}"
            docs.append({
                "id": "stored-id",
                "url": url,
                "domain": url.split("/")[2].removeprefix("www."),
                "title": None,
                "markdown": text,
                "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "source_kind": "web",
                "fetched_at": "2026-10-17T12:00:00+00:00",
            })
        return {"request": {"id": "req-contents", "error": None}, "docs": docs, "data": []}


def test_search_wrapper_is_not_a_direct_source():
    assert not validate_source_url(WRAPPER)[0]
    assert validate_source_url(DIRECT)[0]


def test_escaped_markdown_urls_are_extracted_but_wrappers_stay_rejected():
    text = (r"[bad](https\://www\.google\.com/search?q=https\://justice\.gov/inferred) "
            r"[good](https\://www\.justice\.gov/example/direct-record)")
    accepted, rejected = extract_source_urls(text)
    assert accepted == [DIRECT]
    assert rejected == [{"url": "https://www.google.com/search?q=https://justice.gov/inferred",
                         "reason": "search/result wrapper URL is not a source document"}]


def test_youcom_search_then_contents_uses_only_returned_direct_url():
    client = FakeYouCom()
    source = YouComSource(client)

    docs = source.search("Northwind Signal Media contract", k=5)

    assert client.search_calls[0][1]["extraction"] is None
    assert client.contents_calls == [([DIRECT], {"purpose": "records_case"})]
    assert [d.url for d in docs] == [DIRECT]
    assert docs[0].doc_type == DocType.PRIMARY
    assert source.fetch(docs[0].id) == docs[0]
    assert source.audit()["rejected_urls"] == [
        {"url": WRAPPER, "reason": "search/result wrapper URL is not a source document"}
    ]


def test_fetch_of_unknown_or_invented_url_never_calls_contents():
    client = FakeYouCom()
    source = YouComSource(client)

    with pytest.raises(KeyError):
        source.fetch("https://justice.gov/model-invented")

    assert client.contents_calls == []


def test_explicit_direct_source_hint_is_extracted_once_before_search():
    client = FakeYouCom()
    source = YouComSource(client, seed_urls=[DIRECT, WRAPPER])

    source.search("Northwind Signal Media", k=5)

    # The direct seed is fetched; the same URL returned by search is not fetched twice.
    assert client.contents_calls == [([DIRECT], {"purpose": "records_case"})]
    assert WRAPPER not in source.accepted_urls


def test_search_transport_failure_is_collection_error_when_nothing_was_collected():
    source = YouComSource(FakeYouCom(search_error="upstream timeout"))

    with pytest.raises(KeyError, match="collection failed"):
        source.search("a claim", k=5)


def test_unusable_contents_is_collection_failure_not_empty_evidence():
    class ShortContents(FakeYouCom):
        def contents(self, urls, **kwargs):
            self.contents_calls.append((list(urls), kwargs))
            return {"request": {"id": "c", "error": None}, "docs": [
                {"url": DIRECT, "domain": "justice.gov", "markdown": "Too short",
                 "source_kind": "web", "fetched_at": "2026-10-17T12:00:00+00:00"}
            ], "data": []}

    source = YouComSource(ShortContents())

    with pytest.raises(KeyError, match="collection failed"):
        source.search("a claim", k=5)

    assert source.audit()["errors"] == [f"contents: no usable text extracted from {DIRECT}"]


def test_contents_preserves_whitespace_covered_by_provider_hash():
    client = FakeYouCom()
    raw_text = "\n  " + ("Complete government record. " * 5) + "  \n"

    def contents(urls, **kwargs):
        client.contents_calls.append((list(urls), kwargs))
        return {"request": {"id": "c", "error": None}, "docs": [{
            "url": DIRECT,
            "domain": "justice.gov",
            "markdown": raw_text,
            "content_sha256": hashlib.sha256(raw_text.encode()).hexdigest(),
            "source_kind": "web",
            "fetched_at": "2026-10-17T12:00:00+00:00",
        }], "data": []}

    client.contents = contents
    doc = YouComSource(client).search("a claim", k=5)[0]

    assert doc.text == raw_text
    assert doc.sha256 == hashlib.sha256(raw_text.encode()).hexdigest()


def test_public_integrity_examples_contain_only_direct_source_urls():
    root = Path(__file__).resolve().parents[1] / "data" / "casefiles" / "public_integrity"
    cases = sorted(p for p in root.glob("*.md") if p.name != "README.md")
    assert len(cases) == 5
    for case in cases:
        accepted, rejected = extract_source_urls(case.read_text())
        assert accepted, case.name
        assert not rejected, f"{case.name}: {rejected}"


def test_public_integrity_examples_keep_the_verified_source_urls():
    root = Path(__file__).resolve().parents[1] / "data" / "casefiles" / "public_integrity"
    expected = {
        "fat_leonard.md": {
            "https://www.justice.gov/usao-sdca/pr/leonard-glenn-francis-sentenced-15-years-prison-massive-bribery-fraud-and",
            "https://www.justice.gov/usao-sdca/pr/malaysian-defense-contractor-leonard-francis-pleads-guilty-corruption-conspiracy",
            "https://www.justice.gov/usao-sdca/pr/us-navy-admiral-sentenced-lying-feds-about-his-relationship-foreign-defense-contractor",
        },
        "duke_cunningham.md": {
            "https://www.justice.gov/archive/tax/usaopress/2006/txdv06cas60303.1.pdf",
        },
        "mississippi_tanf.md": {
            "https://www.osa.ms.gov/news/auditor-demands-repayment-misspent-welfare-money",
            "https://www.osa.ms.gov/news/state-auditor-shad-white-testifies-us-house-ways-means-committee-welfare-case",
        },
        "martin_kao.md": {
            "https://www.propublica.org/article/fbi-susan-collins-navatek-campaign-donations-investigation",
            "https://www.propublica.org/article/debunking-susan-collins-fbi-navatek-investigation-claims",
        },
    }

    for filename, required_urls in expected.items():
        accepted, rejected = extract_source_urls((root / filename).read_text())
        assert not rejected, f"{filename}: {rejected}"
        assert required_urls <= set(accepted), f"{filename}: missing {sorted(required_urls - set(accepted))}"


def test_unrelated_us_attorney_removal_report_is_not_a_cunningham_seed():
    case = (Path(__file__).resolve().parents[1] / "data" / "casefiles" / "public_integrity" /
            "duke_cunningham.md").read_text()
    assert "oig.justice.gov/sites/default/files/legacy/special/s0809a/final.pdf" not in case


def test_live_source_flows_through_investigator_verifier_and_gate():
    registry_url = "https://registry.example.gov/entities/northwind"
    award_url = "https://awards.example.gov/awards/001"
    registry_text = ("Entity: Northwind Signal Media LLC\nDate of formation: 2025-02-03\n"
                     "Status: Active\nFile number: 7788")
    award_text = ("Recipient: Northwind Signal Media LLC\nAward date: 2025-02-14\n"
                  "Award status: Completed\nAward number: AW-001")

    class TwoPageYouCom(FakeYouCom):
        pages = {registry_url: registry_text, award_url: award_text}

        def search(self, query, **kwargs):
            self.search_calls.append((query, kwargs))
            return {"request": {"id": "s", "error": None}, "data": {"results": {"web": [
                {"url": registry_url, "title": "Entity record"},
                {"url": award_url, "title": "Award record"},
            ]}}, "docs": []}

        def contents(self, urls, **kwargs):
            self.contents_calls.append((list(urls), kwargs))
            docs = []
            for url in urls:
                text = self.pages[url]
                docs.append({"url": url, "domain": url.split("/")[2], "title": None,
                             "markdown": text, "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
                             "source_kind": "web", "fetched_at": "2026-10-17T12:00:00+00:00"})
            return {"request": {"id": "c", "error": None}, "docs": docs, "data": []}

    def doc_id(url, text):
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        return "ydc_" + hashlib.sha256(f"{url}\0{content_hash}".encode()).hexdigest()[:20]

    reg_id, award_id = doc_id(registry_url, registry_text), doc_id(award_url, award_text)
    llm = FakeLLM({"records_investigator": [
        {"action": "tool", "tool": "search_documents", "args": {"query": "Northwind formation award dates"}},
        {"action": "tool", "tool": "read_document", "args": {"doc_id": reg_id}},
        {"action": "tool", "tool": "read_document", "args": {"doc_id": award_id}},
        {"action": "final", "verdict": "supported", "findings": [
            {"field": "formation_date", "value": "2025-02-03",
             "quote": "Date of formation: 2025-02-03", "doc_id": reg_id},
            {"field": "award_date", "value": "2025-02-14",
             "quote": "Award date: 2025-02-14", "doc_id": award_id},
        ], "explanation": "The cited dates are eleven days apart.", "conflicts": []},
    ]})
    claim = RecordClaim(id="c1", text="Northwind was formed 11 days before the award.",
                        attributed_to="Senator Hale", claim_type=ClaimType.DATE_GAP,
                        params={"entity_canonical": "Northwind Signal Media LLC", "a": "formation_date",
                                "b": "award_date", "days": 11, "comparison": "=="})

    run = verify_one(claim, YouComSource(TwoPageYouCom()), llm, Trace(), RecordsGate())

    assert run.result.verdict == Verdict.SUPPORTED
    assert run.verification.passed
    assert run.receipt.written


def test_case_id_is_forwarded_to_search_and_contents_when_set():
    client = FakeYouCom()
    source = YouComSource(client, seed_urls=[DIRECT], purpose="records_case", case_id="case-uuid-1")
    source.search("Northwind Signal Media", k=5)
    assert client.search_calls and all(kw.get("case_id") == "case-uuid-1" for _, kw in client.search_calls)
    assert client.contents_calls and all(kw.get("case_id") == "case-uuid-1" for _, kw in client.contents_calls)
