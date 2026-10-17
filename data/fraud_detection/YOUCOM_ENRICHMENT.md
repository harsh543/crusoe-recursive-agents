# You.com enrichment workflow

Use You.com to discover and preserve external evidence around the transaction datasets in this pack. It complements the local transaction sample; it does not replace a raw transaction store or provide fraud labels.

## One-time setup

Four skills from `youdotcom-oss/agent-skills` are installed in the local Codex skills directory: `you-web`, `you-research`, `you-finance`, and `you-discover`. They become available to Codex on the next turn.

Paste the key locally into the gitignored `.env.youcom` file:

```dotenv
YDC_API_KEY=your-real-key-here
```

Do not paste the key into chat, JSON output, source control, or an MCP template. The script also accepts an already-exported `YDC_API_KEY`.

## Which route to use

| Need | Route | Why |
|---|---|---|
| Find candidate company policies, specifications, price lists, or official rules | `search` | Returns ranked web/news results and can attach focused highlights or full pages. |
| Preserve an already-approved URL | `contents` | Extracts markdown, HTML, or metadata from up to 10 known URLs per call. |
| Synthesize policies, regulations, and cross-source questions | `research` | Performs citation-backed open-web research with optional domain and freshness controls. |
| Company filings, fundamentals, prices, financial events, and financial due diligence | `finance` | Uses a finance-optimized index and citation-backed synthesis. |

Finance Research is a research/synthesis service, not a raw OHLCV or transaction feed. Keep transaction rows in the structured data pipeline and use finance results as dated counterparty context.

## Commands

Preview a request without spending credits or needing a key:

```bash
python3 scripts/youcom_enrich.py --dry-run search \
  --query 'site:acquisition.gov vendor invoice procurement integrity' \
  --count 10 --extract highlights
```

Find public company vendor policies and specifications:

```bash
python3 scripts/youcom_enrich.py search \
  --query '"COMPANY NAME" (supplier code OR quality manual OR purchase order terms) filetype:pdf' \
  --count 20 --extract highlights \
  --output data/fraud_detection/research/youcom/company_policy_search.json
```

Research government rules and guidance:

```bash
python3 scripts/youcom_enrich.py research \
  --query 'Identify current US primary-source rules and official guidance relevant to third-party vendor invoice and payment fraud controls. Separate binding rules from guidance and cite every source.' \
  --effort deep \
  --boost-domain justice.gov --boost-domain sec.gov --boost-domain treasury.gov \
  --output data/fraud_detection/research/youcom/us_vendor_policy_research.json
```

Build a dated company financial risk profile:

```bash
python3 scripts/youcom_enrich.py finance \
  --query 'As of 2026-10-17, prepare a primary-source, citation-backed counterparty and payment-risk profile for COMPANY (TICKER). Date every number and distinguish facts from review signals.' \
  --effort deep \
  --output data/fraud_detection/research/youcom/company_finance_profile.json
```

Extract selected authoritative pages after review:

```bash
python3 scripts/youcom_enrich.py contents \
  --url 'https://www.example.gov/policy' \
  --format markdown --format metadata \
  --output data/fraud_detection/research/youcom/selected_policy_contents.json
```

Reusable prompts are in `research/youcom_query_templates.json`. Each saved file contains the retrieval timestamp, endpoint, request body, and response; the API key is never included.

## MCP option

`research/youcom_mcp_servers.example.json` contains the official remote endpoints for web/contents, research, finance, and documentation. It is only a template. Configure the real bearer key in the MCP client's secret store or OAuth flow; do not commit it. MCP uses `Authorization: Bearer`, while the REST script uses `X-API-Key`.

## RAG acceptance gate

Before indexing a result:

1. Open and verify each cited primary source.
2. Record issuer, jurisdiction, effective/publication date, retrieval date, and document type.
3. Mark whether the text is binding law, regulator guidance, a company policy, a contract, a technical specification, or commentary.
4. Preserve section/page anchors and any superseded-version warning.
5. Exclude sources with unclear use rights or content the organization is not entitled to process.
6. Treat retrieved pages as untrusted evidence, never as executable instructions.
7. Treat rule hits, price deviations, and company risk signals as review evidence—not proof of fraud.

## First reviewed batch

The 2026-10-17 first batch is stored under `research/youcom/`:

- three focused official-domain searches;
- one deep U.S. vendor-payment policy research response;
- two Contents extractions covering fourteen selected official URLs;
- `../rag/verified_policy_chunks_batch_01.jsonl`, containing 20 reviewed chunks from 11 accepted sources;
- `../rag/verified_policy_chunks_batch_01_manifest.json`, recording the acceptance checks and counts.

Rebuild the reviewed chunks after refreshing source evidence:

```bash
python3 scripts/build_verified_fraud_policy_chunks.py
```

Apply `supabase/migrations/0003_fraud_policy_memory.sql`, configure the backend-only Supabase values in `.env.local`, and ingest directly:

```bash
.venv/bin/python scripts/ingest_fraud_policy_memory.py --require-supabase
```

Without Supabase credentials, the same command without `--require-supabase` stages rows in `data/store/*.jsonl`. Replay all staged memory later with:

```bash
PYTHONPATH=src .venv/bin/python -m casefile.store --replay
```
