# Guidance notes: Plaid Effects 2026 talk (use while building only)

Source: a summary of the session "The models behind intelligent finance" that the user pasted on Oct 17, 2026. We have not watched the talk or verified its figures. This file is **guidance for design choices, not a requirement and not evidence**. None of its numbers may appear in our UI, README or pitch as if they were ours.

## Ideas worth borrowing (and where they land)
| Idea in the talk | How we use it | Where |
| --- | --- | --- |
| A single transaction does not show behavioral state; patterns emerge across a time horizon | Features are computed over the whole ordered sequence, not per event | `features.py` |
| Averaging transaction embeddings loses order, intervals and cadence | Keep order and timing explicit: ordered events, gaps between events, day-of-week and day-of-month as features. A-104's signal is the *order* (new device, then MFA reset, then test charges, then new beneficiary, then transfer) and the minutes between steps | `features.py`, `Features` |
| Foundation models run alongside deterministic rules and feed them features; they do not replace them | Same split as ours: models plan and read, code decides. Reinforces the code-first Verifier and Gate | DESIGN section 1, 5.2 |
| Messy descriptors need canonicalization before reasoning | Add a small deterministic `normalize_descriptor()` in `tools.py` so beneficiaries and merchants compare equal across variants. Keep it rule-based; no model needed | `tools.py` |
| Replaced Token Detection: splice events from other profiles into a timeline and detect what looks unnatural | Test and benchmark idea only: build dev cases by splicing foreign events into A-104/A-105 timelines to produce the "contradictory timestamps" and wrong-account cases, and check the Verifier's `correct_account` and `contradictions_addressed` catch them | `bench/cases.py`, `test_features_policy.py` |
| Gains reported without increasing false-positive declines | Matches our unnecessary-escalation-rate metric: never report detection gain without the false-positive side | SPEC section 6 |
| Hard negatives separate look-alike operations (recurring payroll vs one-off transfer) | A-105 is our hard negative for A-104. Add more lookalikes to the dev set (new phone same country plus a new payee; travel with a new device but no MFA reset) | `bench/cases.py` |

## What we are NOT doing
- No trained foundation model, contrastive training or sequence transformer today. The Crusoe catalog we were given has no embedding model (SPEC non-goals).
- No claim that Casefile improves fraud detection by any percentage. Our benchmark measures false completion, recovery and cost per correct case on synthetic cases.
- No quoting of the talk's reported figures as support for our approach.

## Cheap follow-ups if time remains
1. Add `gap_minutes` between consecutive risky events and `day_of_week` to `Features`; add a test that reordering A-104's events (transfer before MFA reset) changes the policy outcome.
2. Add `normalize_descriptor()` with 3-4 variants of "Velo Holdings" and a test that they compare equal.
3. Add 2 more hard-negative lookalikes to the dev split.
