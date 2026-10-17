"""You.com grounding client. Every call, including failures, is stored (Store) for memory and audit.

Endpoints (https://you.com/docs/api-reference, auth header X-API-Key, env YDC_API_KEY):
  search    POST https://ydc-index.io/v1/search     retrieval only
  contents  POST https://ydc-index.io/v1/contents   retrieval only
  research  POST https://api.you.com/v1/research    You.com runs its own LLM synthesis

Crusoe is our only model provider, so agents use search + contents at run time. research() is
off unless allow_external_llm=True, which is meant for offline corpus building after the organizers
confirm it's allowed.

Page text is untrusted data. Hand it to agents through as_evidence(), never as instructions.
"""
import hashlib
import os
import random
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crusoe_client import load_env  # noqa: E402
from casefile.store import Store  # noqa: E402

SEARCH_URL = "https://ydc-index.io/v1/search"
CONTENTS_URL = "https://ydc-index.io/v1/contents"
RESEARCH_URL = "https://api.you.com/v1/research"

# Primary sources the constitution may cite. Docs from anywhere else are stored but marked untrusted.
TRUSTED_DOMAINS = {
    "acquisition.gov", "justice.gov", "ofac.treasury.gov", "sec.gov", "treasury.gov",
    "fincen.gov", "ecfr.gov", "law.cornell.edu", "consumerfinance.gov", "federalregister.gov",
    "pages.nist.gov", "nist.gov", "ffiec.gov", "fdic.gov", "occ.gov", "federalreserve.gov",
    "consumercomplianceoutlook.org", "fedpaymentsimprovement.org", "ftc.gov",
}


def _domain(url: str) -> str:
    host = urlparse(url).hostname or ""
    return host.removeprefix("www.")


def is_trusted(url: str) -> bool:
    d = _domain(url)
    return any(d == t or d.endswith("." + t) for t in TRUSTED_DOMAINS)


def as_evidence(doc: dict, max_chars: int = 6000) -> str:
    """Wrap stored page text for a prompt so the model treats it as data."""
    body = (doc.get("markdown") or "")[:max_chars]
    return (f'<external-content source="{doc["url"]}" doc_id="{doc["id"]}" trusted="{str(doc.get("trusted")).lower()}">\n'
            f"{body}\n</external-content>")


class YouCom:
    def __init__(self, store: Store | None = None, max_tries: int = 5) -> None:
        load_env()
        key = os.environ.get("YDC_API_KEY")
        if not key:
            raise SystemExit("YDC_API_KEY is not set (put it in .env.youcom)")
        self.http = httpx.Client(timeout=90, headers={"X-API-Key": key, "Content-Type": "application/json"})
        self.store = store or Store()
        self.max_tries = max_tries

    # ---------- transport: retry, then always record ----------
    def _post(self, endpoint: str, url: str, body: dict, purpose: str | None, case_id: str | None) -> tuple[dict, dict | None]:
        t0, status, data, err = time.monotonic(), None, None, None
        for attempt in range(self.max_tries):
            try:
                r = self.http.post(url, json=body)
                status = r.status_code
                if status in (429, 500, 502, 503, 504) and attempt < self.max_tries - 1:
                    wait = float(r.headers.get("Retry-After") or min(30.0, 2.0 ** attempt))
                    time.sleep(wait + random.uniform(0, 0.5))
                    continue
                if status >= 400:
                    err = r.text[:2000]
                else:
                    data = r.json()
                break
            except httpx.HTTPError as e:  # network errors: retry, then record
                err = f"{type(e).__name__}: {e}"
                if attempt == self.max_tries - 1:
                    break
                time.sleep(min(30.0, 2.0 ** attempt))
        req = self.store.insert("grounding_requests", {
            "endpoint": endpoint, "request": body, "response": data, "http_status": status, "error": err,
            "latency_ms": int((time.monotonic() - t0) * 1000), "purpose": purpose, "case_id": case_id,
        })
        return req, data

    def _save_doc(self, url: str, title: str | None, markdown: str | None, request_id: str, kind: str = "web") -> dict | None:
        if not url or not markdown:
            return None
        sha = hashlib.sha256(markdown.encode()).hexdigest()
        existing = self.store.find_one("grounding_docs", url=url, content_sha256=sha)
        if existing:
            return existing
        return self.store.insert("grounding_docs", {
            "url": url, "domain": _domain(url), "title": title, "markdown": markdown, "content_sha256": sha,
            "source_kind": kind, "trusted": is_trusted(url), "first_request_id": request_id,
        })

    # ---------- public API ----------
    def search(self, query: str, *, include_domains: list[str] | None = None, count: int = 5,
               extraction: str | None = "full_page", freshness: str | None = None,
               purpose: str | None = None, case_id: str | None = None) -> dict:
        """Search; with extraction='full_page' each web result's markdown is stored as a doc."""
        body: dict = {"query": query, "count": count}
        if include_domains:
            body["include_domains"] = include_domains
        if freshness:
            body["freshness"] = freshness
        if extraction:
            body["extraction"] = {"extraction_mode": extraction}
            if extraction == "full_page":
                body["extraction"]["full_page"] = {"extraction_formats": ["markdown"]}
        req, data = self._post("search", SEARCH_URL, body, purpose, case_id)
        docs = []
        for section in ("web", "news"):
            for res in (data or {}).get("results", {}).get(section, []) or []:
                c = res.get("contents") or {}
                text = c.get("markdown") or "\n".join(c.get("highlights") or [])
                doc = self._save_doc(res.get("url"), res.get("title"), text, req["id"], section)
                if doc:
                    docs.append(doc)
        return {"request": req, "data": data, "docs": docs}

    def contents(self, urls: list[str], *, purpose: str | None = None, case_id: str | None = None) -> dict:
        if not 1 <= len(urls) <= 10:
            raise ValueError("You.com Contents accepts 1 to 10 URLs per request")
        req, data = self._post("contents", CONTENTS_URL, {"urls": urls, "formats": ["markdown", "metadata"]}, purpose, case_id)
        docs = [d for item in (data or []) if (d := self._save_doc(item.get("url"), item.get("title"), item.get("markdown"), req["id"]))]
        return {"request": req, "data": data, "docs": docs}

    def research(self, question: str, *, effort: str = "lite", include_domains: list[str] | None = None,
                 allow_external_llm: bool = False, purpose: str | None = None) -> dict:
        if not allow_external_llm:
            raise PermissionError("You.com Research runs a non-Crusoe LLM; pass allow_external_llm=True only for offline corpus work")
        body: dict = {"input": question, "research_effort": effort}
        if include_domains:
            body["source_control"] = {"include_domains": include_domains}
        req, data = self._post("research", RESEARCH_URL, body, purpose, None)
        docs = []
        for s in ((data or {}).get("output") or {}).get("sources", []) or []:
            doc = self._save_doc(s.get("url"), s.get("title"), "\n\n".join(s.get("snippets") or []), req["id"], "research_source")
            if doc:
                docs.append(doc)
        return {"request": req, "data": data, "docs": docs}
