"""Ground the ato_v1 constitution: fetch its primary sources through You.com and store them as memory.

Every You.com call lands in grounding_requests; every page lands in grounding_docs (Supabase, or
data/store/*.jsonl until SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are set).

Usage: python scripts/build_policy_corpus.py
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from casefile.youcom import YouCom  # noqa: E402

# Known primary-source pages (docs/DATA_SOURCES.md), read directly.
KNOWN_URLS = [
    "https://www.fincen.gov/resources/advisories/fincen-advisory-fin-2011-a016",
    "https://www.law.cornell.edu/cfr/text/16/part-681/appendix-A",
    "https://pages.nist.gov/800-63-4/sp800-63b/events/",
    "https://www.consumerfinance.gov/rules-policy/regulations/1005/11/",
]

# What each ato_v1 signal/check needs grounding for; searched only on trusted domains.
QUERIES = [
    ("new_device_new_country", "account takeover red flags changes to customer profile", ["fincen.gov"]),
    ("mfa_reset_after_new_device", "authenticator binding account recovery notification subscriber", ["pages.nist.gov"]),
    ("card_testing_burst", "card testing small authorization fraud", ["fincen.gov", "federalreserve.gov", "ftc.gov"]),
    ("new_beneficiary_then_large_transfer", "account takeover wire transfer new payee red flag", ["fincen.gov", "ffiec.gov"]),
    ("policy_rule_satisfied", "FFIEC authentication guidance high-risk transactions", ["ffiec.gov", "federalreserve.gov", "fdic.gov"]),
    ("escalation_narrative", "SAR narrative account takeover fraud cyber indicators", ["fincen.gov"]),
    ("deadline", "error resolution unauthorized electronic fund transfer 10 business days", ["consumerfinance.gov", "ecfr.gov"]),
]


def main() -> None:
    yc = YouCom()
    print(f"storing to {yc.store.backend}")
    seen: Counter = Counter()
    for i in range(0, len(KNOWN_URLS), 2):
        out = yc.contents(KNOWN_URLS[i:i + 2], purpose="policy_corpus")
        print(f"contents {KNOWN_URLS[i:i + 2]} -> http {out['request']['http_status']}, {len(out['docs'])} docs")
        seen.update(d["domain"] for d in out["docs"])
    for binds_to, q, domains in QUERIES:
        out = yc.search(q, include_domains=domains, count=3, purpose=f"policy_corpus:{binds_to}")
        print(f"search [{binds_to}] -> http {out['request']['http_status']}, {len(out['docs'])} docs: "
              + ", ".join(d["url"] for d in out["docs"]))
        seen.update(d["domain"] for d in out["docs"])
    print("docs by domain:", dict(seen))


if __name__ == "__main__":
    main()
