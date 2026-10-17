# Public-integrity finance enrichment

Status: live You.com MCP preflight run on 17 October 2026 at approximately 21:49 UTC.

This is an **applicability and routing report**, not a finding about any person or organization. The live call used the configured
`you-finance` tool at `https://api.you.com/mcp?tools=you-search,you-finance`. It asked for exact-entity issuer matching, SEC identifiers only when
verified, nonprofit financial sources, and a separation between finance evidence and other public records.

## Result

The finance MCP did not verify a ticker, CIK, or SEC-reporting match for Glenn Defense Marine Asia, MZM Inc., ADCS Inc., Navatek/Martin Defense
Group, Safe America Media LLC, or The Strategy Group Company. That absence is **not proof that an entity is privately held**. It means only that
issuer-level finance data is not eligible for these case files until an exact legal-entity match is independently verified.

The useful finance slice is the two Mississippi nonprofits: You.com located Form 990-derived records and audit leads. The underlying filed return
or signed audit must be opened and preserved before a line item is treated as case evidence.

| Entity | Finance applicability | Retain from the preflight | Correct primary route |
| --- | --- | --- | --- |
| Glenn Defense Marine Asia Pte. Ltd. | No verified issuer match | No issuer metric retained | [DOJ case record](https://www.justice.gov/criminal/criminal-fraud/case/united-states-v-glenn-defense-marine-asia-pte-ltd), court docket, Singapore registry |
| MZM Inc. | No verified issuer match | The $1 million FEC settlement is campaign-finance evidence, not issuer finance | [FEC enforcement release](https://www.fec.gov/updates/mitchell-wade-and-mzm-inc-agree-to-pay-1000000-civil-penalty-for-illegal-contribution-reimbursement-scheme/), procurement records, DOJ/court records |
| ADCS Inc. | No verified issuer match | No finance fact retained; the returned identity leads were not adequate issuer evidence | Procurement records, corporate registry, DOJ/court records |
| Mississippi Community Education Center | Nonprofit finance lead | EIN 58-2046994; an IRS-derived filing for the period ended June 2018 reports $26.875m revenue, $19.410m expenses, $16.618m assets, $7.158m liabilities, and $9.460m net assets | [Form 990 index](https://projects.propublica.org/nonprofits/organizations/582046994), [full filing](https://projects.propublica.org/nonprofits/organizations/582046994/201931359349309988/full), [IRS search](https://apps.irs.gov/app/eos), state auditor/grant records |
| Family Resource Center of North Mississippi Inc. | Nonprofit finance lead | EIN 64-0895266; Form 990 and audit records were located, but line items remain lead-only until the filings are preserved | [Form 990 index](https://projects.propublica.org/nonprofits/organizations/640895266), [full filing](https://projects.propublica.org/nonprofits/organizations/640895266/201840649349300444/full), [IRS search](https://apps.irs.gov/app/eos), state auditor/grant records |
| Navatek / Martin Defense Group | No verified issuer match | No issuer metric retained; contract amounts belong to procurement evidence | [PacMar Technologies](https://www.pacmartech.com/), USAspending/SAM.gov, agency award files, corporate registry |
| Safe America Media LLC | No verified issuer match | No issuer metric retained | [USAspending award](https://www.usaspending.gov/award/CONT_AWD_70RDA225FR0000009_7001_70RDA225D00000004_7001), award file, [Senate inquiry letter](https://www.welch.senate.gov/wp-content/uploads/2026/03/Letter-to-Safe-America-Media.pdf) |
| The Strategy Group Company | No verified issuer match | Do not attach Strategy Inc.'s CIK 0001050446 or filings; it is a different named entity | Campaign-finance filings, subcontract records, [local business-directory identity lead](https://business.delawareareachamber.com/list/member/the-strategy-group-company-2207) |

## Enforced routing policy

The executable router is `src/casefile/records/evidence_routing.py`.

| Question | You.com route | What may count as evidence |
| --- | --- | --- |
| Does this exact legal entity map to an issuer? | `you-finance` | Lead only until the ticker/CIK is confirmed against [SEC EDGAR](https://www.sec.gov/edgar/search/) or the relevant securities regulator |
| What do a verified issuer's filings or market data show? | `you-finance` with the verified ticker/CIK | Cited filing/market source with period and as-of date |
| What do a nonprofit's finances show? | `you-finance` | Lead only until the underlying Form 990 or signed audit is preserved |
| What contract, grant, contribution, registration, case, or rule applies? | `you-search`, then `you-contents` on the actual URL | The underlying official record; never a search wrapper or finance synthesis |

The verifier must fail closed when issuer identity is unverified, a finance result supplies no underlying URL, the period is missing, or a name-only
match could be a lookalike. Finance signals provide context; they cannot establish procurement competition, grant diversion, a relationship,
wrongdoing, or legal compliance.

