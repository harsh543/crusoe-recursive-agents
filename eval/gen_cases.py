"""Build Casefile's mock source systems and alert cases from Sparkov background data.

Reads   data/sparkov/*.csv          (third_party/sparkov output, card purchases per customer)
Writes  data/casefile/              what the agents' tools may query
          customers.csv  devices.csv  auth_events.csv  beneficiaries.csv  transactions.csv  alerts.json
        data/oracle/                ground truth; never exposed to agents
          labels.json  story_events.csv

Background per customer: Sparkov card purchases (its own is_fraud rows are dropped so labels come only
from our storylines), one long-lived home device, regular logins, payroll credits, rent and utility
transfers to established beneficiaries.

Storylines injected before each alert (policy ato_v1, docs/DATA_SOURCES.md):
  ato           new device in a new country -> MFA reset -> optional card testing -> new beneficiary
                -> large transfer                                                         => escalate
  new_phone     new device in the home country -> payroll -> first rent to a new landlord
                at the usual rent amount                                                  => close_benign
  travel        home device logs in abroad, card purchases abroad, no auth changes        => close_benign
  source_down   device history is unavailable for the whole run (tool fault)              => insufficient_evidence

Usage: python eval/gen_cases.py [--seed 7]
"""
import argparse
import csv
import json
import random
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPARKOV = ROOT / "data" / "sparkov"
OUT = ROOT / "data" / "casefile"
ORACLE = ROOT / "data" / "oracle"

DATA_START = datetime(2026, 7, 18, tzinfo=timezone.utc)
WINDOW_DAYS = 45
FOREIGN = [("RO", "Bucharest"), ("VN", "Ho Chi Minh City"), ("BR", "Sao Paulo"), ("NG", "Lagos"),
           ("ID", "Jakarta"), ("UA", "Kyiv"), ("PH", "Manila")]
TRAVEL = [("MX", "Cancun"), ("FR", "Paris"), ("JP", "Tokyo"), ("IT", "Rome"), ("GB", "London")]
PHONES = ["iPhone 15", "iPhone 14", "Pixel 8", "Galaxy S24", "Galaxy A54", "Pixel 7a"]
ATO_PAYEES = ["Velo Holdings", "Northgate Trading LLC", "Kestrel Digital Ltd", "Amberline Exports",
              "Oriel Capital Partners", "Halcyon Supply Co"]
LANDLORDS = ["Maple Court Apartments", "Riverside Property Mgmt", "Oak Hill Residences",
             "Summit Lofts LLC", "Cedar Grove Rentals"]


def iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_ip(rng: random.Random, foreign: bool) -> str:
    # RFC 5737 documentation ranges, so no real address appears in the demo
    return f"{'203.0.113' if foreign else '198.51.100'}.{rng.randint(1, 254)}"


