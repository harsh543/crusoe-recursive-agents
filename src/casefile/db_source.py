"""Supabase-backed evidence source: the investigator's tools read accounts, device_events and transactions from the
database instead of Case.raw. Returns exactly the shape Case.raw[source] has, so the verifier and features do not change."""
from datetime import datetime, timezone

from .store import Store

SOURCES = ("device_history", "transactions")


def _iso(value: str) -> str:
    d = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


class SupabaseCaseSource:
    def __init__(self, store: Store | None = None):
        self.store = store or Store()
        if not self.store.remote:
            raise RuntimeError("SupabaseCaseSource needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")

    def resolve_account(self, email: str, tenant_id: str) -> str:
        rows = self.store.select("accounts", tenant_id=tenant_id, email=email.strip().lower())
        if not rows:
            raise LookupError("unknown email")
        return rows[0]["account_id"]

    def load(self, source: str, account_id: str) -> dict:
        if source == "device_history":
            acct = (self.store.select("accounts", account_id=account_id) or [{}])[0]
            events = self.store.select("device_events", order="occurred_at.asc", account_id=account_id)
            return {"home_country": acct.get("home_country"),
                    "devices": [{"id": e["device_id"], "country": e["country"], "first_seen": _iso(e["occurred_at"]),
                                 "known": e["known"]} for e in events if e["kind"] == "device_seen"],
                    "mfa_resets": [_iso(e["occurred_at"]) for e in events if e["kind"] == "mfa_reset"]}
        if source == "transactions":
            out = []
            for t in self.store.select("transactions", order="occurred_at.asc", account_id=account_id):
                row = {"id": t["tx_id"], "kind": t["kind"], "amount": float(t["amount"]), "ts": _iso(t["occurred_at"])}
                if t["beneficiary"] is not None:
                    row.update(beneficiary=t["beneficiary"], beneficiary_new=t["beneficiary_new"])
                out.append(row)
            return {"transactions": out}
        raise KeyError(source)


def seed_cases(store: Store, cases) -> int:
    """Bulk-write bench cases' accounts, devices, MFA resets and transactions. Idempotent. Returns rows newly inserted."""
    accts, devs, txs = {}, [], []
    for case in cases:
        dh, tx = case.raw["device_history"], case.raw["transactions"]["transactions"]
        accts[case.account_id] = {"account_id": case.account_id, "tenant_id": case.tenant_id,
                                  "email": case.email.lower(), "home_country": dh.get("home_country")}
        devs += [{"account_id": case.account_id, "kind": "device_seen", "device_id": d["id"], "country": d["country"],
                  "known": d["known"], "occurred_at": d["first_seen"]} for d in dh["devices"]]
        devs += [{"account_id": case.account_id, "kind": "mfa_reset", "device_id": "", "occurred_at": ts} for ts in dh["mfa_resets"]]
        txs += [{"account_id": case.account_id, "tx_id": t["id"], "kind": t["kind"], "amount": t["amount"],
                 "beneficiary": t.get("beneficiary"), "beneficiary_new": t.get("beneficiary_new"), "occurred_at": t["ts"]}
                for t in tx]
    _same_keys(devs), _same_keys(txs)
    return (store.upsert_ignore_many("accounts", list(accts.values()), "account_id")
            + store.upsert_ignore_many("device_events", devs, "account_id,kind,device_id,occurred_at")
            + store.upsert_ignore_many("transactions", txs, "account_id,tx_id"))


def _same_keys(rows: list[dict]) -> None:
    """PostgREST bulk insert needs every object to have the same keys."""
    keys = set().union(*rows) if rows else set()
    for r in rows:
        for k in keys:
            r.setdefault(k, None)


def seed_case(store: Store, case) -> int:
    return seed_cases(store, [case])
