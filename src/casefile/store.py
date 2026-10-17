"""Supabase persistence via PostgREST, with a local JSONL fallback so the pipeline runs before Supabase is wired.

Uses SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (backend only; never ship the service key to the UI).
Without them, rows go to data/store/<table>.jsonl with the same shape, so nothing is lost and it can be
replayed into Supabase later with `python -m casefile.store --replay`.
"""
import json
import os
import sys
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crusoe_client import load_env  # noqa: E402

LOCAL = Path(__file__).resolve().parents[2] / "data" / "store"


class Store:
    def __init__(self) -> None:
        load_env()
        self.url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        self.remote = bool(self.url and key)
        if self.remote:
            headers = {"apikey": key, "Content-Type": "application/json", "Prefer": "return=representation"}
            if key.startswith("eyJ"):  # legacy service_role JWT; new sb_secret_ keys go in apikey only
                headers["Authorization"] = f"Bearer {key}"
            self.http = httpx.Client(base_url=f"{self.url}/rest/v1", timeout=30, headers=headers)

    @property
    def backend(self) -> str:
        return "supabase" if self.remote else f"jsonl ({LOCAL})"

    def insert(self, table: str, row: dict) -> dict:
        if self.remote:
            r = self.http.post(f"/{table}", json=row)
            r.raise_for_status()
            return r.json()[0]
        row = {"id": str(uuid.uuid4()), **row}
        LOCAL.mkdir(parents=True, exist_ok=True)
        with (LOCAL / f"{table}.jsonl").open("a") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
        return row

    def upsert_ignore(self, table: str, row: dict, on_conflict: str) -> dict | None:
        """Insert unless a row with the same `on_conflict` key exists. Returns the new row, or None if it already existed."""
        if self.remote:
            r = self.http.post(f"/{table}", params={"on_conflict": on_conflict}, json=row,
                               headers={"Prefer": "resolution=ignore-duplicates,return=representation"})
            r.raise_for_status()
            rows = r.json()
            return rows[0] if rows else None
        keys = on_conflict.split(",")
        if self.find_one(table, **{k: row[k] for k in keys}):
            return None
        return self.insert(table, row)

    def upsert_ignore_many(self, table: str, rows: list[dict], on_conflict: str) -> int:
        """Bulk insert, skipping rows whose `on_conflict` key already exists. Returns the number newly inserted."""
        if not rows:
            return 0
        if self.remote:
            r = self.http.post(f"/{table}", params={"on_conflict": on_conflict}, json=rows,
                               headers={"Prefer": "resolution=ignore-duplicates,return=representation"})
            r.raise_for_status()
            return len(r.json())
        return sum(self.upsert_ignore(table, row, on_conflict) is not None for row in rows)

    def select(self, table: str, order: str | None = None, **eq) -> list[dict]:
        if self.remote:
            params = {k: f"eq.{v}" for k, v in eq.items()}
            if order:
                params["order"] = order
            r = self.http.get(f"/{table}", params=params)
            r.raise_for_status()
            return r.json()
        path = LOCAL / f"{table}.jsonl"
        rows = [json.loads(l) for l in path.read_text().splitlines()] if path.is_file() else []
        return [r for r in rows if all(r.get(k) == v for k, v in eq.items())]

    def update(self, table: str, patch: dict, **eq) -> None:
        if not self.remote:
            raise RuntimeError("update needs Supabase; the JSONL fallback is append-only")
        r = self.http.patch(f"/{table}", params={k: f"eq.{v}" for k, v in eq.items()}, json=patch)
        r.raise_for_status()

    def delete(self, table: str, **eq) -> None:
        if not self.remote:
            raise RuntimeError("delete needs Supabase")
        if not eq:
            raise ValueError("refusing an unfiltered delete")
        r = self.http.delete(f"/{table}", params={k: f"eq.{v}" for k, v in eq.items()})
        r.raise_for_status()

    def find_one(self, table: str, **eq) -> dict | None:
        if self.remote:
            r = self.http.get(f"/{table}", params={k: f"eq.{v}" for k, v in eq.items()} | {"limit": 1})
            r.raise_for_status()
            rows = r.json()
            return rows[0] if rows else None
        path = LOCAL / f"{table}.jsonl"
        if not path.is_file():
            return None
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if all(row.get(k) == v for k, v in eq.items()):
                return row
        return None

    def rpc(self, fn: str, **args) -> list[dict]:
        if not self.remote:
            raise RuntimeError(f"rpc {fn} needs Supabase; local fallback has no full-text search")
        r = self.http.post(f"/rpc/{fn}", json=args)
        r.raise_for_status()
        return r.json()


NATURAL_KEYS = {"grounding_docs": ("url", "content_sha256"), "rag_policy_chunks": ("chunk_id",)}


def replay() -> None:
    """Push data/store/*.jsonl into Supabase in FK order, keeping the local ids."""
    s = Store()
    if not s.remote:
        raise SystemExit("set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY first")
    remap: dict[str, str] = {}  # local id -> id already in Supabase for the same natural key
    for table in ("grounding_requests", "grounding_docs", "policy_clauses", "rag_policy_chunks"):
        path = LOCAL / f"{table}.jsonl"
        if not path.is_file():
            continue
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        natural_key = NATURAL_KEYS.get(table, ("id",))
        inserted = 0
        for row in rows:
            case_id = row.get("case_id")
            if case_id and not _is_uuid(case_id):
                # case_id is an FK to cases; free-text labels belong in purpose
                row["purpose"] = f"{row.get('purpose') or ''}|label:{case_id}".lstrip("|")
                row["case_id"] = None
            for fk in ("doc_id", "first_request_id"):
                if row.get(fk) in remap:
                    row[fk] = remap[row[fk]]
            r = s.http.post(f"/{table}", json=row, params={"on_conflict": ",".join(natural_key)},
                            headers={"Prefer": "resolution=ignore-duplicates,return=representation"})
            if r.status_code >= 400:
                raise SystemExit(f"{table} row {row.get('id')}: HTTP {r.status_code} {r.text[:300]}")
            if r.json():
                inserted += 1
            else:  # already in Supabase, possibly under another id: point later FKs at that row
                existing = s.find_one(table, **{k: row[k] for k in natural_key})
                if existing and existing["id"] != row["id"]:
                    remap[row["id"]] = existing["id"]
        print(f"{table}: {inserted} inserted, {len(rows) - inserted} already present")


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


if __name__ == "__main__" and "--replay" in sys.argv:
    replay()
