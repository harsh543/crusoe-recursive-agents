"""Append-only trace. Step ids (s001, s002, ...) are what the Attributor cites."""
import json
from pathlib import Path


class Trace:
    def __init__(self, path: Path | None = None, context_id: str | None = None):
        self.context_id = context_id
        self.steps: list[dict] = []
        self.path = Path(path) if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("")

    def add(self, role: str, kind: str, **fields) -> str:
        sid = f"s{len(self.steps) + 1:03d}"
        rec = {"step": sid, "role": role, "kind": kind, **fields}
        if self.context_id:
            rec["context_id"], rec["task_id"] = self.context_id, f"{self.context_id}:{sid}"
        self.steps.append(rec)
        if self.path:
            with self.path.open("a") as f:
                f.write(json.dumps(rec, default=str) + "\n")
        return sid
