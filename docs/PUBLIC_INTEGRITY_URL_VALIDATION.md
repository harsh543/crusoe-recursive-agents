# Public-integrity source URL validation

Validation date: 2026-10-17

These results distinguish URL identity from evidentiary relevance. `Extracted` means You.com
Contents returned usable text from that exact URL. A valid page is not included in a case unless
its contents are relevant to a claim.

| Case | Exact URL | Result |
|---|---|---|
| Fat Leonard | https://www.justice.gov/usao-sdca/pr/leonard-glenn-francis-sentenced-15-years-prison-massive-bribery-fraud-and | Extracted (7,320 characters) |
| Fat Leonard | https://www.justice.gov/usao-sdca/pr/malaysian-defense-contractor-leonard-francis-pleads-guilty-corruption-conspiracy | Extracted (11,332 characters) |
| Fat Leonard | https://www.justice.gov/usao-sdca/pr/us-navy-admiral-sentenced-lying-feds-about-his-relationship-foreign-defense-contractor | Extracted (13,114 characters) |
| Duke Cunningham | https://www.justice.gov/archive/tax/usaopress/2006/txdv06cas60303.1.pdf | Extracted (5,776 characters) |
| Duke Cunningham candidate | https://oig.justice.gov/sites/default/files/legacy/special/s0809a/final.pdf | **Rejected as evidence.** This is *An Investigation into the Removal of Nine U.S. Attorneys in 2006*. It mentions Cunningham only as background to the Carol Lam removal question and does not substantiate the Cunningham case-file claims. You.com Contents also returned no text. |
| Mississippi TANF | https://www.osa.ms.gov/news/auditor-demands-repayment-misspent-welfare-money | Extracted (4,787 characters) |
| Mississippi TANF | https://www.osa.ms.gov/news/state-auditor-shad-white-testifies-us-house-ways-means-committee-welfare-case | Extracted (3,004 characters) |
| Martin Kao / Navatek | https://www.propublica.org/article/fbi-susan-collins-navatek-campaign-donations-investigation | Extracted (47,978 characters) |
| Martin Kao / Navatek | https://www.propublica.org/article/debunking-susan-collins-fbi-navatek-investigation-claims | Extracted (13,439 characters) |

## Live Casefile runs

| Case | Report | Retrieval audit | Result summary |
|---|---|---|---|
| Fat Leonard | `runs/casefile-20261017-143419/report.md` | `runs/casefile-20261017-143419/retrieval_audit.json` | 1 supported, 2 insufficient evidence, 1 out of scope |
| Duke Cunningham | `runs/casefile-20261017-144057/report.md` | `runs/casefile-20261017-144057/retrieval_audit.json` | 4 insufficient evidence, 1 out of scope; unrelated OIG URL absent from the clean audit |
| Mississippi TANF | `runs/casefile-20261017-143530/report.md` | `runs/casefile-20261017-143530/retrieval_audit.json` | 4 insufficient evidence, 1 out of scope |
| Martin Kao / Navatek | `runs/casefile-20261017-143605/report.md` | `runs/casefile-20261017-143605/retrieval_audit.json` | 1 contradicted, 2 insufficient evidence, 1 out of scope |

Every audit recorded zero rejected wrapper URLs. The case inputs contain direct source URLs rather
than Google or other search-result wrapper links. Verdicts remain conservative when a source does
not contain enough exact, quotable evidence.
