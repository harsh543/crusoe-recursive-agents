#!/usr/bin/env python3
"""Import saved You.com evidence and reviewed policy chunks into Casefile memory.

With SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY configured, this writes directly
to Supabase. Otherwise it writes the same rows to data/store/*.jsonl for replay.
The migration supabase/migrations/0003_fraud_policy_memory.sql must be applied
before direct or replayed Supabase ingestion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from casefile.store import Store  # noqa: E402
from casefile.youcom import is_trusted  # noqa: E402


RESEARCH_DIR = ROOT / "data" / "fraud_detection" / "research" / "youcom"
CHUNKS_PATH = ROOT / "data" / "fraud_detection" / "rag" / "verified_policy_chunks_batch_01.jsonl"
ENVELOPE_PATHS = (
    RESEARCH_DIR / "search_vendor_payment_controls.json",
    RESEARCH_DIR / "search_sanctions_controls.json",
    RESEARCH_DIR / "search_procurement_price_controls.json",
    RESEARCH_DIR / "us_vendor_policy_research.json",
    RESEARCH_DIR / "selected_policy_contents_batch_01.json",
    RESEARCH_DIR / "selected_policy_contents_batch_02.json",
)

CHUNK_COLUMNS = {
    "chunk_id",
    "rule_id",
    "text",
    "domain",
    "source_title",
    "source_url",
    "source_date",
    "source_page",
    "source_section",
    "authority_level",
    "jurisdiction",
    "effective_from",
    "effective_to",
    "access_scope",
    "retrieved_at",
    "content_hash",
    "supersedes_chunk_id",
    "review_status",
    "binding_status",
    "applicability",
    "evidence_fields",
    "recommended_action",
    "retrieval_source_url",
    "notes",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _domain(url: str) -> str:
    return (urlparse(url).hostname or "").removeprefix("www.")


def _endpoint_name(url: str) -> str:
    if url.endswith("/search"):
        return "search"
    if url.endswith("/contents"):
        return "contents"
    if url.endswith("/research"):
        return "research"
    raise ValueError(f"Unsupported saved endpoint: {url}")


def _save_request(store: Store, path: Path, envelope: dict[str, Any]) -> dict[str, Any]:
    provenance = envelope["provenance"]
    fingerprint = _sha(_canonical_json(envelope))
    existing = store.find_one("grounding_requests", request_fingerprint=fingerprint)
    if existing:
        return existing
    return store.insert("grounding_requests", {
        "endpoint": _endpoint_name(provenance["endpoint"]),
        "request": provenance["request"],
        "response": envelope["response"],
        "http_status": 200,
        "error": None,
        "latency_ms": None,
        "purpose": "fraud_policy_batch_01",
        "case_id": None,
        "requested_at": provenance["retrieved_at"],
        "request_fingerprint": fingerprint,
        "source_file": str(path.relative_to(ROOT)),
    })


def _save_doc(
    store: Store,
    *,
    url: str | None,
    title: str | None,
    markdown: str | None,
    request_id: str,
    fetched_at: str,
    source_kind: str,
) -> tuple[dict[str, Any] | None, bool]:
    if not url or not markdown:
        return None, False
    content_hash = _sha(markdown)
    existing = store.find_one("grounding_docs", url=url, content_sha256=content_hash)
    if existing:
        return existing, False
    return store.insert("grounding_docs", {
        "url": url,
        "domain": _domain(url),
        "title": title,
        "markdown": markdown,
        "content_sha256": content_hash,
        "source_kind": source_kind,
        "trusted": is_trusted(url),
        "first_request_id": request_id,
        "fetched_at": fetched_at,
    }), True


def _docs_from_envelope(
    store: Store,
    envelope: dict[str, Any],
    request_id: str,
) -> tuple[list[dict[str, Any]], int]:
    endpoint = _endpoint_name(envelope["provenance"]["endpoint"])
    fetched_at = envelope["provenance"]["retrieved_at"]
    response = envelope["response"]
    candidates: list[tuple[str | None, str | None, str | None, str]] = []

    if endpoint == "search":
        for source_kind in ("web", "news"):
            for item in ((response.get("results") or {}).get(source_kind) or []):
                contents = item.get("contents") or {}
                markdown = contents.get("markdown") or "\n\n".join(contents.get("highlights") or [])
                candidates.append((item.get("url"), item.get("title"), markdown, source_kind))
    elif endpoint == "contents":
        for item in response:
            candidates.append((item.get("url"), item.get("title"), item.get("markdown"), "web"))
    else:
        for item in (((response.get("output") or {}).get("sources")) or []):
            candidates.append((
                item.get("url"),
                item.get("title"),
                "\n\n".join(item.get("snippets") or []),
                "research_source",
            ))

    docs: list[dict[str, Any]] = []
    inserted = 0
    for url, title, markdown, kind in candidates:
        doc, was_inserted = _save_doc(
            store,
            url=url,
            title=title,
            markdown=markdown,
            request_id=request_id,
            fetched_at=fetched_at,
            source_kind=kind,
        )
        if doc:
            docs.append(doc)
        inserted += int(was_inserted)
    return docs, inserted


def _save_chunk(store: Store, chunk: dict[str, Any], docs_by_url: dict[str, dict[str, Any]]) -> bool:
    if store.find_one("rag_policy_chunks", chunk_id=chunk["chunk_id"]):
        return False
    row = {key: chunk.get(key) for key in CHUNK_COLUMNS}
    retrieval_url = chunk.get("retrieval_source_url") or chunk["source_url"]
    row["doc_id"] = (docs_by_url.get(retrieval_url) or {}).get("id")
    row["metadata"] = {key: value for key, value in chunk.items() if key not in CHUNK_COLUMNS}
    store.insert("rag_policy_chunks", row)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-supabase",
        action="store_true",
        help="Fail instead of using the local JSONL fallback when Supabase credentials are absent.",
    )
    args = parser.parse_args()

    missing = [path for path in (*ENVELOPE_PATHS, CHUNKS_PATH) if not path.is_file()]
    if missing:
        raise SystemExit("Missing ingestion inputs:\n- " + "\n- ".join(str(path) for path in missing))

    store = Store()
    if args.require_supabase and not store.remote:
        raise SystemExit(
            "Supabase credentials are not configured. Put SUPABASE_URL and "
            "SUPABASE_SERVICE_ROLE_KEY in .env.local; never expose the service-role key to the UI."
        )

    docs_by_url: dict[str, dict[str, Any]] = {}
    inserted_requests = 0
    inserted_docs = 0
    for path in ENVELOPE_PATHS:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        fingerprint = _sha(_canonical_json(envelope))
        request_existed = store.find_one("grounding_requests", request_fingerprint=fingerprint) is not None
        request = _save_request(store, path, envelope)
        inserted_requests += int(not request_existed)
        docs, count = _docs_from_envelope(store, envelope, request["id"])
        inserted_docs += count
        for doc in docs:
            docs_by_url[doc["url"]] = doc

    chunks = [json.loads(line) for line in CHUNKS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    inserted_chunks = sum(_save_chunk(store, chunk, docs_by_url) for chunk in chunks)
    unlinked = sum(
        1 for chunk in chunks
        if (chunk.get("retrieval_source_url") or chunk["source_url"]) not in docs_by_url
    )
    if unlinked:
        raise SystemExit(f"Ingestion failed closed: {unlinked} policy chunks did not link to a stored source document")

    print(f"backend: {store.backend}")
    print(f"requests: {inserted_requests} inserted, {len(ENVELOPE_PATHS) - inserted_requests} already present")
    print(f"documents: {inserted_docs} inserted or versioned")
    print(f"policy chunks: {inserted_chunks} inserted, {len(chunks) - inserted_chunks} already present")


if __name__ == "__main__":
    main()
