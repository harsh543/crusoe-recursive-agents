"""Analyst review queue. Escalations and insufficient-evidence cases land here; the analyst's decision is the stored label."""
import json
from pathlib import Path


class ReviewQueue:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def _rows(self):
        return [json.loads(l) for l in self.path.read_text().splitlines() if l.strip()]

    def _append(self, row):
        with self.path.open("a") as f:
            f.write(json.dumps(row) + "\n")

    def tasks(self) -> list[dict]:
        out = {}
        for r in self._rows():
            if r["kind"] == "open":
                out[r["task_id"]] = {**r, "status": "open"}
            elif r["kind"] == "decision" and r["task_id"] in out:
                out[r["task_id"]].update(status="decided", decision=r["decision"], analyst=r["analyst"], note=r.get("note", ""))
        return list(out.values())

    def open_task(self, case_id: str, outcome: str, packet: dict) -> str:
        tid = f"task_{len(self.tasks()) + 1}"
        self._append({"kind": "open", "task_id": tid, "case_id": case_id, "outcome": outcome, "packet": packet})
        return tid

    def decide(self, task_id: str, *, analyst: str, decision: str, note: str = "") -> None:
        t = next((t for t in self.tasks() if t["task_id"] == task_id), None)
        if t is None or t["status"] != "open":
            raise ValueError(f"task {task_id} is unknown or already decided")
        self._append({"kind": "decision", "task_id": task_id, "analyst": analyst, "decision": decision, "note": note})

    def labels(self) -> dict:
        return {t["case_id"]: t["decision"] for t in self.tasks() if t["status"] == "decided"}
