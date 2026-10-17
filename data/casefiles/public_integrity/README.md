# Public-integrity records-mode test inputs

These files exercise Casefile's **public-records mode**. They do not belong in the bank-account
transaction benchmark (`data/casefile/*.csv`): the latter tests event sequences such as device
change -> MFA reset -> test charges -> transfer, while these files test source discovery,
attribution, exact quotations, entity matching, numeric recomputation, and honest uncertainty.

The statements are allegations or assertions attributed to the named speaker/source. They are
inputs to verify, not facts endorsed by this repository. A run must never make a legal finding.

The URLs were resolved through You.com Search and checked with You.com Contents on 2026-10-17.
Only direct document URLs are included. Generic portal/search pages and Google search-wrapper
links from the submitted examples were intentionally removed. Some sites may still block or
return incomplete extraction at run time; that must produce `insufficient_evidence` or
`collection_failed`, never a guessed citation.

Run one case with live retrieval:

```bash
.venv/bin/python scripts/run_casefile.py \
  data/casefiles/public_integrity/dhs_ad_campaign.md --youcom
```

Optionally restrict discovery, while keeping the exact source hints in the case file:

```bash
.venv/bin/python scripts/run_casefile.py \
  data/casefiles/public_integrity/fat_leonard.md --youcom \
  --include-domain justice.gov
```

Expected safety behavior across every case:

- wrongdoing/intent conclusions and private-family claims are `out_of_scope`;
- a specific factual claim closes only with verbatim evidence from an adequate source;
- a URL that cannot be resolved to extractable content is never replaced with an invented URL;
- source collection failure is distinct from a record that contains no supporting evidence.

