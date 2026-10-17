"""Dataset-level fraud analytics (SQL over raw events). Account-scoped vendor tools cannot see cross-account structure;
this can. Backed by stdlib sqlite3 so it needs no service; the MCP server in fraud_engine_mcp.py exposes the same functions.
Output carries counts and masked peer ids only (no emails, no raw device fingerprints)."""
import hashlib
import sqlite3


def _mask(account_id: str) -> str:
    return "peer_" + hashlib.sha256(account_id.encode()).hexdigest()[:6]


class FraudDataset:
    def __init__(self, events: list[dict]):
        """events: {account_id, device_fp, beneficiary (nullable), amount, ts}"""
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.execute("create table events (account_id text, device_fp text, beneficiary text, amount real, ts text)")
        self.db.executemany("insert into events values (:account_id,:device_fp,:beneficiary,:amount,:ts)", events)

    def inspect_device_sharing(self, account_id: str) -> dict:
        fps = [r[0] for r in self.db.execute("select distinct device_fp from events where account_id=?", (account_id,))]
        if not fps:
            return {"device_fingerprints": 0, "shared_accounts": 1, "peer_accounts": [], "peers_paying_same_beneficiary": 0}
        marks = ",".join("?" * len(fps))
        peers = sorted(r[0] for r in self.db.execute(
            f"select distinct account_id from events where device_fp in ({marks}) and account_id<>?", (*fps, account_id)))
        own_ben = [r[0] for r in self.db.execute(
            "select distinct beneficiary from events where account_id=? and beneficiary is not null", (account_id,))]
        same_ben = 0
        if peers and own_ben:
            pm, bm = ",".join("?" * len(peers)), ",".join("?" * len(own_ben))
            same_ben = self.db.execute(
                f"select count(distinct account_id) from events where account_id in ({pm}) and beneficiary in ({bm})",
                (*peers, *own_ben)).fetchone()[0]
        return {"device_fingerprints": len(fps), "shared_accounts": 1 + len(peers),
                "peer_accounts": [_mask(p) for p in peers], "peers_paying_same_beneficiary": same_ben}

    def velocity_outliers(self, window_minutes: int = 60, threshold_count: int = 5) -> list[dict]:
        rows = self.db.execute("select account_id, ts from events order by account_id, ts").fetchall()
        from datetime import datetime, timedelta
        out, by = [], {}
        for a, ts in rows:
            by.setdefault(a, []).append(datetime.fromisoformat(ts.replace("Z", "+00:00")))
        for a, ts in by.items():
            best = 0
            for i, t in enumerate(ts):
                best = max(best, sum(1 for u in ts[i:] if u - t <= timedelta(minutes=window_minutes)))
            if best >= threshold_count:
                out.append({"account": _mask(a), "peak_burst": best})
        return sorted(out, key=lambda r: -r["peak_burst"])[:20]
