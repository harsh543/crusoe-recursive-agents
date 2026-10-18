"""Builds docs/casefile_architecture_dark.svg (standalone, literal colors, for Canva/Gamma) and docs/casefile_architecture_dark.html.
Row counts and sample rows are values read from the live Supabase project on Oct 17 2026 (synthetic data); update COUNTS to refresh."""
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
W, H = 1360, 1340

INK, MUTED, GROUND, PANEL, LINE = "#e8edf4", "#93a1b6", "#0c1118", "#121922", "#2a3748"
KINDS = {  # kind: (stroke, fill tint, badge text)
    "model": ("#f0b35a", "#251d10", "CRUSOE · NEMOTRON"),
    "code": ("#4fd1c5", "#0e2321", "CODE · NO MODEL"),
    "human": ("#b69cff", "#1b1630", "HUMAN"),
    "plain": ("#5d6d85", "#151d28", ""),
    "refuse": ("#ff7b72", "#2a1416", "CODE + CRUSOE"),
    "data": ("#6aa8ff", "#0f1b2f", "SUPABASE"),
}
COUNTS = {"runs": 20, "cases": 75, "contracts": 64, "playbooks": 2, "evidence": 179, "claims": 185, "events": 2156,
          "check_results": 839, "attributions": 71, "dispositions": 121, "audit_log": 1451,
          "grounding_requests": 320, "grounding_docs": 919, "rag_policy_chunks": 20,
          "accounts": 4, "transactions": 12, "device_events": 10}
out: list[str] = []


def t(x, y, s, size=13, fill=INK, weight="400", anchor="start", mono=False, extra=""):
    fam = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" if mono else "system-ui,-apple-system,'Segoe UI',Roboto,sans-serif"
    out.append(f'<text x="{x}" y="{y}" font-family="{fam}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
               f'text-anchor="{anchor}" {extra}>{escape(s)}</text>')


def box(x, y, w, h, kind, title, lines=(), badge=True, size=13):
    stroke, fill, tag = KINDS[kind]
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1.4"/>')
    if badge and tag:
        bw = len(tag) * 6.2 + 14
        out.append(f'<rect x="{x + w - bw - 10}" y="{y - 9}" width="{bw}" height="18" rx="9" fill="{GROUND}" stroke="{stroke}" stroke-width="1"/>')
        t(x + w - bw / 2 - 10, y + 4, tag, 10, stroke, "700", "middle")
    t(x + 14, y + 25, title, 14, stroke, "700")
    limit = int((w - 28) / (size * 0.56))
    for i, line in enumerate(lines):
        assert len(line) <= limit, f"line too long for box ({len(line)} > {limit}): {line}"
        t(x + 14, y + 47 + i * (size + 6), line, size, INK if i == 0 else MUTED)


def arrow(points, color=MUTED, dashed=False, label=None, lx=None, ly=None, anchor="start"):
    mid = {MUTED: "m", "#ff7b72": "r", "#6aa8ff": "b", "#4fd1c5": "c"}[color]
    d = " ".join(f"{x},{y}" for x, y in points)
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    out.append(f'<polyline points="{d}" fill="none" stroke="{color}" stroke-width="1.6"{dash} marker-end="url(#arr-{mid})"/>')
    if label:
        t(lx, ly, label, 12, color, "600", anchor)


out.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
           f'aria-label="Casefile architecture: transaction mode and records mode share one investigate, verify, gate loop on Crusoe Nemotron models, with account data and the run record stored in Supabase">')
out.append("<defs>" + "".join(
    f'<marker id="arr-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
    f'<path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>' for k, c in
    (("m", MUTED), ("r", "#ff7b72"), ("b", "#6aa8ff"), ("c", "#4fd1c5"))) + "</defs>")
out.append(f'<rect width="{W}" height="{H}" fill="{GROUND}"/>')

