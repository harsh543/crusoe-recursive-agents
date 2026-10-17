# Demo data

All synthetic. No real customer data. IPs are RFC 5737 documentation ranges, and emails are `@example.com`.

| Path | What | Who may read it |
|---|---|---|
| `sparkov/` | Raw Sparkov output: 30 customers, 2026-07-18 → 2026-10-16, seed 42 (MIT, [namebrandon/Sparkov_Data_Generation](https://github.com/namebrandon/Sparkov_Data_Generation)) | generator only |
| `casefile/` | Mock source systems the tools query: `customers`, `devices`, `auth_events`, `beneficiaries`, `transactions`, plus `alerts.json` (24 alerts) | agents, via tools |
| `oracle/` | `labels.json` (disposition, split, injected faults, faulty agent/step) and `story_events.csv` (which rows each storyline injected) | eval harness only |

Case mix: 24 alerts, split 12 dev / 12 held-out. Each split has 5 escalate, 5 close_benign and 2 insufficient_evidence. A-104 (ATO, $4,800 to Velo Holdings) and A-105 (new phone, new landlord) are the showcase pair. Every alert gives the customer's **email**, not the account ID. That's what the wrong-identifier fault exploits.

Faults listed in `labels.json` are applied by the tool layer at run time. They are not baked into the CSVs.

## Regenerate

```bash
cd third_party/sparkov && python3.11 -m venv .venv && .venv/bin/pip install "Faker==13.12.0" numpy
```

```bash
cd third_party/sparkov && .venv/bin/python datagen.py -n 30 -seed 42 -o ../../data/sparkov 07-18-2026 10-16-2026
```

```bash
.venv/bin/python eval/gen_cases.py --seed 7
```

Sparkov pins `numpy==1.21.6`, which doesn't build on Python 3.14. Use Python 3.11 with a current numpy, as above.
