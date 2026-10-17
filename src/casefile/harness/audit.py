"""Append-only, hash-chained audit trail. Editing or deleting any line breaks verify_chain()."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def events(self) -> list[dict]:
        return [json.loads(l) for l in self.path.read_text().splitlines() if l.strip()]

    @staticmethod
    def _hash(prev: str, body: dict) -> str:
        return hashlib.sha256((prev + json.dumps(body, sort_keys=True)).encode()).hexdigest()

    def append(self, type_: str, case_id: str, data: dict) -> dict:
        ev = self.events()
        body = {"seq": len(ev) + 1, "ts": datetime.now(timezone.utc).isoformat(), "type": type_, "case_id": case_id, "data": data}
        prev = ev[-1]["hash"] if ev else "genesis"
        rec = {**body, "prev": prev, "hash": self._hash(prev, body)}
        with self.path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        return rec

    def verify_chain(self) -> bool:
        prev = "genesis"
        for i, e in enumerate(self.events(), 1):
            body = {k: e[k] for k in ("seq", "ts", "type", "case_id", "data")}
            if e["seq"] != i or e["prev"] != prev or e["hash"] != self._hash(prev, body):
                return False
            prev = e["hash"]
        return True