# ---- lane titles
t(60, 40, "TRANSACTION MODE", 15, INK, "700")
t(60, 58, "alerts A-104 / A-105 (synthetic accounts)", 12, MUTED)
t(460, 40, "RECORDS MODE", 15, INK, "700")
t(460, 58, "public-procurement case files, pseudonymized", 12, MUTED)

LX, RX, LW = 60, 460, 370
box(LX, 74, LW, 52, "plain", "Alert + account hint", ["tenant · email or account id · time window"], badge=False)
box(LX, 152, LW, 100, "code", "GUARDRAIL 1 · governance + required fields",
    ["harness/gates.py, before any model call", "bad alert type or uncertified agent: 0 tokens", "email passed as account_id: stop, ask a human"])
box(LX, 282, LW, 78, "model", "PLANNER · Super VL", ["agents/planner.py", "adds checks from an allowlist, nothing removed"])
box(LX, 390, LW, 74, "code", "build_contract (frozen)", ["mandatory checks can't be removed", "any change creates version + 1"])
box(RX, 74, LW, 52, "plain", "Case file (.md / .txt)", ["attributed statements about a public matter"], badge=False)
box(RX, 152, LW, 100, "model", "INTAKE · Super VL", ["text into atomic, attributed claims", "strict JSON schema, thinking off"])
box(RX, 282, LW, 78, "code", "GUARDRAIL · enforce_scope", ["wrongdoing words: out_of_scope, no research", "private individuals are never researched"])

arrow([(245, 126), (245, 152)]); arrow([(245, 252), (245, 282)]); arrow([(245, 360), (245, 390)]); arrow([(245, 464), (245, 510)])
arrow([(645, 126), (645, 152)]); arrow([(645, 252), (645, 282)])
arrow([(645, 360), (645, 510)], label="each claim", lx=655, ly=440)

# ---- shared loop
box(60, 510, 770, 128, "model", "INVESTIGATOR · Lightning · read-only tool loop",
    ["transactions: resolve_account, get_device_history, get_transactions",
     "records: search_documents, read_document (You.com Search, then exact-URL Contents)",
     "tools gated per role by harness/registry.py · PII masked by the router · strict JSON schema"])
arrow([(445, 638), (445, 676)])
box(60, 676, 770, 104, "code", "VERIFIER · code, no model",
    ["evidence ok? right account? window covered? verbatim quote? numbers recomputed?",
     "policy followed? neutral wording? conflicts listed? (verifier.py, records/verifier.py)"])
box(60, 826, 370, 124, "refuse", "GATE REFUSES · ATTRIBUTOR", ["Lightning names the failed agent + step", "escalates to Super VL if the answer is invalid",
                                                                 "targeted re-plan · LoopGuard: max 2 re-plans"])
arrow([(225, 780), (225, 826)], "#ff7b72", label="fail", lx=236, ly=808)
arrow([(22, 888), (22, 574), (60, 574)], "#ff7b72")
out.append(f'<path d="M22,888 L60,888" stroke="#ff7b72" stroke-width="1.6" fill="none"/>')
t(14, 730, "back to investigator", 12, "#ff7b72", "600", "middle", extra='transform="rotate(-90 14 730)"')
arrow([(700, 780), (700, 1000)], "#4fd1c5", label="pass", lx=712, ly=900)
t(460, 872, "Only checks that pass in code", 13, MUTED)
t(460, 892, "reach the Gate. A fluent answer", 13, MUTED)
t(460, 912, "can't skip them.", 13, MUTED)
box(60, 1000, 770, 150, "code", "GATE · the only writer (gate.py, records/gate.py)",
    ["allowlist · idempotency key · refuses closure that did not verify",
     "transactions: escalated | closed_benign | insufficient_evidence | collection_failed",
     "records: supported | contradicted | insufficient_evidence | out_of_scope"])
arrow([(245, 1150), (245, 1190)]); arrow([(645, 1150), (645, 1190)])
box(60, 1190, 370, 70, "human", "ANALYST REVIEW QUEUE", ["harness/review.py · the analyst decides"])
box(460, 1190, 370, 70, "plain", "report.md + retrieval audit", ["pseudonymized · \"Not a legal finding\""], badge=False)

