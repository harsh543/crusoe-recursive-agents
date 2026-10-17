"""Verify the hash-chained audit trail of a case or every case in a run: python scripts/audit_verify.py --case <uuid> | --run <uuid>
Exit 0 if every chain is intact, 1 otherwise."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from casefile.persist import verify_audit_chain  # noqa: E402
from casefile.store import Store  # noqa: E402

ap = argparse.ArgumentParser()
g = ap.add_mutually_exclusive_group(required=True)
g.add_argument("--case")
g.add_argument("--run")
a = ap.parse_args()
store = Store()
cases = [a.case] if a.case else [c["id"] for c in store.select("cases", run_id=a.run)]
bad = 0
for c in cases:
    ok, seq = verify_audit_chain(store, c)
    bad += not ok
    print(f"{c} {'OK' if ok else f'TAMPERED at seq {seq}'}")
print(f"{len(cases) - bad}/{len(cases)} chains intact")
sys.exit(1 if bad else 0)
