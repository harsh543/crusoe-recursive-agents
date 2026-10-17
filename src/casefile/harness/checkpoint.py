"""Append-only checkpoints: one JSON line per saved state, latest wins. A crash resumes from the last completed node."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .state import CaseState


class CheckpointStore:
    def __init__(self, directory):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, case_id: str) -> Path:
        return self.dir / (re.sub(r"[^A-Za-z0-9_.-]", "_", case_id) + ".jsonl")

    def save(self, state: CaseState) -> None:
        line = json.dumps({"saved_at": datetime.now(timezone.utc).isoformat(), "state": state.model_dump(mode="json")})
        with self._path(state.case_id).open("a") as f:
            f.write(line + "\n")

    def latest(self, case_id: str):
        p = self._path(case_id)
        if not p.exists():
            return None
        for line in reversed(p.read_text().splitlines()):
            try:
                return CaseState.model_validate(json.loads(line)["state"])
            except Exception:                    # a torn last line must not lose earlier checkpoints
                continue
        return None
