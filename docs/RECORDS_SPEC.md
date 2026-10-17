# Casefile Records mode: spec (uploaded case file, public-records claim verification)

Status: v0.1, Oct 17 2026. Approved plan: `~/.claude/plans/serene-bubbling-bentley.md`. Domain pack under `src/casefile/records/`.

## What it does
Takes an uploaded case file (text of allegations/assertions about a public matter), splits it into atomic **attributed claims**, and verifies each claim against cached documents. It never decides whether anyone committed wrongdoing.

## Verdicts (per claim)
`supported` | `contradicted` | `insufficient_evidence` | `collection_failed` | `out_of_scope`.
- Closure verdicts (`supported`, `contradicted`) require a passing verification before the Gate writes them.
- `out_of_scope`: legal conclusions (fraud, corruption, intent, guilt) and claims about private individuals. These are never researched; the report states "attributed, not verified".

## Verification checks (all in code)
| Check | Rule |
| --- | --- |
| scope_respected | legal-conclusion or private-individual claims must be `out_of_scope` with no findings; in-scope claims must not be `out_of_scope` |
| quotes_verbatim | every finding quote appears verbatim (whitespace/case-normalized) in the cited document; supported/contradicted need >= 1 finding |
| source_adequate | >= 1 primary document, or findings from >= 2 distinct publishers among secondary sources |
| entity_match | the claim's canonical entity name appears in each cited document; a look-alike name (similar but different) fails |
| computation_correct | code recomputes date gaps, totals, competition status from the findings; the verdict must equal the computed one; missing inputs force `insufficient_evidence` |
| conflicts_addressed | two documents giving different values for the same field must be listed in `result.conflicts` |
| neutral_language | no wrongdoing vocabulary outside double-quoted text; every claim has an attribution |

## Pseudonymization
Processing uses raw text (verbatim quotes must match). Presentation is pseudonymized by default (names mapped to aliases, including inside quotes); a reveal toggle shows originals. A leak check must find zero real names in default output.

## Report
Per-claim table (claim, attributed to, verdict, quote, document, retrieval date), a "what the record does and does not establish" section, the other side's stated position as its own claim, and the line "Not a legal finding."

## Retrieval
`EvidenceSource` exposes `search` and cache-only `fetch`. `FixtureSource` keeps benchmark runs
offline and reproducible. `YouComSource` is the live path:

1. You.com Search discovers candidate source URLs without supplying evidence text to the agent.
2. Code rejects search/result wrappers (for example `google.com/search?q=...`) and non-HTTP URLs.
3. You.com Contents extracts only the exact direct URLs returned by Search or explicitly included
   in the uploaded case file. Contents requests are capped at 10 URLs.
4. Only successfully extracted documents enter the investigator's cache. `fetch` never performs a
   network call, so an invented model URL or document id cannot become a scrape target.
5. No result means `insufficient_evidence`; a Search/Contents transport error with no collected
   document means `collection_failed`. The run writes a retrieval audit with accepted URLs,
   rejected URLs, queries, and errors.

Documents carry the exact URL, type, publisher/domain, retrieval time and sha256 (integrity
enforced on construction). Search and Contents are retrieval-only; all agent reasoning remains on
Crusoe. You.com Research is not used at run time because it performs external model synthesis.
