# casefile-gate: an MCP server for the pull-request gate

Maps the four checks on the PayPal "pull request gate" slide to tools, with guardrails. Regulatory research uses You.com Search followed by
exact-URL Contents extraction through the **host**. The finance tool is used only for verified issuer, SEC-filing, market-data, or nonprofit-finance
enrichment; this server never holds You.com credentials.

| Slide check | Tool(s) | How it works |
| --- | --- | --- |
| PCI exposure | `check_pci_exposure` | Luhn-checked card numbers (critical, blocking; masked in output), CVV/CVC and track data (critical), known test cards (low), card fields and card data in logs (high). In a unified diff only added lines count |
| Data classification | `classify_data_fields` | pii / payment / credential / internal / unclassified, from names or a JSON schema; unclassified fields need review |
| API-contract changes | `check_api_contract`, `check_tool_permissions` | Breaking vs non-breaking schema changes; removed tools, access-class changes and widened roles (permission expansion blocks unless a named approver is given) |
| Regulatory surface | `check_regulatory_surface`, `record_regulatory_evidence` | Keyword/path mapping to topics (card data, money movement, AML reporting, account actions, credit decisioning, personal data, automated decisions) with research queries; evidence must be https, an official domain, a 20-1000 character quote, and free of "we are compliant" language |
| The gate itself | `gate_decide` | pass / needs_review / block from code rules; appends a hash-chained audit event with counts only (no diff, no card data) |

Also published: resource `gate://policy` and prompt `pr_gate_review`, which tells the host to discover an official URL with `you-search`, extract
that exact URL, record only official-source evidence, and never override a block.

## Guardrails
Read-only tools (annotations `readOnlyHint`; only `gate_decide` writes, and only to the audit log) | no network access in this server | inputs capped
(200k characters, 500 items) | a card number is never echoed in full | evidence domain allowlist (`.gov`, `.europa.eu`, PCI SSC, NACHA, Cornell LII)
| no legal-conclusion statements accepted | decisions come from code, not a model | every decision audited | `security_approved_by` is recorded with the decision.

## Use
- MCP: `.mcp.json` defines both servers (`casefile-gate` over stdio and a You.com remote endpoint). Codex is configured separately with the
  combined `you-search,you-finance` endpoint and the local header helper documented in `README.md`.
- CI: `git diff main | .venv/bin/python scripts/pr_gate.py --change-id PR-12 --summary "..."` (exit 0 pass, 1 needs_review, 2 block).
- Tests: `.venv/bin/python -m pytest tests/gate_mcp -q` (37 tests, including an in-memory MCP client and the guardrails above).

## You.com connection status
On 17 October 2026, the Codex connection was verified against
`https://api.you.com/mcp?tools=you-search,you-finance`: initialization, tool discovery, and a live `you-finance` call all succeeded using the
gitignored `YDC_API_KEY` through `scripts/youcom_mcp_headers.py`. The key is not stored in Codex configuration or this server.

Other MCP clients may use `.mcp.json` and their own secret store or OAuth flow. Never commit an Authorization header.

## Limits, stated plainly
- A live finance applicability preflight was run, but its synthesis is lead material until each cited filing, Form 990, audit, or primary record is
  opened and preserved. An absent finance match does not prove that an entity is private.
- The regulatory mapping is a keyword heuristic for routing research, not legal analysis. The gate cannot fetch pages, so accepted quotes are marked `verified_by_gate: false`.
- `security_approved_by` is a recorded attestation, not a signed approval.