# ---- Supabase panel
PX, PW = 900, 440
out.append(f'<rect x="{PX}" y="74" width="{PW}" height="976" rx="8" fill="{PANEL}" stroke="#6aa8ff" stroke-width="1.4"/>')
t(PX + 16, 100, "SUPABASE · Postgres", 15, "#6aa8ff", "700")
t(PX + 16, 119, "row-level security on · synthetic data · counts read live", 12, MUTED)


def group(y, h, title, sub):
    out.append(f'<rect x="{PX + 12}" y="{y}" width="{PW - 24}" height="{h}" rx="6" fill="{KINDS["data"][1]}" stroke="{LINE}" stroke-width="1"/>')
    t(PX + 26, y + 22, title, 13, "#6aa8ff", "700")
    if sub:
        t(PX + 26, y + 40, sub, 11.5, MUTED)


group(134, 150, "GROUNDING · You.com retrieval log", "written on every search and fetch")
for i, k in enumerate(("grounding_requests", "grounding_docs", "rag_policy_chunks")):
    t(PX + 26, 194 + i * 22, k, 12.5, INK, mono=True)
    t(PX + PW - 28, 194 + i * 22, f"{COUNTS[k]:,}", 12.5, "#6aa8ff", "700", "end", mono=True)
t(PX + 26, 268, "URL, content hash, time and purpose per request", 11.5, MUTED)

group(296, 330, "ACCOUNT DATA · read by the investigator's tools", "db_source.py replaces Case.raw when run with --supabase")
y0 = 384
t(PX + 26, y0, "transactions · acct_1040 (takeover-shaped)", 12, INK, "600")
for i, (a, b, c) in enumerate([("07:10", "charge", "1.00"), ("07:11", "charge", "2.00"), ("07:12", "charge", "1.00"),
                               ("07:30", "transfer", "5,501.00  to Velo Holdings (new)")]):
    t(PX + 26, y0 + 20 + i * 18, f"{a}  {b:<9}{c}", 12, MUTED, mono=True)
y1 = y0 + 108
t(PX + 26, y1, "transactions · acct_1050 (benign lookalike)", 12, INK, "600")
for i, (a, b, c) in enumerate([("05:00", "payroll", "3,603.00"), ("05:00", "transfer", "1,370.00  to New Landlord LLC (new)")]):
    t(PX + 26, y1 + 20 + i * 18, f"{a}  {b:<9}{c}", 12, MUTED, mono=True)
y2 = y1 + 74
t(PX + 26, y2, "device_events · acct_1040", 12, INK, "600")
t(PX + 26, y2 + 20, "d1 US known · d2 RO new 07:00 · mfa_reset 07:05", 12, MUTED, mono=True)
t(PX + 26, y2 + 44, f"accounts {COUNTS['accounts']} · transactions {COUNTS['transactions']} · device_events {COUNTS['device_events']}  (fictional names)", 11.5, "#6aa8ff", "700")

group(668, 366, "RUN RECORD · persist.py", "after each step; the Gate stays the only decision-maker")
rows = [("START OF RUN", [("runs", "runs"), ("cases", "cases"), ("contracts", "contracts (sha256)"), ("playbooks", "playbooks")], 738),
        ("INVESTIGATOR WRITES", [("evidence", "evidence"), ("claims", "claims"), ("events", "events: every Crusoe call, tokens, cost")], 830),
        ("VERIFIER + ATTRIBUTOR WRITE", [("check_results", "check_results"), ("attributions", "attributions")], 908),
        ("GATE WRITES", [("dispositions", "dispositions (idempotency key)"), ("audit_log", "audit_log (hash-chained)")], 966)]
for title, tabs, y in rows:
    t(PX + 26, y, title, 11.5, MUTED, "700")
    for i, (k, label) in enumerate(tabs):
        yy = y + 20 + i * 18
        t(PX + 26, yy, label, 12, INK, mono=True)
        t(PX + PW - 28, yy, f"{COUNTS[k]:,}", 12, "#6aa8ff", "700", "end", mono=True)