class Builder:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.customers, self.devices, self.auth, self.benes, self.txns = [], [], [], [], []
        self.story_events: list[dict] = []  # oracle: which rows a storyline injected
        self.n = defaultdict(int)

    def nid(self, prefix: str) -> str:
        self.n[prefix] += 1
        return f"{prefix}_{self.n[prefix]:05d}"

    def tag(self, table: str, row_id: str, case_id: str, step: str) -> None:
        self.story_events.append({"case_id": case_id, "table": table, "row_id": row_id, "step": step})

    # ---------- background ----------
    def load_sparkov(self) -> dict[str, dict]:
        people: dict[str, dict] = {}
        for f in sorted(SPARKOV.glob("*.csv")):
            if f.name == "customers.csv":
                continue
            with f.open() as fh:
                for r in csv.DictReader(fh, delimiter="|"):
                    p = people.setdefault(r["acct_num"], {"row": r, "card": []})
                    if r["is_fraud"] == "1":
                        continue
                    p["card"].append(r)
        return people

    def add_customer(self, acct: str, p: dict) -> dict:
        r, rng = p["row"], self.rng
        account_id = f"acc_{acct[-6:]}"
        c = {
            "account_id": account_id, "tenant_id": "bank_demo",
            "name": f"{r['first']} {r['last']}",
            "email": f"{r['first'].lower()}.{r['last'].lower()}{acct[-2:]}@example.com",
            "city": r["city"], "state": r["state"], "country": "US",
            "lat": float(r["lat"]), "long": float(r["long"]),
            "opened_at": iso(DATA_START - timedelta(days=rng.randint(400, 2500))),
            "job": r["job"],
        }
        self.customers.append(c)
        for t in p["card"]:
            ts = datetime.fromisoformat(f"{t['trans_date']}T{t['trans_time']}+00:00")
            self.txns.append(self._txn(account_id, ts, "card", "debit", float(t["amt"]), t["merchant"].removeprefix("fraud_"),
                                       t["category"], "US", r["city"], float(t["merch_lat"]), float(t["merch_long"])))
        # home device and regular logins
        home = {"device_id": self.nid("dev"), "account_id": account_id, "model": rng.choice(PHONES),
                "first_seen": iso(DATA_START - timedelta(days=rng.randint(150, 700))),
                "country": "US", "city": r["city"]}
        self.devices.append(home)
        c["_home_device"] = home["device_id"]
        t = DATA_START
        while t < DATA_START + timedelta(days=90):
            t += timedelta(hours=rng.randint(18, 72), minutes=rng.randint(0, 59))
            self._auth(account_id, t, "login_success", home["device_id"], "US", r["city"], rng)
        # payroll, rent, utilities
        if rng.random() < 0.75:
            pay = round(rng.uniform(1400, 3600), 2)
            day = DATA_START + timedelta(days=rng.randint(0, 13))
            while day < DATA_START + timedelta(days=90):
                self.txns.append(self._txn(account_id, day.replace(hour=9), "ach_in", "credit", pay,
                                           f"PAYROLL {r['job'][:18].upper()}", "payroll", "US", r["city"]))
                day += timedelta(days=14)
            c["_payroll"] = pay
        c["_rent"] = round(rng.uniform(1100, 2400), -1)
        c["_landlord"] = self._bene(account_id, rng.choice(LANDLORDS), DATA_START - timedelta(days=rng.randint(200, 900)))
        util = self._bene(account_id, "City Power & Water", DATA_START - timedelta(days=rng.randint(300, 900)))
        for m in range(3):
            first = datetime(2026, 8 + m, 1, 8, tzinfo=timezone.utc)
            self.txns.append(self._txn(account_id, first, "ach_out", "debit", c["_rent"], c["_landlord"]["payee_name"],
                                       "rent", "US", r["city"], beneficiary_id=c["_landlord"]["beneficiary_id"]))
            self.txns.append(self._txn(account_id, first + timedelta(days=4), "ach_out", "debit",
                                       round(rng.uniform(70, 190), 2), "City Power & Water", "utilities", "US",
                                       r["city"], beneficiary_id=util["beneficiary_id"]))
        return c

    # ---------- row helpers ----------
    def _txn(self, account_id, ts, channel, direction, amount, payee, category, country, city,
             lat=None, long=None, beneficiary_id=None, device_id=None) -> dict:
        return {"txn_id": self.nid("txn"), "account_id": account_id, "ts": iso(ts), "channel": channel,
                "direction": direction, "amount": round(amount, 2), "counterparty": payee, "category": category,
                "country": country, "city": city, "lat": lat, "long": long,
                "beneficiary_id": beneficiary_id, "device_id": device_id}

    def _auth(self, account_id, ts, event, device_id, country, city, rng, foreign=False) -> dict:
        row = {"event_id": self.nid("auth"), "account_id": account_id, "ts": iso(ts), "event": event,
               "device_id": device_id, "ip": test_ip(rng, foreign), "country": country, "city": city}
        self.auth.append(row)
        return row

    def _bene(self, account_id, name, added_at, device_id=None) -> dict:
        b = {"beneficiary_id": self.nid("ben"), "account_id": account_id, "payee_name": name,
             "added_at": iso(added_at), "added_via_device": device_id}
        self.benes.append(b)
        return b

    def _transfer_median(self, account_id: str, before: datetime) -> float:
        amts = [t["amount"] for t in self.txns if t["account_id"] == account_id and t["channel"] in ("ach_out", "wire_out")
                and t["ts"] < iso(before)]
        return statistics.median(amts) if amts else 100.0

    # ---------- storylines ----------
    def ato(self, c: dict, case_id: str, alert: datetime, card_testing: bool, payee: str | None, amount: float | None):
        rng, acc = self.rng, c["account_id"]
        country, city = rng.choice(FOREIGN)
        t0 = alert - timedelta(hours=rng.randint(30, 60))
        dev = {"device_id": self.nid("dev"), "account_id": acc, "model": rng.choice(["Android (emulator)", "Windows Chrome", "Galaxy A14"]),
               "first_seen": iso(t0), "country": country, "city": city}
        self.devices.append(dev)
        self.tag("devices", dev["device_id"], case_id, "new_device_new_country")
        ev = self._auth(acc, t0, "login_success", dev["device_id"], country, city, rng, foreign=True)
        self.tag("auth_events", ev["event_id"], case_id, "new_device_new_country")
        t = t0 + timedelta(minutes=rng.randint(8, 40))
        for e in ("mfa_reset", "phone_number_changed"):
            ev = self._auth(acc, t, e, dev["device_id"], country, city, rng, foreign=True)
            self.tag("auth_events", ev["event_id"], case_id, "mfa_reset_after_new_device")
            t += timedelta(minutes=rng.randint(2, 15))
        if card_testing:
            for _ in range(3):
                t += timedelta(minutes=rng.randint(3, 15))
                tx = self._txn(acc, t, "card", "debit", rng.choice([1.0, 1.49, 1.99, 2.0]), "GIFTCARD ONLINE SVC",
                               "shopping_net", country, city, device_id=dev["device_id"])
                self.txns.append(tx)
                self.tag("transactions", tx["txn_id"], case_id, "card_testing_burst")
        t += timedelta(hours=rng.randint(2, 10))
        b = self._bene(acc, payee or rng.choice(ATO_PAYEES), t, dev["device_id"])
        self.tag("beneficiaries", b["beneficiary_id"], case_id, "new_beneficiary_then_large_transfer")
        median = self._transfer_median(acc, t)
        amt = amount or round(max(median * rng.uniform(5.5, 9), 2500) / 50) * 50
        tx = self._txn(acc, t + timedelta(minutes=rng.randint(10, 90)), "wire_out", "debit", amt, b["payee_name"],
                       "transfer", country, city, beneficiary_id=b["beneficiary_id"], device_id=dev["device_id"])
        self.txns.append(tx)
        self.tag("transactions", tx["txn_id"], case_id, "new_beneficiary_then_large_transfer")
        return {"trigger": f"wire_out {amt:.2f} to new payee from new device", "trigger_txn": tx["txn_id"]}

    def new_phone(self, c: dict, case_id: str, alert: datetime):
        rng, acc = self.rng, c["account_id"]
        t0 = alert - timedelta(days=rng.randint(3, 6))
        dev = {"device_id": self.nid("dev"), "account_id": acc, "model": rng.choice(PHONES),
               "first_seen": iso(t0), "country": "US", "city": c["city"]}
        self.devices.append(dev)
        self.tag("devices", dev["device_id"], case_id, "same_country_new_device")
        ev = self._auth(acc, t0, "login_success", dev["device_id"], "US", c["city"], rng)
        self.tag("auth_events", ev["event_id"], case_id, "same_country_new_device")
        payroll = [t for t in self.txns if t["account_id"] == acc and t["category"] == "payroll" and t["ts"] < iso(alert)]
        if payroll:  # the regular payroll already in the history is the mitigating evidence
            self.tag("transactions", payroll[-1]["txn_id"], case_id, "recurring_payroll_inflow")
        t = alert - timedelta(hours=rng.randint(2, 20))
        b = self._bene(acc, rng.choice([n for n in LANDLORDS if n != c["_landlord"]["payee_name"]]), t, dev["device_id"])
        self.tag("beneficiaries", b["beneficiary_id"], case_id, "payee_matches_prior_pattern")
        amt = round(c["_rent"] * rng.uniform(0.95, 1.08), -1)
        tx = self._txn(acc, t + timedelta(minutes=rng.randint(5, 30)), "ach_out", "debit", amt, b["payee_name"], "rent",
                       "US", c["city"], beneficiary_id=b["beneficiary_id"], device_id=dev["device_id"])
        self.txns.append(tx)
        self.tag("transactions", tx["txn_id"], case_id, "payee_matches_prior_pattern")
        return {"trigger": f"ach_out {amt:.2f} to new payee from new device", "trigger_txn": tx["txn_id"]}

    def travel(self, c: dict, case_id: str, alert: datetime):
        rng, acc = self.rng, c["account_id"]
        country, city = rng.choice(TRAVEL)
        t = alert - timedelta(days=rng.randint(2, 4))
        ev = self._auth(acc, t, "login_success", c["_home_device"], country, city, rng, foreign=True)
        self.tag("auth_events", ev["event_id"], case_id, "home_device_abroad")
        last = None
        for _ in range(rng.randint(4, 8)):
            t += timedelta(hours=rng.randint(2, 9))
            if t >= alert:
                break
            last = self._txn(acc, t, "card", "debit", round(rng.uniform(12, 260), 2), f"{city.upper()} MERCHANT {rng.randint(10, 99)}",
                             rng.choice(["food_dining", "travel", "shopping_pos", "entertainment"]), country, city)
            self.txns.append(last)
            self.tag("transactions", last["txn_id"], case_id, "home_device_abroad")
        return {"trigger": f"card activity in {country}", "trigger_txn": last["txn_id"] if last else None}


