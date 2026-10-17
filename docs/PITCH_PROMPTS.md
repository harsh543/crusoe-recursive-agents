# Casefile: Gamma and Canva prompts

Drafted Oct 17 2026. Use only facts from the project; numbers marked [INSERT] are pending and must come from `runs/*/results.json`.

## Gamma prompt (paste as is)

```
Create a 13-slide pitch deck titled "Casefile: an agent that can't say 'done' until code proves it".
Audience: hackathon judges and enterprise engineers. Tone: precise, honest, no hype.
Style: dark navy background, teal and white accents, clean diagrams, large numbers, minimal text, no stock photos of people.
Do not name or depict any real person or company; all case data is synthetic or pseudonymized.

1. Title: "Casefile". Subtitle: "Done means done. Built on Crusoe Managed Inference with NVIDIA Nemotron." Hackathon: Crusoe x Cerebral Valley Recursive Agents, Oct 17 2026.
2. The problem, false completion: a lookup fails, the agent reads "no data" as "nothing suspicious", writes a fluent "benign" memo, and an LLM critic approves it. Example: an email was passed where an account ID was needed.
3. The idea: the agent writes its own definition of done, but code checks it. A frozen contract, a code verifier, a Gate that is the only writer, a loop guard, and a failure Attributor that re-plans only the broken step.
4. How a case flows (diagram): intake, governance gate, required-field check, planner, investigator, code verifier, attributor and targeted re-plan, commit, analyst review queue. Mark which steps are models and which are plain code.
5. Why Crusoe: the cheapest Nemotron per role. Lightning (30B-A3B) investigates and attributes; Super VL plans and handles intake. Show the live prices per 1M tokens read from Crusoe's /v1/models. Mention that turning thinking off cut output from 310 to 19 tokens and latency from 2.9s to 0.4s on Lightning.
6. Enterprise harness inspired by a PayPal talk (cite it as a summary, not verified): one model router with allowlist, per-role access, per-case budget, PII masking both ways; tool registry; certified agent registry; typed state with checkpoints; hash-chained audit log; analyst review queue; no automatic money movement.
7. Case-file mode: upload a case file, split it into attributed claims, verify each against cited records with verbatim quotes and code-recomputed dates and amounts. Outputs are pseudonymized, never conclude wrongdoing, and include "Not a legal finding".
8. PR gate as an MCP server: PCI exposure, data classification, API-contract changes, regulatory surface. Read-only tools, capped inputs, card numbers never echoed, decisions audited. Regulatory research uses You.com Search followed by exact-URL extraction; Finance is limited to verified issuer and financial enrichment.
9. Measured results, dev split, 10 injected-fault cases, one run each, after adding schemas and the router. Casefile: 100% correct disposition, 0% false completion (0 of 6 claimed completions), 100% recovery from fixable faults, cost per correct case $0.0005. Single agent: 60% correct, 33% false completion (2 of 6). Agent plus LLM critic: 70% correct, 20% false completion (1 of 5), 75% recovery. Failure attribution exact match: 63% (5 of 8), up from 29%. Casefile is slower: p50 25s vs 12s for the single agent, p95 63s. Footnote on the slide: "dev numbers are optimistic; prompts were tuned after the first dev run; the held-out split has not been run". [INSERT held-out numbers only after the single held-out run]
10. Honesty slide, what went wrong and what we fixed: a verifier bug rejected correct answers; the first result was a lucky 8 of 8; after the fix, 24 of 24 across repeated runs with company names swapped showed no name bias. Failure attribution is still weak at 29%.
11. The build team: a human lead plus three AI tools. Claude Code wrote the code, tests (286 offline, 12 live) and benchmarks. Claude Desktop [CONFIRM: project brief and research summaries]. Codex [CONFIRM: You.com retrieval adapter and storage]. The human set direction and made every key decision.
12. Limits and next steps: held-out run, model sweep, wire memory rules into agents, preserve cited finance records after the now-verified You.com MCP preflight, Version N+1 playbook loop.
13. Closing line: "An agent that can't prove it's done doesn't get to say it's done."
```

## Canva prompts

1. **Logo mark:** "Minimal logo for 'Casefile': a folder icon with a checkmark formed by a circuit line, navy and teal, flat vector, readable at 32px."
2. **Title hero:** "Abstract dark navy background, a glowing teal checklist with one item locked by a padlock, subtle grid, no people, 16:9."
3. **Architecture infographic:** "Horizontal flow diagram, 9 rounded boxes in a row. Models in teal, plain code in white, human analyst in amber. Label the steps: Intake, Governance gate, Required fields, Planner, Investigator, Verifier, Attributor, Commit, Analyst."
4. **Before and after:** "Two-panel comparison. Left: a fluent 'benign' memo stamped APPROVED by a critic over an error icon. Right: the same memo blocked by a red gate labeled 'device evidence: error'. Clean, flat, high contrast."
5. **Results graphic:** "Bar chart, three bars: Single agent, Agent plus critic, Casefile. Large numbers, teal for Casefile, grey for the others. Footnote: dev split, 10 cases." Use your own final numbers.
6. **Social card:** "1200x630 card with the closing line in large type on navy, small logo bottom-left."

## Before you publish
- **Pending numbers:** slide 9 now has the dev rerun (`runs/dev-20261017-143607/results.json`); the held-out run has not been done, so keep that placeholder.
- **Claude Desktop and Codex lines (slide 11):** written from what was visible in the repo. Codex added the You.com retrieval adapter; the brief edits appear to come from Claude Desktop. Neither was verified, so correct those two lines.
- **PayPal talk points:** they come from summaries the project owner pasted, not from the video. Keep the "summary, not verified" wording.
- **Tone check:** read slide 7 and any case-file example before presenting, since the topic involves public figures.