# ---- Supabase connectors (dashed blue) ; read arrows point at the investigator, write arrows at the panel
B = "#6aa8ff"
arrow([(830, 520), (848, 520), (848, 210), (PX + 12, 210)], B, True)
arrow([(PX + 12, 470), (868, 470), (868, 552), (830, 552)], B, True)
arrow([(830, 612), (884, 612), (884, 852), (PX + 12, 852)], B, True)
arrow([(830, 746), (868, 746), (868, 930), (PX + 12, 930)], B, True)
arrow([(830, 1050), (884, 1050), (884, 990), (PX + 12, 990)], B, True)

# ---- legend
ly = 1296
items = [("model", "Nemotron model call on Crusoe Managed Inference"), ("code", "plain code, no model"), ("human", "human"),
         ("data", "Supabase (dashed: arrowhead shows read or write)"), ("refuse", "refusal and repair")]
x = 60
for kind, label in items:
    stroke, fill, _ = KINDS[kind]
    out.append(f'<rect x="{x}" y="{ly - 11}" width="14" height="14" rx="3" fill="{fill}" stroke="{stroke}" stroke-width="1.4"/>')
    t(x + 22, ly, label, 12, MUTED)
    x += 22 + len(label) * 6.4 + 26
out.append("</svg>")
svg = "\n".join(out)
(ROOT / "docs" / "casefile_architecture_dark.svg").write_text(svg)

page = f"""<title>Casefile Architecture</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>
:root {{ --ground: {GROUND}; --ink: {INK}; --muted: {MUTED}; --line: {LINE}; --panel: {PANEL}; --amber: #f0b35a; --teal: #4fd1c5;
  --blue: #6aa8ff; color-scheme: dark; }}
body {{ background: var(--ground); color: var(--ink); font: 15px/1.55 system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
  padding-block: 28px; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }}
main {{ max-width: 1400px; margin: 0 auto; display: grid; gap: 20px; }}
h1 {{ margin: 0; font-size: 1.5rem; letter-spacing: -0.01em; text-wrap: balance; }}
p {{ margin: 0; color: var(--muted); max-width: 70ch; }}
.scroll {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; background: {GROUND}; }}
.scroll svg {{ display: block; width: 100%; min-width: 1000px; height: auto; }}
.notes {{ display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }}
.notes div {{ border-top: 2px solid var(--line); padding-top: 10px; min-width: 0; }}
.notes b {{ display: block; color: var(--ink); font-size: 0.8rem; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 4px; }}
.notes span {{ color: var(--muted); font-size: 0.92rem; }}
</style>
<main>
  <div><h1>Casefile architecture</h1>
  <p>Two modes share one loop: investigate, verify in code, then let the Gate write. Amber boxes are Nemotron calls on Crusoe; everything teal is plain code. The right panel is the live Supabase project.</p></div>
  <figure style="margin:0"><div class="scroll">{svg}</div>
  <figcaption style="color:var(--muted);font-size:.85rem;margin-top:8px">Counts and sample rows were read from Supabase during this session. All accounts, names and transactions are synthetic.</figcaption></figure>
  <div class="notes">
    <div><b>Account data</b><span>Four synthetic accounts hold 12 transactions and 10 device events. The investigator reads them through db_source.py only when a run uses --supabase; offline tests and the earlier benchmark numbers read in-memory cases.</span></div>
    <div><b>Where Crusoe runs</b><span>Super VL plans and does intake. Lightning investigates and attributes, with Super VL as the fallback. Verification, scope, the Gate and masking never call a model.</span></div>
    <div><b>Records mode</b><span>Case files are pseudonymized in output, claims are attributed, and legal conclusions or claims about private individuals are never researched.</span></div>
  </div>
</main>
"""
(ROOT / "docs" / "casefile_architecture_dark.html").write_text(page)
print("wrote docs/casefile_architecture_dark.svg and .html;", len(svg) // 1024, "KB svg")
