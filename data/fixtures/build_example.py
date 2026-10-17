"""Builds data/fixtures/example_procurement.json (documents with sha256) and the expected-verdict labels."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RETRIEVED = "2026-10-17T00:00:00+00:00"
DOCS = [
    ("d_reg", "https://registry.example.test/entities/NS-7788", "primary", "State Business Registry",
     "SYNTHETIC entity record: Northwind Signal Media LLC",
     "Entity: Northwind Signal Media LLC\nFile number: NS-7788\nDate of formation: 2025-02-03\nStatus: Active"),
    ("d_award", "https://awards.example.test/award/AW-001", "primary", "Federal Award Database",
     "SYNTHETIC award record AW-001",
     "Recipient: Northwind Signal Media LLC\nAward date: 2025-02-14\nAward amount: $143,000,000\n"
     "Extent competed: NOT COMPETED\nJustification: urgent need exception cited"),
    ("d_award2", "https://awards.example.test/award/AW-002", "primary", "Federal Award Database",
     "SYNTHETIC award record AW-002",
     "Recipient: Lakeshore Ads Inc.\nAward date: 2025-02-14\nAward amount: $77,000,000\nExtent competed: LIMITED COMPETITION"),
    ("d_sub", "https://awards.example.test/subaward/SA-001", "primary", "Federal Subaward Database",
     "SYNTHETIC subaward report SA-001",
     "Prime recipient: Northwind Signal Media LLC\nPrime award total: $143,000,000\n"
     "Subawardee: Harbor Strategy Group LLC\nSubaward total: $91,000,000"),
    ("d_rule", "https://rules.example.test/part6/urgency", "primary", "Acquisition Regulation (synthetic excerpt)",
     "SYNTHETIC rule excerpt: unusual and compelling urgency",
     "Unusual and compelling urgency. Full and open competition need not be provided when the agency's need for the "
     "supplies or services is of such an unusual and compelling urgency that the Government would be seriously injured "
     "unless the agency is permitted to limit the number of sources solicited."),
    ("d_n1", "https://outlet-one.example.test/story/1", "secondary", "Outlet One", "SYNTHETIC news report (Outlet One)",
     "Outlet One reports that Northwind Signal Media LLC was a newly formed company when it received the award."),
    ("d_n2", "https://outlet-two.example.test/story/9", "secondary", "Outlet Two", "SYNTHETIC news report (Outlet Two)",
     "Outlet Two reports that Harbor Strategy Group LLC received most of the subaward funds."),
]
docs = [dict(id=i, url=u, doc_type=t, publisher=p, title=ti, retrieved_at=RETRIEVED, text=tx,
             sha256=hashlib.sha256(tx.encode()).hexdigest()) for i, u, t, p, ti, tx in DOCS]
(ROOT / "data/fixtures/example_procurement.json").write_text(json.dumps(docs, indent=1))
# expected verdict per numbered statement in the case file (oracle data; agents never read this)
labels = {"1": "supported", "2": "supported", "3": "supported", "4": "contradicted",
          "5": "insufficient_evidence", "6": "out_of_scope", "7": "out_of_scope", "8": "supported"}
(ROOT / "labels_records/example_procurement.json").write_text(json.dumps(labels, indent=1))
print(len(docs), "documents,", len(labels), "labels")
