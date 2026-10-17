# Casefile — Data Sources and Investigation Constitution

Researched Oct 17, 2026. **Nothing has been downloaded yet.** Licenses marked "verify" weren't visible on the pages we fetched.

Two things this doc settles:
1. **Constitution:** the rules our Planner's `get_policy` returns and our Verifier enforces, grounded in public regulation and guidance.
2. **Dataset:** where demo transactions come from.

---

## Part 1: The constitution (policy sources)

### Sources and what each gives us

| Source | What we take from it | Becomes |
|---|---|---|
| **FinCEN Advisory FIN-2011-A016, Account Takeover Activity** ([page](https://www.fincen.gov/resources/advisories/fincen-advisory-fin-2011-a016), [PDF](https://www.fincen.gov/sites/default/files/shared/FIN-2011-A016.pdf)) | ATO red flags: profile/contact changes, sudden wires, ACH clustered across geographies, unusual ATM use, departure from normal activity. SAR narrative must say "account takeover fraud" and describe the activity | ATO red-flag vocabulary; the narrative template for escalations |
| **FinCEN Advisory FIN-2016-A005, Cyber-Events and Cyber-Enabled Crime** ([PDF](https://www.fincen.gov/sites/default/files/advisory/2016-10-25/Cyber%20Threats%20Advisory%20-%20FINAL%20508_2.pdf)) | Include cyber indicators (IP, device, timestamps) in reports | Escalation must cite device/IP evidence when the evidence is cyber-related |
| **FTC/Interagency Red Flags Rule, 16 CFR 681 App. A + Supplement A** ([Cornell LII](https://www.law.cornell.edu/cfr/text/16/part-681/appendix-A)) | 5 red-flag categories. Includes: a new card or device requested shortly after a contact change; departure from established patterns; dormant account reactivated; a customer notice of unauthorized charges. Risk-based responses range from "monitor" and "contact customer" to "no response needed" | Red-flag categories, plus the **benign path**: guidance explicitly allows "no response warranted" |
| **NIST SP 800-63B-4, authenticator events and recovery** ([events](https://pages.nist.gov/800-63-4/sp800-63b/events/)) | Binding a new authenticator or recovering an account is a security event that must notify the subscriber at its stored addresses | "MFA reset on a new device" is a high-weight signal; check whether a notification went to the *old* contact |
| **Regulation E, 12 CFR 1005.11** ([CFPB](https://www.consumerfinance.gov/rules-policy/regulations/1005/11/), [Fed Consumer Compliance Outlook 2025](https://www.consumercomplianceoutlook.org/articles/2025/third-issue-2025/error-resolution-procedures-under-the-electronic-fund-transfer-act-and-regulation-e)) | Unauthorized EFT claims: investigate within 10 business days, or 45 days with provisional credit; report within 3 business days | The case `deadline` and a `reg_e_clock` field (stretch). It also explains why closing cases fast *and* correctly matters |
| **FFIEC Authentication Guidance (Aug 2021)** ([summary, MoFo](https://mofo.com/resources/insights/210817-ffiec-issues-updated-guidance)) | Single-factor authentication is inadequate for high-risk transactions | Policy: a high-risk transfer after a step-up bypass or reset counts as a red flag |
| **Federal Reserve FraudClassifier / ScamClassifier** ([overview](https://fedpaymentsimprovement.org/?p=39306), [using both](https://fedpaymentsimprovement.org/wp-content/uploads/using-the-fraudclassifier-and-scamclassifier-models-together.pdf)) | Taxonomy built around three questions: who initiated the payment (authorized vs unauthorized), how it was executed, and what kind of fraud it was | `fraud_class` field on escalations, which gives the Investigator a controlled vocabulary instead of free text |

Note: all of these are for **grounding a synthetic demo**. Casefile doesn't file real SARs, and nothing changes money.

### Grounding through You.com (first run, Oct 17)

`scripts/build_policy_corpus.py` pulls these sources through You.com and stores every call and page (see PLAN.md §5). The first run stored 20 trusted docs:
- **FinCEN:** FIN-2011-A016 (page + PDF); FIN-2016-A003 (business email compromise); the cyber-event SAR FAQs.
- **Rules and standards:** 16 CFR 681 App. A; NIST 800-63B-4 events and authenticators; CFPB Reg E 1005.11.
- **FFIEC and Fed:** FFIEC 2021 authentication guidance plus Fed SR 21-14; the FFIEC BSA/AML manual appendix 7.
- **Federal Reserve paper on CardSim:** a Bayesian card-fraud simulator. A possible second data source.

Gaps to close:
- The eCFR pages came back nearly empty (436–803 chars, likely JS-rendered). Use the CFPB and Cornell copies instead.
- No primary source defines "card testing". That signal is grounded only in the FTC consumer page and Fed research, so treat it as our heuristic, not regulation.

### Draft constitution: `policy/ato_v1` (what `get_policy` returns)

```yaml
policy_id: ato_v1
immutable: true                # Version N+1 improver cannot edit this file
mandatory_checks:              # Planner can add checks, never remove these
  - correct_account
  - required_evidence_ok
  - window_covered
  - claims_supported
  - policy_rule_satisfied
  - result_persisted
required_sources: [devices, auth_events, transactions, beneficiaries]
window_days: 45

signals:                       # computed in CODE by compute_sequence_features
  new_device_new_country:   {weight: 3, source: devices,        ref: FIN-2011-A016 "profile changes"}
  mfa_reset_after_new_device: {weight: 3, source: auth_events,  ref: NIST 800-63B-4 events}
  card_testing_burst:       {weight: 2, source: transactions,   rule: ">=3 charges <= $2 within 60 min"}
  new_beneficiary_then_large_transfer: {weight: 3, source: beneficiaries+transactions, rule: "transfer to a payee added <24h earlier, amount >= 3x median of the account's ach_out/wire_out before the window"}
  geo_dispersed_ach:        {weight: 2, source: transactions,   ref: FIN-2011-A016}
  dormant_reactivation:     {weight: 1, source: transactions,   ref: 16 CFR 681 Supp. A}
mitigating:
  same_country_new_device:  {weight: -1}
  recurring_payroll_inflow: {weight: -1}
  payee_matches_prior_pattern: {weight: -1, rule: "every transfer to a new payee is 0.8x-1.25x that same median"}

disposition_rule:              # applied by the Verifier, not by a model
  escalate:              "all required_sources ok AND score >= 6"
  close_benign:          "all required_sources ok AND score <= 2 AND no signal with weight 3"
  insufficient_evidence: "any required_source not ok after budget, OR 2 < score < 6 with unresolved contradiction"
escalation_narrative:
  must_include: ["account takeover fraud", cited evidence ids, device/IP indicators, fraud_class]
```

Two properties judges should notice:
- **Error never means benign.** `close_benign` *requires* every source to be `ok`.
- **A-105 is closed by the same rule A-104 is escalated by.** It isn't a special case.

---

## Part 2: Transaction data

### What exists publicly

| Dataset | License | Size | Device / login / MFA? | Fit for Casefile |
|---|---|---|---|---|
| **Sparkov generator** ([GitHub namebrandon/Sparkov_Data_Generation](https://github.com/namebrandon/Sparkov_Data_Generation)) | MIT | You pick: `-n customers`, date range, `-seed` | No | **Best base.** Realistic per-customer card history (merchants, categories, lat/long, amounts) that we can generate small and reproducible |
| Sparkov prebuilt on Kaggle (kartik2112, via [FDB](https://github.com/amazon-science/fraud-dataset-benchmark)) | CC0 1.0 (per FDB) | ~1.3M train rows, 1,000 customers; ~100 MB CSV | No | Same data prebuilt. Needs a Kaggle login, and it's bigger than we need |
| **Synthetic Banking Transactions, Multi-Pattern Fraud Labels** ([Mendeley ktbthg777x v2](https://data.mendeley.com/datasets/ktbthg777x/2)) | CC BY 4.0 | 1M rows, CSV + Parquet | Unclear; columns not listed | Has an **ATO label** among 4 patterns. Worth one look at its columns; could be our held-out "realism" set |
| CreditTransAct ([Mendeley y64bbnm2s3](https://data.mendeley.com/datasets/y64bbnm2s3)) | verify | 33 features | Device, network and auth fields claimed, plus an ATO cluster | Promising for device signals; license and size unverified |
| Fraud e-commerce (Kaggle, via FDB) | not stated | ~150k rows | device_id, IP, browser, signup time | Has device/IP, but it's e-commerce rather than bank ATO |
| IEEE-CIS (Kaggle competition) | competition rules only | 590k rows | DeviceInfo, anonymized | License blocks redistribution. Skip |
| PaySim (Kaggle ealaxi/paysim1) | verify | 6.3M rows | No | Mobile money, no customer profile. Skip |
| IBM TabFormer ([GitHub](https://github.com/IBM/TabFormer)) | Apache-2.0 | 24M rows | No | Too big for the day. Skip |
| Feedzai BAF ([GitHub](https://github.com/feedzai/bank-account-fraud)) | CC BY-NC-ND 4.0 (secondary source) | 1M per variant | device_os, session fields | Account *opening* fraud, not takeover. Skip |
| ULB credit card (Kaggle) | DbCL | 285k rows | No, PCA features | Skip |

**Finding:** no public dataset has the full ATO sequence of device change → MFA reset → test charges → new beneficiary → transfer, joined per customer. The [arXiv 2606.25007](https://arxiv.org/pdf/2606.25007) multi-stream paper describes exactly that (ATO = device switch + P2P drain), but it doesn't say the data is released.

### Recommendation: a hybrid, which is honest and demo-ready

1. **Background behavior:** run Sparkov (MIT) for ~30 customers × 90 days, with a fixed seed. That gives each customer a believable spending history, so "departure from normal" is real.
2. **Overlay generator** (`eval/gen_cases.py`, ours): inject storylines into chosen customers.
   - **Escalate cases** (A-104-like) follow the FIN-2011-A016 / NIST pattern: new device in a new country → MFA reset → 3 × $1–2 charges → beneficiary add → large transfer. Vary amount, country, gap and order so the cases aren't a template.
   - **Benign lookalikes** (A-105-like): new phone in the same country → payroll in → first rent to a new payee (matches prior pattern).
   - **Insufficient-evidence cases:** a device source that's down for the whole budget.
   - Each injected event carries a hidden `story_id`. Labels go only to `oracle.labels`.
3. **Fault injection** stays in the tool layer (wrong identifier, stale records, timezone shift, interrupted write). It isn't in the data.
4. **Optional realism check:** if the Mendeley CC BY 4.0 set has usable ATO columns, sample ~6 of its ATO-labelled accounts as an extra held-out slice. That answers "did you only test on your own generator?"

Tables to seed (`devices`, `auth_events`, `transactions`, `beneficiaries`, `customers`) are mock source systems the tools query. They are separate from the Casefile tables in `0001_casefile.sql`.

### Downloads this needs (asking first)

| What | From | Size | Why |
|---|---|---|---|
| `Sparkov_Data_Generation` repo (git clone) | github.com/namebrandon | small (code + profile JSON) | Generate background transactions locally; run in its own directory |
| Mendeley ktbthg777x v2 (optional) | data.mendeley.com | unknown; 1M rows, likely 100 MB+ | Realism held-out slice |

---

## Precedents found while researching (add to the brief's "precedents to beat")

- **OpenAI Cookbook, "Evidence-grounded AML agent with Bedrock"** ([link](https://developers.openai.com/cookbook/examples/partners/aws/evidence_grounded_aml_agent_with_bedrock)). The model proposes and application code verifies the claims and controls workflow state. This is **very close to our pattern**. Our difference: frozen contracts, failure attribution, measured false-completion vs a critic baseline, and fault recovery.
- **Sentinel** ([GitHub CodeWithLuka/sentinel](https://github.com/CodeWithLuka/sentinel)): an L1 fraud investigation agent with a case file and a close/escalate/SAR recommendation.
- **Co-Investigator AI** ([arXiv 2509.08380](https://arxiv.org/pdf/2509.08380)): multi-agent SAR drafting with a compliance validator.
- **FAA Framework** ([arXiv 2506.11635](https://arxiv.org/pdf/2506.11635)): an LLM credit-card fraud investigation framework that uses Sparkov.

None of these claim measured false-completion under injected tool faults. That's still our gap to own.
