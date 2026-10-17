#!/usr/bin/env python3
"""Create the fraud-data research brief as a styled Word document."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "data/fraud_detection/rules/policy_rules.jsonl"
OUTPUT_PATH = ROOT / "output/fraud_detection_data_research_brief.docx"

NAVY = "14213D"
TEAL = "007C83"
MINT = "DFF4F2"
GOLD = "FCA311"
INK = "202938"
SLATE = "4B5563"
LIGHT = "F4F7FA"
PALE_BLUE = "EAF1F8"
WHITE = "FFFFFF"
RED = "A51C30"


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_border(cell, color: str = "D7DEE7", size: str = "4") -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.first_child_found_in("w:tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = "w:" + edge
        element = borders.find(qn(tag))
        if element is None:
            element = OxmlElement(tag)
            borders.append(element)
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), size)
        element.set(qn("w:color"), color)


def set_repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def prevent_row_split(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    cant_split = OxmlElement("w:cantSplit")
    tr_pr.append(cant_split)


def set_cell_margins(cell, top=80, start=90, bottom=80, end=90) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for margin, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{margin}"))
        if node is None:
            node = OxmlElement(f"w:{margin}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_run_font(run, size=None, bold=None, color=None, name="Aptos") -> None:
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color is not None:
        run.font.color.rgb = RGBColor.from_string(color)


def add_hyperlink(paragraph, text: str, url: str, color=TEAL, underline=True):
    part = paragraph.part
    rel_id = part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink", is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), rel_id)
    run = OxmlElement("w:r")
    r_pr = OxmlElement("w:rPr")
    c = OxmlElement("w:color")
    c.set(qn("w:val"), color)
    r_pr.append(c)
    if underline:
        u = OxmlElement("w:u")
        u.set(qn("w:val"), "single")
        r_pr.append(u)
    r_fonts = OxmlElement("w:rFonts")
    r_fonts.set(qn("w:ascii"), "Aptos")
    r_fonts.set(qn("w:hAnsi"), "Aptos")
    r_pr.append(r_fonts)
    run.append(r_pr)
    text_node = OxmlElement("w:t")
    text_node.text = text
    run.append(text_node)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)
    return hyperlink


def add_page_number(paragraph) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = paragraph.add_run("  PAGE ")
    set_run_font(run, size=8, color=SLATE)
    fld_char1 = OxmlElement("w:fldChar")
    fld_char1.set(qn("w:fldCharType"), "begin")
    instr_text = OxmlElement("w:instrText")
    instr_text.set(qn("xml:space"), "preserve")
    instr_text.text = " PAGE "
    fld_char2 = OxmlElement("w:fldChar")
    fld_char2.set(qn("w:fldCharType"), "end")
    run._r.extend([fld_char1, instr_text, fld_char2])


def style_document(doc: Document) -> None:
    section = doc.sections[0]
    section.top_margin = Inches(0.65)
    section.bottom_margin = Inches(0.65)
    section.left_margin = Inches(0.72)
    section.right_margin = Inches(0.72)

    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = "Aptos"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Aptos")
    normal.font.size = Pt(10)
    normal.font.color.rgb = RGBColor.from_string(INK)
    normal.paragraph_format.space_after = Pt(5)
    normal.paragraph_format.line_spacing = 1.08

    for style_name, size, color, before, after in [
        ("Title", 31, NAVY, 0, 10),
        ("Subtitle", 13, SLATE, 0, 8),
        ("Heading 1", 20, NAVY, 14, 7),
        ("Heading 2", 13, TEAL, 10, 5),
        ("Heading 3", 10.5, NAVY, 8, 3),
    ]:
        style = styles[style_name]
        style.font.name = "Aptos Display" if style_name in {"Title", "Heading 1", "Heading 2"} else "Aptos"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), style.font.name)
        style.font.size = Pt(size)
        style.font.bold = style_name != "Subtitle"
        style.font.color.rgb = RGBColor.from_string(color)
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True

    for s in doc.sections:
        footer = s.footer
        p = footer.paragraphs[0]
        p.text = "CRUSOE RECURSIVE AGENTS  •  FRAUD DATA RESEARCH BRIEF"
        set_run_font(p.runs[0], size=8, color=SLATE)
        add_page_number(p)


def add_kicker(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    run = p.add_run(text.upper())
    set_run_font(run, size=9, bold=True, color=TEAL)


def add_rule(doc: Document, color=GOLD) -> None:
    table = doc.add_table(rows=1, cols=1)
    table.autofit = False
    table.columns[0].width = Inches(7.0)
    cell = table.cell(0, 0)
    set_cell_shading(cell, color)
    set_cell_margins(cell, top=0, bottom=0, start=0, end=0)
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    p.add_run(" ")
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def add_callout(doc: Document, title: str, body: str, fill=MINT, accent=TEAL) -> None:
    table = doc.add_table(rows=1, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    table.columns[0].width = Inches(0.12)
    table.columns[1].width = Inches(6.75)
    left, right = table.rows[0].cells
    set_cell_shading(left, accent)
    set_cell_shading(right, fill)
    for cell in (left, right):
        set_cell_border(cell, fill, "0")
        set_cell_margins(cell, top=110, bottom=110, start=110, end=110)
    p = right.paragraphs[0]
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run(title)
    set_run_font(r, size=10.5, bold=True, color=NAVY)
    p2 = right.add_paragraph(body)
    p2.paragraph_format.space_after = Pt(0)
    for run in p2.runs:
        set_run_font(run, size=9.5, color=INK)


def add_bullet(doc: Document, text: str, level=0, color=INK) -> None:
    p = doc.add_paragraph(style="List Bullet" if level == 0 else "List Bullet 2")
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run(text)
    set_run_font(r, size=9.7, color=color)


def add_numbered(doc: Document, text: str) -> None:
    p = doc.add_paragraph(style="List Number")
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run(text)
    set_run_font(r, size=9.7, color=INK)


def add_table(doc: Document, headers, rows, widths=None, font_size=8.5, header_fill=NAVY) -> None:
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    header = table.rows[0]
    set_repeat_table_header(header)
    for i, text in enumerate(headers):
        cell = header.cells[i]
        set_cell_shading(cell, header_fill)
        set_cell_border(cell, header_fill)
        set_cell_margins(cell)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        run = p.add_run(str(text))
        set_run_font(run, size=font_size, bold=True, color=WHITE)
        if widths:
            cell.width = Inches(widths[i])
    for row_index, values in enumerate(rows):
        row = table.add_row()
        prevent_row_split(row)
        fill = WHITE if row_index % 2 == 0 else LIGHT
        for i, value in enumerate(values):
            cell = row.cells[i]
            set_cell_shading(cell, fill)
            set_cell_border(cell)
            set_cell_margins(cell)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
            if widths:
                cell.width = Inches(widths[i])
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            run = p.add_run(str(value))
            set_run_font(run, size=font_size, color=INK)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def add_metric_cards(doc: Document, cards) -> None:
    table = doc.add_table(rows=1, cols=len(cards))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    for i, (value, label) in enumerate(cards):
        cell = table.cell(0, i)
        set_cell_shading(cell, LIGHT if i % 2 == 0 else PALE_BLUE)
        set_cell_border(cell, WHITE, "8")
        set_cell_margins(cell, top=140, bottom=140, start=120, end=120)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(value)
        set_run_font(r, size=20, bold=True, color=TEAL)
        p2 = cell.add_paragraph(label)
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p2.paragraph_format.space_after = Pt(0)
        set_run_font(p2.runs[0], size=8.5, bold=True, color=SLATE)


def add_pipeline(doc: Document) -> None:
    labels = [
        ("1", "Normalize", "transactions"),
        ("2", "Score", "features + rules"),
        ("3", "Summarize", "case evidence"),
        ("4", "Retrieve", "policies + specs"),
        ("5", "Explain", "cited review"),
    ]
    table = doc.add_table(rows=1, cols=5)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    for i, (number, title, subtitle) in enumerate(labels):
        cell = table.cell(0, i)
        set_cell_shading(cell, MINT if i % 2 == 0 else PALE_BLUE)
        set_cell_border(cell, WHITE, "10")
        set_cell_margins(cell, top=120, bottom=120, start=70, end=70)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(number)
        set_run_font(r, size=15, bold=True, color=GOLD)
        p2 = cell.add_paragraph(title)
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_run_font(p2.runs[0], size=9, bold=True, color=NAVY)
        p3 = cell.add_paragraph(subtitle)
        p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p3.paragraph_format.space_after = Pt(0)
        set_run_font(p3.runs[0], size=7.5, color=SLATE)


def add_source(doc: Document, code: str, title: str, publisher: str, url: str, note: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Inches(0.18)
    p.paragraph_format.first_line_indent = Inches(-0.18)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run(f"[{code}] ")
    set_run_font(r, size=8.5, bold=True, color=TEAL)
    add_hyperlink(p, title, url)
    r2 = p.add_run(f" — {publisher}. {note}")
    set_run_font(r2, size=8.5, color=INK)


def load_rules():
    return [json.loads(line) for line in RULES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def build() -> None:
    rules = load_rules()
    domains = Counter(rule["domain"] for rule in rules)
    doc = Document()
    style_document(doc)

    # Cover
    doc.add_paragraph().paragraph_format.space_after = Pt(54)
    add_kicker(doc, "Research & data readiness")
    title = doc.add_paragraph(style="Title")
    title.add_run("Grounded Fraud Detection\nData & Policy Pack")
    subtitle = doc.add_paragraph(style="Subtitle")
    subtitle.add_run("A source-vetted input plan for billing, payment, invoice, vendor, procurement, price, and quality signals")
    add_rule(doc)
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after = Pt(18)
    r = p.add_run("Prepared for Crusoe Recursive Agents Casefile")
    set_run_font(r, size=12, bold=True, color=NAVY)
    p2 = doc.add_paragraph("Research date: 17 October 2026  •  Public sources + connected Drive review")
    set_run_font(p2.runs[0], size=9.5, color=SLATE)
    add_metric_cards(doc, [("25", "CURATED SOURCES"), (str(len(rules)), "GROUNDED RULES"), ("1,000", "STARTER ROWS")])
    doc.add_paragraph().paragraph_format.space_after = Pt(18)
    add_callout(
        doc,
        "Decision in one sentence",
        "Use structured analytics for raw transactions and a separate, versioned RAG corpus for policies, vendor contracts, price evidence, quality specifications, and prior reviewed cases.",
    )
    doc.add_page_break()

    # Executive summary
    add_kicker(doc, "Executive brief")
    doc.add_heading("What to use first", level=1)
    p = doc.add_paragraph()
    p.add_run("Start with a complementary three-part bundle: ").bold = True
    p.add_run("IBM AML-Data or AMLSim for labeled financial behavior; the included UCI Online Retail sample for invoice, cancellation, quantity, and unit-price exploration; and the Open Contracting red-flag catalog for vendor and procurement rules. ")
    p.add_run("Ground the control narrative in DOJ, OFAC, World Bank, FAR, and Mastercard material. [S1–S5, S9–S14]")

    doc.add_heading("Key findings", level=2)
    add_bullet(doc, "GitHub offers strong synthetic and labeled transaction sources, but repository popularity is not a license. IBM AML-Data has the clearest research fit; the Fraud Detection Handbook is excellent for explainable experiments, while its raw-data repository needs a separate dataset-license check. [S1–S3]")
    add_bullet(doc, "Real retail data is available under CC BY 4.0 from UCI. It is useful for price, cancellation, return, and invoice anomalies, but it does not provide confirmed fraud outcomes. [S4–S5]")
    add_bullet(doc, "Procurement fraud needs contract, award, amendment, payment, supplier, buyer, and specification evidence. OCDS/USAspending can provide public records; they are not fraud labels. [S7–S8]")
    add_bullet(doc, "The strongest rules are contextual: payment-over-contract, split purchasing, single-bid competition, price reasonableness, specification mismatch, sanctions risk, third-party diligence, and merchant velocity/refund changes. [S9–S14]")
    add_bullet(doc, "Two Drive documents contain useful prototype fields and approval ideas, but they are not verified bank policy and should remain restricted design references. [D1–D2]")

    add_callout(
        doc,
        "Important limitation",
        "A rule hit or anomaly score is evidence for review—not proof of fraud. Sanctions blocks, payment holds, supplier exclusion, or adverse decisions require the organization's approved procedure and qualified human review.",
        fill="FFF4DE",
        accent=GOLD,
    )

    doc.add_heading("Pack contents", level=2)
    add_table(
        doc,
        ["Artifact", "Purpose", "Ready now"],
        [
            ["source_manifest.csv", "25 datasets, policies, company examples, Drive references, and Devpost patterns", "Yes"],
            ["policy_rules.jsonl", f"{len(rules)} paraphrased rules with page/section citations and required evidence", "Yes"],
            ["transaction_schema.json", "Canonical contract for billing, payment, invoice, procurement, and quality events", "Yes"],
            ["rag_policy_chunk_schema.json", "Versioning and provenance contract for retrievable evidence", "Yes"],
            ["uci_online_retail_sample.csv", "1,000-row attributed sample with anomaly-candidate annotations", "Yes"],
        ],
        widths=[1.65, 4.2, 0.85],
        font_size=8.2,
    )
    doc.add_page_break()

    # Architecture
    add_kicker(doc, "Architecture fit")
    doc.add_heading("Keep transaction scoring and policy retrieval separate", level=1)
    p = doc.add_paragraph(
        "Crusoe Recursive Agents Casefile already separates transactions, alerts, policies, tools, and investigation traces. Raw transaction rows should remain in its structured case-data pipeline, while the retrieval collection contains policy, contract, specification, and prior-case text with precise metadata."
    )
    p.add_run(" This keeps deterministic evidence generation separate from the agent's grounded explanation step.").italic = True
    add_pipeline(doc)
    doc.add_heading("What belongs where", level=2)
    add_table(
        doc,
        ["Layer", "Store", "Contents", "Primary operation"],
        [
            ["Raw events", "Warehouse / lake / dataframe", "Invoices, payments, refunds, awards, amendments, inspection results", "Filter, join, aggregate"],
            ["Feature layer", "Feature table / rules engine", "Velocity, duplicate keys, price variance, cumulative payment, supplier linkage", "Score and trigger"],
            ["Case record", "Operational database", "Facts, feature values, rule IDs, reviewer state, disposition", "Investigate and audit"],
            ["Evidence corpus", "Policy evidence index", "Policies, contracts, price schedules, quality specs, prior approved cases", "Retrieve and cite"],
            ["Narrative", "Crusoe-hosted agent", "Grounded explanation, missing evidence, recommended next review step", "Summarize—not decide"],
        ],
        widths=[1.0, 1.4, 3.05, 1.4],
        font_size=8.0,
    )
    doc.add_heading("Minimum case summary for retrieval", level=2)
    add_bullet(doc, "Identifiers: case, transaction, invoice, purchase order, contract, vendor, merchant, and customer tokens.")
    add_bullet(doc, "Facts: amount, currency, date/time, product/category, quantity, unit price, geography, channel, and payment method.")
    add_bullet(doc, "Derived evidence: relevant baselines, peer comparisons, cumulative totals, exact feature values, and triggered rule IDs.")
    add_bullet(doc, "Retrieval constraints: jurisdiction, document effective date, source authority, access scope, vendor/contract, and product specification.")
    doc.add_page_break()

    # Data shortlist
    add_kicker(doc, "Transaction & procurement data")
    doc.add_heading("Recommended dataset shortlist", level=1)
    add_table(
        doc,
        ["Source", "What it adds", "Labels", "License posture", "Use now"],
        [
            ["IBM AML-Data [S1]", "Transfers, purchases, cards, checks; graph structure", "Laundering labels", "Data CDLA-Sharing-1.0; code Apache-2.0", "Primary AML benchmark"],
            ["IBM AMLSim [S2]", "Controllable banking scenarios and AML patterns", "Known synthetic patterns", "Apache-2.0 code", "Generate custom scenarios"],
            ["Fraud Detection Handbook [S3]", "Customer-terminal-time transaction simulator", "Synthetic fraud label", "GPL-3.0 code; raw-data terms need review", "Interpretable small benchmark"],
            ["UCI Online Retail [S4]", "Invoice, SKU, quantity, unit price, cancellation", "No fraud label", "CC BY 4.0", "Included starter sample"],
            ["UCI Online Retail II [S5]", "Two years for drift and seasonality", "No fraud label", "CC BY 4.0", "Second-stage evaluation"],
            ["Olist [S6]", "Order, payment, seller, freight, product, review joins", "No fraud label", "Verify current Kaggle terms", "Price + quality proxy"],
            ["USAspending [S7]", "Federal awards and contract spending", "No fraud label", "Public government data", "Vendor/award analytics"],
            ["OCDS Liberia [S8]", "Tenders, bidders, awards, documents, amendments", "No fraud label", "Verify publication license", "Small procurement pilot"],
        ],
        widths=[1.35, 2.45, 1.1, 1.35, 1.15],
        font_size=7.6,
    )
    doc.add_heading("How to use the included UCI sample", level=2)
    p = doc.add_paragraph(
        "The sample deliberately includes baseline rows and examples with cancellations, non-positive quantity/price, or values above the source data's 99th percentile. Customer identifiers are tokenized. The annotations support pipeline testing only; they are not confirmed fraud labels."
    )
    add_table(
        doc,
        ["Candidate signal", "Rows in sample", "Interpretation"],
        [
            ["Baseline", "499", "No selected candidate condition; still not guaranteed clean"],
            ["Cancellation + non-positive quantity", "172", "Return/cancellation pattern for rule testing"],
            ["High quantity (p99)", "121", "Volume outlier relative to source dataset"],
            ["High unit price (p99)", "116", "Price outlier relative to source dataset"],
            ["Other / combined", "92", "Non-positive price or overlapping candidate conditions"],
        ],
        widths=[2.2, 1.1, 3.9],
        font_size=8.2,
    )
    doc.add_page_break()

    # Policy corpus
    add_kicker(doc, "Grounded policy corpus")
    doc.add_heading("Authoritative sources and what they contribute", level=1)
    add_table(
        doc,
        ["Source", "Grounded controls", "Best metadata filter"],
        [
            ["DOJ compliance evaluation [S9]", "Third-party diligence, business rationale, services actually performed, compensation reasonableness, ongoing monitoring", "US / government guidance / third-party"],
            ["OFAC framework [S10]", "Sanctions risk assessment, onboarding risk rating, screening calibration, escalation, records", "US / sanctions / effective date"],
            ["OCP red flags [S11]", "Split purchases, single bids, identity anomalies, value changes, excess payments, specification failures", "Procurement / global / red-flag ID"],
            ["World Bank procurement [S12]", "Abnormally low bids, lifecycle costing, quality, risk, sustainability, value for money", "Financing regime / procurement stage"],
            ["FAR 15.404-1 [S13]", "Comparable price evidence, adjusted historical prices, market research, unbalanced pricing", "US federal / section / current version"],
            ["Mastercard SPME [S14]", "Daily alerts, 90-day merchant baselines, refund and chargeback patterns, device/identity velocity", "Network role / region / edition"],
            ["Apple supplier standard [S15]", "Conflicts, material traceability, records, supplier oversight", "Company policy / supplier / effective date"],
            ["Walmart packaging guide [S16]", "Packaging and supply-chain quality expectations", "Company / product category / revision"],
        ],
        widths=[1.55, 3.8, 1.85],
        font_size=7.8,
    )
    add_callout(
        doc,
        "Company-specific grounding",
        "Apple, Walmart, and Mastercard documents are useful examples, but production decisions must retrieve the policy, contract, or specification that actually governs the organization, vendor, network role, product, and date in question.",
    )
    doc.add_heading("Version every policy chunk", level=2)
    add_bullet(doc, "Store source URL, publisher, title, edition/effective date, page/section, jurisdiction, authority level, access scope, retrieval timestamp, and content hash.")
    add_bullet(doc, "Retire or supersede outdated chunks; never let a newer document silently overwrite the evidence used in an earlier decision.")
    add_bullet(doc, "Use exact excerpts only where licensing and quotation limits permit; prefer concise paraphrases tied to page and section.")
    doc.add_page_break()

    # Rule catalog
    add_kicker(doc, "Rule library")
    doc.add_heading(f"{len(rules)} screening rules, organized for retrieval", level=1)
    domain_rows = [
        ("Third party", "DOJ-TP-001…005", "Diligence, rationale, service evidence, compensation, monitoring, re-engagement"),
        ("Sanctions", "OFAC-SCP-001…004", "Risk coverage, onboarding, screening calibration, interdict/escalate/report"),
        ("Procurement", "OCP-R011/R018/R042/R043", "Split purchases, single bid, supplier identity and official-contact matches"),
        ("Contract/payment", "OCP-R059/R068/R069", "Award-contract differences, payment over contract, price-increasing amendments"),
        ("Quality", "OCP-R073", "Delivered work, goods, or services fail contractual specifications"),
        ("Pricing", "WB-ALB-001/WB-VFM-001", "Abnormally low bid analysis, lifecycle cost, quality and risk"),
        ("Federal price analysis", "FAR-PRICE-001/002", "Comparable evidence and materially unbalanced line items"),
        ("Merchant/payment", "MC-FLC-001…004", "Timely alerts, refund/deposit anomalies, trend monitoring, shared-identifier velocity"),
        ("Supplier integrity", "APPLE-SUP-001…003", "Relationship disclosure, material traceability, record integrity"),
    ]
    add_table(doc, ["Domain", "Rule IDs", "Coverage"], domain_rows, widths=[1.3, 1.7, 4.2], font_size=8.0)

    doc.add_heading("Rules need configurable context", level=2)
    add_table(
        doc,
        ["Parameter", "Why it cannot be universal", "Configuration source"],
        [
            ["Approval threshold", "Varies by entity, jurisdiction, category, and delegation", "Delegation of authority / procurement policy"],
            ["Price variance", "Depends on product, quantity, location, terms, index, and date", "Contract, catalog, market data, historical adjustment"],
            ["Time window", "Split purchases and velocity behave differently by process", "Policy, control design, observed seasonality"],
            ["Merchant baseline", "New merchants and seasonal businesses need different comparisons", "Business plan, MCC peers, rolling history"],
            ["Quality tolerance", "Specifications and inspection methods are product-specific", "Contract, statement of work, quality standard"],
        ],
        widths=[1.35, 3.35, 2.5],
        font_size=8.0,
    )
    doc.add_page_break()

    # Schemas
    add_kicker(doc, "Data contract")
    doc.add_heading("Canonical fields to request from company systems", level=1)
    add_table(
        doc,
        ["Field group", "Minimum fields", "Rules enabled"],
        [
            ["Identity", "transaction, invoice, PO, contract, vendor, merchant, customer tokens", "Duplicate, linkage, re-engagement, conflict"],
            ["Economics", "amount, currency, quantity, unit price, contract amount, amendments", "Price variance, excess payment, split purchase"],
            ["Time & channel", "event time, channel, device, IP country, terminal", "Velocity, abnormal hours, geography mismatch"],
            ["Approval", "status, approver IDs, delegation tier, exception reason", "Authority breach, collusion indicators, override monitoring"],
            ["Delivery & quality", "specification reference, inspection result, accepted/delivered quantity", "Specification mismatch, premature payment"],
            ["Outcome labels", "confirmed fraud, label source, review time, disposition", "Supervised learning and evaluation"],
            ["Provenance", "source system, source record URI, ingestion time, content hash", "Audit, replay, correction"],
        ],
        widths=[1.35, 3.65, 2.2],
        font_size=8.1,
    )
    doc.add_heading("RAG chunk metadata", level=2)
    add_bullet(doc, "Required: chunk ID, text, source title/URL/date, page/section, authority level, access scope, retrieval time, and review state.")
    add_bullet(doc, "Strong filters: domain, jurisdiction, effective window, vendor or contract, product category, policy owner, and rule ID.")
    add_bullet(doc, "Security: do not embed raw PANs, bank accounts, tax identifiers, personal addresses, secrets, or unrestricted Drive content.")
    add_callout(
        doc,
        "Retrieval rule",
        "When policy versions conflict, prefer the document that is authoritative for the transaction's jurisdiction, network role, contract, and event date—and disclose the selected version in the answer.",
    )

    doc.add_heading("Example evidence query", level=2)
    p = doc.add_paragraph()
    r = p.add_run("Triggered facts: ")
    set_run_font(r, size=9.5, bold=True, color=NAVY)
    p.add_run("cumulative payments = 112% of approved contract; two price-increasing amendments; inspection incomplete.")
    p2 = doc.add_paragraph()
    r2 = p2.add_run("Retrieve: ")
    set_run_font(r2, size=9.5, bold=True, color=NAVY)
    p2.add_run("OCP-R068, OCP-R069, OCP-R073; governing contract cap; amendment approvals; acceptance and quality clauses.")
    p3 = doc.add_paragraph()
    r3 = p3.add_run("Answer: ")
    set_run_font(r3, size=9.5, bold=True, color=NAVY)
    p3.add_run("Explain the exact arithmetic and missing evidence, cite each source, and recommend human review—not a fraud verdict.")
    doc.add_page_break()

    # Drive and Devpost
    add_kicker(doc, "Connected sources")
    doc.add_heading("Google Drive findings", level=1)
    p = doc.add_paragraph(
        "The connected Drive search returned two relevant prototype documents. Personal-looking financial records were intentionally excluded from review and from this pack."
    )
    add_table(
        doc,
        ["Document", "Useful design signals", "Treatment"],
        [
            ["Yes bank usecase documentary [D1]", "Transaction type, amount limits, card/device/merchant features, role groups, approval thresholds, MFA", "Restricted design reference; verify authorship and authority before use"],
            ["yes bank API doc [D2]", "Frequency, amount, device/card, source, merchant, location, authorization flow", "Restricted design reference; not a policy source"],
        ],
        widths=[1.75, 3.65, 1.8],
        font_size=8.2,
    )
    add_callout(
        doc,
        "Drive boundary",
        "The URLs are preserved only in the local manifest. The document text is not copied into the public corpus, and the prototypes are not represented as official bank policy.",
        fill="FFF4DE",
        accent=GOLD,
    )
    doc.add_heading("Devpost findings", level=1)
    p = doc.add_paragraph(
        "Devpost supplied architecture inspiration, not a reusable authoritative policy dataset. Tallyrun uses deterministic AP checks; BillSenseAI describes quote-versus-invoice retrieval; redflags emphasizes evidence-backed supplier investigation. [P1–P3]"
    )
    add_bullet(doc, "Borrow the pattern: deterministic checks first, retrieval second, human review for material actions.")
    add_bullet(doc, "Do not treat project descriptions, screenshots, or demo data as regulatory authority or training labels.")
    add_bullet(doc, "No reviewed project clearly published a grounded company-policy corpus suitable for direct reuse.")
    doc.add_page_break()

    # Acquisition and implementation
    add_kicker(doc, "Execution plan")
    doc.add_heading("Acquire data in risk-controlled phases", level=1)
    add_numbered(doc, "Pilot with the included UCI sample and one synthetic labeled source (IBM AML-Data or AMLSim). Keep source licenses and retrieval dates beside every file.")
    add_numbered(doc, "Ingest the 28-rule JSONL into a separate policy-evidence collection. Add metadata filters before adding internal policies.")
    add_numbered(doc, "Map company invoices, payments, contracts, and quality records to the canonical schema using tokenized identifiers.")
    add_numbered(doc, "Implement a small deterministic rule set: duplicate invoice, payment over contract, split purchase, price variance, refund ratio, beneficiary change, and specification mismatch.")
    add_numbered(doc, "Create compact case summaries and retrieve only the sources relevant to triggered rules, effective dates, and access permissions.")
    add_numbered(doc, "Evaluate on time-aware splits with investigator-confirmed outcomes. Measure precision at review capacity, recall on confirmed cases, citation correctness, and alert latency.")

    doc.add_heading("Recommended first milestone", level=2)
    add_table(
        doc,
        ["Deliverable", "Acceptance check"],
        [
            ["Structured loader", "Rejects invalid currency/date/amount and logs provenance"],
            ["Seven deterministic checks", "Unit tests cover normal, boundary, and multi-currency cases"],
            ["Policy collection", "Every answer cites title, URL, page/section, and effective date"],
            ["Case review screen/API", "Shows raw evidence, feature values, rules, missing documents, and disposition"],
            ["Evaluation set", "Contains confirmed outcomes and a time-based holdout; no leakage from post-event fields"],
        ],
        widths=[2.05, 5.15],
        font_size=8.3,
    )
    doc.add_heading("Quality and governance gates", level=2)
    add_bullet(doc, "Data rights approved; source and derivative licenses documented.")
    add_bullet(doc, "No raw sensitive credentials or personal identifiers in embeddings or logs.")
    add_bullet(doc, "Rules reviewed by compliance, procurement, finance, security, and legal owners as applicable.")
    add_bullet(doc, "Policy versioning, access controls, retention, and deletion procedures tested.")
    add_bullet(doc, "Bias and disparate-impact checks performed for geography, merchant category, customer, and vendor segments where lawful and relevant.")
    add_bullet(doc, "Human override, appeal, reason codes, and audit trail available for every material decision.")
    doc.add_page_break()

    # Sources
    add_kicker(doc, "Source register")
    doc.add_heading("Primary datasets and tools", level=1)
    add_source(doc, "S1", "IBM AML-Data", "IBM", "https://github.com/IBM/AML-Data", "Synthetic financial transactions with laundering labels; data license is identified in the repository documentation.")
    add_source(doc, "S2", "IBM AMLSim", "IBM", "https://github.com/IBM/AMLSim", "Apache-2.0 simulator for synthetic banking transactions and AML patterns.")
    add_source(doc, "S3", "Fraud Detection Handbook simulated dataset", "Fraud Detection Handbook", "https://github.com/Fraud-Detection-Handbook/fraud-detection-handbook/blob/main/Chapter_3_GettingStarted/SimulatedDataset.ipynb", "Interpretable synthetic transaction generator; code is GPL-3.0.")
    add_source(doc, "S4", "UCI Online Retail", "UCI Machine Learning Repository", "https://archive.ics.uci.edu/dataset/352/online%2Bretail", "541,909 retail lines; CC BY 4.0; source of the included sample.")
    add_source(doc, "S5", "UCI Online Retail II", "UCI Machine Learning Repository", "https://archive.ics.uci.edu/dataset/502/online%2Bretail%2Bii", "1,067,371 retail lines over two years; CC BY 4.0.")
    add_source(doc, "S6", "Brazilian E-Commerce Public Dataset by Olist", "Olist / Kaggle", "https://www.kaggle.com/olistbr/brazilian-ecommerce/home/", "Orders, payments, sellers, products, delivery, and reviews; verify current dataset terms.")
    add_source(doc, "S7", "USAspending API", "United States Government", "https://api.usaspending.gov/docs/endpoints", "Federal awards and contract spending endpoints.")
    add_source(doc, "S8", "Liberia PPCC open contracting data", "OCP Data Registry", "https://data.open-contracting.org/en/publication/156", "Small OCDS procurement source with tenders, suppliers, awards, documents, and amendments.")
    add_source(doc, "S17", "PaySim mobile money simulation", "PaySim authors / Kaggle", "https://www.kaggle.com/datasets/ealaxi/paysim1", "Large synthetic mobile-money benchmark; verify current Kaggle license before redistribution.")
    add_source(doc, "S18", "Cardinal", "Open Contracting Partnership", "https://github.com/open-contracting/cardinal-rs", "Open-source implementation of procurement red-flag measurement over OCDS data.")

    doc.add_heading("Policies, rulebooks, and standards", level=1)
    add_source(doc, "S9", "Evaluation of Corporate Compliance Programs", "US Department of Justice", "https://www.justice.gov/criminal/criminal-fraud/page/file/937501/dl?inline=", "September 2024; third-party and compliance-program evaluation guidance.")
    add_source(doc, "S10", "A Framework for OFAC Compliance Commitments", "US Treasury OFAC", "https://ofac.treasury.gov/system/files/126/framework_ofac_cc.pdf", "May 2019; sanctions compliance framework and root causes.")
    add_source(doc, "S11", "Red Flags in Public Procurement 2024", "Open Contracting Partnership", "https://www.open-contracting.org/wp-content/uploads/2024/12/OCP2024-RedFlagProcurement-1.pdf", "Catalog of 73 procurement red flags with implementation guidance.")
    add_source(doc, "S12", "Procurement Regulations for IPF Borrowers, seventh edition", "World Bank", "https://thedocs.worldbank.org/en/doc/c84273d1b230aeb2b0b8134de5dc8cd7-0290012025/original/Procurement-Regulations-7th-Edition-Sep-2025.pdf", "September 2025; low bids, value for money, lifecycle cost, quality, and risk.")
    add_source(doc, "S13", "FAR 15.404-1 Proposal analysis", "US Acquisition.gov", "https://www.acquisition.gov/far/15.404-1", "Price-analysis techniques and unbalanced pricing; retrieve current version at decision time.")
    doc.add_page_break()
    doc.add_heading("Company policies and connected references", level=1)
    add_source(doc, "S14", "Security Rules and Procedures—Merchant Edition", "Mastercard", "https://www.mastercard.com/content/dam/mccom/shared/business/support/rules-pdfs/SPME-Manual.pdf", "4 August 2026 edition observed; merchant deposit, velocity, refund, chargeback, and ongoing monitoring controls.")
    add_source(doc, "S15", "Supplier Code of Conduct and Supplier Responsibility Standards", "Apple", "https://s203.q4cdn.com/367071867/files/doc_downloads/2025/11/Supplier-Code-of-Conduct-and-Supplier-Responsibility-Standards.pdf", "Effective 11 November 2025; company-specific supplier controls and traceability.")
    add_source(doc, "S16", "Supply Chain Packaging Guide", "Walmart", "https://corporate.walmart.com/content/dam/corporate/documents/suppliers/requirements/supply-chain-packaging-guide.pdf", "Example of product and packaging quality requirements.")
    add_source(doc, "S19", "FCPA Resource Guide, second edition", "US DOJ and SEC", "https://www.justice.gov/criminal/criminal-fraud/fcpa-resource-guide", "Supplementary anti-bribery and third-party payment guidance.")

    doc.add_heading("Connected Drive and Devpost references", level=1)
    add_source(doc, "D1", "Yes bank usecase documentary", "Connected Google Drive", "https://docs.google.com/document/d/1DDPk4AAq_xPn-wKHF6Wx99uncKRTZGX5MqMS6YEbKlg/edit?usp=drivesdk", "Restricted prototype; not verified as official policy.")
    add_source(doc, "D2", "yes bank API doc", "Connected Google Drive", "https://docs.google.com/document/d/1LvGUsfoEvg-wIhSy2VYRggOngdWE9K8KcxO4a7LwWGA/edit?usp=drivesdk", "Restricted prototype; not verified as official policy.")
    add_source(doc, "P1", "Tallyrun", "Devpost", "https://devpost.com/software/tallyrun", "Accounts-payable rules and review-flow inspiration.")
    add_source(doc, "P2", "BillSenseAI", "Devpost", "https://devpost.com/software/billsenseai-1m8o6a", "Invoice anomaly and quote-versus-invoice retrieval inspiration.")
    add_source(doc, "P3", "redflags", "Devpost", "https://devpost.com/software/redflags-eg6rhj", "Evidence-backed supplier investigation inspiration.")

    doc.add_heading("Method note", level=2)
    p = doc.add_paragraph(
        "Sources were reviewed through public web search, the connected GitHub and Google Drive services, and repository inspection. Rules are concise paraphrases rather than legal quotations. The source manifest records access and redistribution cautions. This brief is research and system-design guidance, not legal advice."
    )
    p.paragraph_format.space_after = Pt(0)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUTPUT_PATH)
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    build()