# (case_id, story, split, faults, kwargs). A-104 / A-105 are the brief's showcase pair.
PLAN = [
    ("A-104", "ato", "dev", ["wrong_identifier"], {"card_testing": True, "payee": "Velo Holdings", "amount": 4800.0}),
    ("A-105", "new_phone", "dev", [], {}),
    ("A-106", "ato", "dev", [], {"card_testing": False}),
    ("A-107", "travel", "dev", ["wrong_identifier"], {}),
    ("A-108", "ato", "dev", ["stale_records"], {"card_testing": True}),
    ("A-109", "new_phone", "dev", ["timezone_shift"], {}),
    ("A-110", "ato", "dev", ["interrupted_write"], {"card_testing": True}),
    ("A-111", "travel", "dev", [], {}),
    ("A-112", "new_phone", "dev", ["missing_device_evidence"], {}),
    ("A-113", "ato", "dev", ["timezone_shift"], {"card_testing": False}),
    ("A-114", "source_down", "dev", ["device_source_down"], {"under": "ato"}),
    ("A-115", "source_down", "dev", ["device_source_down"], {"under": "new_phone"}),
    ("A-201", "ato", "heldout", ["wrong_identifier"], {"card_testing": True}),
    ("A-202", "new_phone", "heldout", ["wrong_identifier"], {}),
    ("A-203", "ato", "heldout", [], {"card_testing": False}),
    ("A-204", "travel", "heldout", ["stale_records"], {}),
    ("A-205", "ato", "heldout", ["missing_device_evidence"], {"card_testing": True}),
    ("A-206", "new_phone", "heldout", [], {}),
    ("A-207", "ato", "heldout", ["interrupted_write"], {"card_testing": True}),
    ("A-208", "travel", "heldout", ["timezone_shift"], {}),
    ("A-209", "new_phone", "heldout", ["stale_records"], {}),
    ("A-210", "ato", "heldout", ["wrong_identifier", "timezone_shift"], {"card_testing": False}),
    ("A-211", "source_down", "heldout", ["device_source_down"], {"under": "ato"}),
    ("A-212", "source_down", "heldout", ["device_source_down"], {"under": "travel"}),
]
DISPOSITION = {"ato": "escalate", "new_phone": "close_benign", "travel": "close_benign", "source_down": "insufficient_evidence"}
# Where a recoverable fault bites first; the Attributor is scored by exact match on agent and step name.
FAULT_STEP = {"wrong_identifier": ("investigator", "get_device_history"),
              "missing_device_evidence": ("investigator", "get_device_history"),
              "stale_records": ("investigator", "get_transactions"),
              "timezone_shift": ("investigator", "get_auth_events"),
              "interrupted_write": ("gate", "commit_disposition"),
              "device_source_down": ("investigator", "get_device_history")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    b = Builder(args.seed)
    people = b.load_sparkov()
    if not people:
        raise SystemExit(f"no Sparkov output in {SPARKOV}; run third_party/sparkov first (see data/README.md)")
    customers = {acct: b.add_customer(acct, p) for acct, p in sorted(people.items())}

    # Rich histories host the storylines; the two sparsest also host source_down cases; leftovers are no-alert controls.
    by_activity = sorted(customers, key=lambda a: -len(people[a]["card"]))
    rich = [a for a in by_activity if len(people[a]["card"]) >= 60]
    sparse = [a for a in by_activity if a not in rich]
    rng = b.rng
    hosts_needed = sum(1 for p in PLAN if p[1] != "source_down")
    if len(rich) < hosts_needed:
        raise SystemExit(f"need {hosts_needed} customers with >=60 card txns, have {len(rich)}; generate more Sparkov customers")
    rng.shuffle(rich)
    pool_rich, pool_any = iter(rich), iter(sparse + rich[hosts_needed:])

    alerts, labels = [], []
    for case_id, story, split, faults, kw in PLAN:
        acct = next(pool_any) if story == "source_down" else next(pool_rich)
        c = customers[acct]
        alert_at = datetime(2026, 9, 15, tzinfo=timezone.utc) + timedelta(days=rng.randint(0, 29), hours=rng.randint(0, 23))
        under = kw.get("under", story)
        if under == "ato":
            info = b.ato(c, case_id, alert_at, kw.get("card_testing", rng.random() < 0.5), kw.get("payee"), kw.get("amount"))
        elif under == "new_phone":
            info = b.new_phone(c, case_id, alert_at)
        else:
            info = b.travel(c, case_id, alert_at)
        alerts.append({
            "alert_id": case_id, "tenant_id": c["tenant_id"], "created_at": iso(alert_at),
            "customer_name": c["name"], "account_hint": c["email"],  # alerts carry the email, not the account ID
            "summary": info["trigger"], "trigger_txn": info["trigger_txn"],
            "window": {"start": iso(alert_at - timedelta(days=WINDOW_DAYS)), "end": iso(alert_at)},
        })
        first_fault = next((f for f in faults if f in FAULT_STEP), None)
        labels.append({
            "alert_id": case_id, "split": split, "story": under, "disposition": DISPOSITION[story],
            "account_id": c["account_id"], "faults": faults,
            "faulty_agent": FAULT_STEP[first_fault][0] if first_fault else None,
            "faulty_step": FAULT_STEP[first_fault][1] if first_fault else None,
        })

    OUT.mkdir(parents=True, exist_ok=True)
    ORACLE.mkdir(parents=True, exist_ok=True)
    public_customers = [{k: v for k, v in c.items() if not k.startswith("_")} for c in b.customers]
    for name, rows in [("customers", public_customers), ("devices", b.devices), ("auth_events", b.auth),
                       ("beneficiaries", b.benes), ("transactions", b.txns)]:
        rows = sorted(rows, key=lambda r: (r.get("account_id", ""), r.get("ts") or r.get("first_seen") or r.get("added_at") or ""))
        with (OUT / f"{name}.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    (OUT / "alerts.json").write_text(json.dumps(alerts, indent=2))
    (ORACLE / "labels.json").write_text(json.dumps(labels, indent=2))
    with (ORACLE / "story_events.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["case_id", "table", "row_id", "step"])
        w.writeheader()
        w.writerows(b.story_events)

    counts = defaultdict(int)
    for l in labels:
        counts[(l["split"], l["disposition"])] += 1
    print(f"customers={len(b.customers)} txns={len(b.txns)} devices={len(b.devices)} auth={len(b.auth)} "
          f"beneficiaries={len(b.benes)} alerts={len(alerts)}")
    for k in sorted(counts):
        print(f"  {k[0]:8} {k[1]:22} {counts[k]}")


if __name__ == "__main__":
    main()
