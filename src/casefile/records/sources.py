"""Evidence retrieval behind one interface.

The live source is deliberately two-stage: You.com Search discovers candidate URLs, then
You.com Contents extracts only those exact URLs. A model-supplied URL is never fetched, and
search-engine wrapper URLs are rejected rather than decoded into a guessed destination.
"""
import hashlib
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from urllib.parse import urlparse

from .models import DocType, Document


SEARCH_WRAPPER_HOSTS = frozenset({
    "bing.com", "duckduckgo.com", "google.com", "search.yahoo.com", "you.com",
})
TRANSCRIPT_HOSTS = frozenset({"youtube.com", "youtu.be"})


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def validate_source_url(url: str) -> tuple[bool, str]:
    """Return whether *url* is a direct, public HTTP(S) source URL and why not."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "malformed URL"
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False, "URL must use http or https and include a hostname"
    host = _host(url)
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".localhost"):
        return False, "local URLs are not evidence sources"
    if host in SEARCH_WRAPPER_HOSTS:
        return False, "search/result wrapper URL is not a source document"
    return True, ""


def extract_source_urls(text: str) -> tuple[list[str], list[dict[str, str]]]:
    """Extract direct URLs from case text, preserving rejected wrappers for the audit."""
    # Pasted markdown often escapes URL punctuation (``https\://example\.gov``).
    normalized = re.sub(r"\\([:/._?&=%#-])", r"\1", text)
    raw = re.findall(r"https?://[^\s<>\]\[\"']+", normalized)
    accepted, rejected, seen = [], [], set()
    for candidate in raw:
        candidate = candidate.rstrip(".,;:!?)\\")
        if candidate in seen:
            continue
        seen.add(candidate)
        ok, reason = validate_source_url(candidate)
        if ok:
            accepted.append(candidate)
        else:
            rejected.append({"url": candidate, "reason": reason})
    return accepted, rejected


class EvidenceSource(ABC):
    @abstractmethod
    def search(self, query: str, k: int = 5) -> list[Document]: ...

    @abstractmethod
    def fetch(self, key: str) -> Document:
        """Fetch by document id or URL. Raises KeyError if unavailable (callers record collection_failed)."""


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


class FixtureSource(EvidenceSource):
    def __init__(self, docs: list[Document]):
        self._by_id = {d.id: d for d in docs}
        self._by_url = {d.url: d for d in docs}

    def search(self, query: str, k: int = 5) -> list[Document]:
        q = _tokens(query)
        scored = sorted(self._by_id.values(), key=lambda d: (-len(q & _tokens(d.title + " " + d.text)), d.id))
        return [d for d in scored if q & _tokens(d.title + " " + d.text)][:k]

    def fetch(self, key: str) -> Document:
        if key in self._by_id:
            return self._by_id[key]
        if key in self._by_url:
            return self._by_url[key]
        raise KeyError(key)

    @property
    def documents(self) -> list[Document]:
        return list(self._by_id.values())


class YouComSource(EvidenceSource):
    """Live You.com Search -> exact-URL Contents adapter for records mode.

    Search is discovery only. Contents is called solely for direct URLs returned by Search
    or supplied in ``seed_urls``. ``fetch`` is cache-only, so an investigator cannot make the
    adapter scrape an invented URL by passing it as a document id.
    """

    def __init__(self, client=None, *, seed_urls=(), include_domains=None,
                 purpose: str = "records_case", case_id: str | None = None):
        if client is None:
            from ..youcom import YouCom
            client = YouCom()
        self.client = client
        self.include_domains = list(include_domains or []) or None
        self.purpose = purpose
        self.case_id = case_id                      # Supabase cases.id; links every You.com request to its case
        self._by_id: dict[str, Document] = {}
        self._by_url: dict[str, Document] = {}
        self._titles: dict[str, str] = {}
        self._seed_urls: list[str] = []
        self._seeds_loaded = False
        self.queries: list[str] = []
        self.accepted_urls: list[str] = []
        self.rejected_urls: list[dict[str, str]] = []
        self.errors: list[str] = []
        for url in seed_urls:
            self._consider_url(str(url), self._seed_urls)

    def _case_kw(self) -> dict:
        return {"case_id": self.case_id} if self.case_id else {}

    @staticmethod
    def _doc_type(url: str, source_kind: str = "web") -> DocType:
        host = _host(url)
        if host in TRANSCRIPT_HOSTS or source_kind == "transcript":
            return DocType.TRANSCRIPT
        if host.endswith(".gov") or host.endswith(".mil"):
            return DocType.PRIMARY
        return DocType.SECONDARY

    @staticmethod
    def _when(value) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str) and value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return datetime.now(timezone.utc)

    def _consider_url(self, url: str, out: list[str], *, title: str | None = None) -> None:
        ok, reason = validate_source_url(url)
        if not ok:
            item = {"url": url, "reason": reason}
            if item not in self.rejected_urls:
                self.rejected_urls.append(item)
            return
        if self.include_domains and not any(
            _host(url) == d.removeprefix("www.") or _host(url).endswith("." + d.removeprefix("www."))
            for d in self.include_domains
        ):
            return
        if url not in out:
            out.append(url)
        if title:
            self._titles[url] = title

    def _as_document(self, row: dict) -> Document | None:
        url = str(row.get("url") or "")
        ok, reason = validate_source_url(url)
        if not ok:
            item = {"url": url, "reason": reason}
            if item not in self.rejected_urls:
                self.rejected_urls.append(item)
            return None
        # Keep the extracted bytes intact: YouCom hashes the unmodified body
        # before storing it, so trimming here would invalidate its digest.
        text = str(row.get("markdown") or row.get("text") or "")
        if len(text.strip()) < 80:
            self.errors.append(f"contents: no usable text extracted from {url}")
            return None
        digest = str(row.get("content_sha256") or hashlib.sha256(text.encode()).hexdigest())
        doc_id = "ydc_" + hashlib.sha256(f"{url}\0{digest}".encode()).hexdigest()[:20]
        source_kind = str(row.get("source_kind") or "web")
        return Document(
            id=doc_id,
            url=url,
            doc_type=self._doc_type(url, source_kind),
            title=str(row.get("title") or self._titles.get(url) or url),
            publisher=str(row.get("domain") or _host(url)),
            retrieved_at=self._when(row.get("fetched_at") or row.get("retrieved_at")),
            sha256=digest,
            text=text,
        )

    def _fetch_urls(self, urls: list[str]) -> list[Document]:
        pending = [u for u in urls if u not in self._by_url]
        added: list[Document] = []
        for start in range(0, len(pending), 10):
            batch = pending[start:start + 10]
            if not batch:
                continue
            result = self.client.contents(batch, purpose=self.purpose, **self._case_kw())
            req = result.get("request") or {}
            if req.get("error"):
                self.errors.append(f"contents: {req['error']}")
            returned = set()
            for row in result.get("docs") or []:
                doc = self._as_document(row)
                if doc is None:
                    continue
                returned.add(doc.url)
                self._by_id[doc.id] = doc
                self._by_url[doc.url] = doc
                if doc.url not in self.accepted_urls:
                    self.accepted_urls.append(doc.url)
                added.append(doc)
            for url in batch:
                if url not in returned and not any(url in error for error in self.errors):
                    self.errors.append(f"contents: URL returned no extractable document: {url}")
        return added

    def _load_seeds(self) -> list[Document]:
        if self._seeds_loaded:
            return []
        self._seeds_loaded = True
        return self._fetch_urls(self._seed_urls)

    def search(self, query: str, k: int = 5) -> list[Document]:
        query = query.strip()
        self.queries.append(query)
        errors_before = len(self.errors)
        self._load_seeds()
        result = self.client.search(
            query,
            include_domains=self.include_domains,
            count=max(5, min(20, k * 2)),
            extraction=None,
            purpose=self.purpose,
            **self._case_kw(),
        )
        req = result.get("request") or {}
        if req.get("error"):
            self.errors.append(f"search: {req['error']}")

        urls: list[str] = []
        data = result.get("data") or {}
        for section in ("web", "news"):
            for hit in (data.get("results") or {}).get(section, []) or []:
                self._consider_url(str(hit.get("url") or ""), urls, title=hit.get("title"))
        self._fetch_urls(urls)

        # Search-engine order leads. Relevant explicit source hints fill any remaining slots.
        ordered, seen = [], set()
        for url in urls:
            doc = self._by_url.get(url)
            if doc and doc.id not in seen:
                ordered.append(doc)
                seen.add(doc.id)
        q = _tokens(query)
        hinted = sorted(
            self._by_id.values(),
            key=lambda d: (-len(q & _tokens(d.title + " " + d.text)), d.id),
        )
        for doc in hinted:
            if doc.id not in seen and q & _tokens(doc.title + " " + doc.text):
                ordered.append(doc)
                seen.add(doc.id)
        ordered.sort(key=lambda d: d.doc_type != DocType.PRIMARY)
        if not ordered and (req.get("error") or len(self.errors) > errors_before):
            raise KeyError("You.com collection failed; no source document was collected")
        return ordered[:k]

    def fetch(self, key: str) -> Document:
        if key in self._by_id:
            return self._by_id[key]
        if key in self._by_url:
            return self._by_url[key]
        # Deliberately no network call here: unknown model output cannot become a scrape target.
        raise KeyError(key)

    @property
    def documents(self) -> list[Document]:
        return list(self._by_id.values())

    def audit(self) -> dict:
        return {
            "provider": "you.com",
            "retrieval_flow": "search_then_exact_url_contents",
            "queries": list(self.queries),
            "accepted_urls": list(self.accepted_urls),
            "rejected_urls": list(self.rejected_urls),
            "errors": list(self.errors),
        }


def load_fixtures(path) -> FixtureSource:
    """Load documents from a JSON file (id, url, doc_type, publisher, title, retrieved_at, text, sha256)."""
    import json
    from pathlib import Path

    return FixtureSource([Document(**d) for d in json.loads(Path(path).read_text())])
