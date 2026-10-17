#!/usr/bin/env python3
"""Build the first reviewed fraud-policy RAG batch from saved You.com evidence.

The builder is deliberately fail-closed: each source must exist in a saved Contents
response and contain expected phrases before any chunk derived from it is emitted.
The output is review-ready, not legal advice and not an accusation of fraud.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DIR = ROOT / "data" / "fraud_detection" / "research" / "youcom"
RULES_PATH = ROOT / "data" / "fraud_detection" / "rules" / "policy_rules.jsonl"
OUTPUT_DIR = ROOT / "data" / "fraud_detection" / "rag"
OUTPUT_PATH = OUTPUT_DIR / "verified_policy_chunks_batch_01.jsonl"
MANIFEST_PATH = OUTPUT_DIR / "verified_policy_chunks_batch_01_manifest.json"

CONTENTS_FILES = (
    RESEARCH_DIR / "selected_policy_contents_batch_01.json",
    RESEARCH_DIR / "selected_policy_contents_batch_02.json",
)

DOJ_ECCP = "https://www.justice.gov/criminal/criminal-fraud/page/file/937501/dl?inline="
OFAC_FRAMEWORK = "https://ofac.treasury.gov/media/16331/download?inline="
OFAC_CANONICAL = "https://ofac.treasury.gov/system/files/126/framework_ofac_cc.pdf"
FINCEN_BOI = "https://www.fincen.gov/boi"
FINCEN_CDD = "https://www.fincen.gov/news/news-releases/fincen-reminds-financial-institutions-cdd-rule-becomes-effective-today"
FAR_PART_3 = "https://www.acquisition.gov/far/part-3"
FAR_ETHICS = "https://www.acquisition.gov/far/52.203-13"
FAR_COMMERCIAL = "https://www.acquisition.gov/far/52.212-4"
FAR_PROMPT_PAYMENT = "https://www.acquisition.gov/far/subpart-32.9"
FAR_PRICE = "https://www.acquisition.gov/far/15.404-1"
FAR_RETENTION = "https://www.acquisition.gov/far/subpart-4.7"
SEC_CONTROLS = "https://www.sec.gov/spotlight/fcpa/fcpa-recordkeeping.pdf"

SOURCE_CHECKS = {
    DOJ_ECCP: (
        "business rationale for the use of third parties",
        "compensation is commensurate",
        "ongoing monitoring of the third-party relationships",
    ),
    OFAC_FRAMEWORK: (
        "five essential components of compliance",
        "identify, interdict, escalate, report",
        "due diligence on an organization’s customers",
    ),
    FINCEN_BOI: (
        "The final rule became effective on August 14, 2026",
        "U.S. companies are exempt from BOI reporting requirements",
    ),
    FINCEN_CDD: (
        "The CDD Rule has four core requirements",
        "conduct ongoing monitoring",
    ),
    FAR_PART_3: (
        "avoid strictly any conflict of interest",
        "credible evidence of a violation",
    ),
    FAR_ETHICS: (
        "Exercise due diligence to prevent and detect criminal conduct",
        "Timely disclosure, in writing",
    ),
    FAR_COMMERCIAL: (
        "An invoice must include",
        "duplicate contract financing or invoice payment",
    ),
    FAR_PROMPT_PAYMENT: (
        "Payment will be based on receipt of a proper invoice",
        "must be supported by a receiving report",
    ),
    FAR_PRICE: (
        "final agreed-to _price_ is fair and reasonable",
        "published market _prices_",
        "Unbalanced _pricing_",
    ),
    FAR_RETENTION: (
        "Accounts payable records to support disbursements",
        "Retain 4 years",
    ),
    SEC_CONTROLS: (
        "make and keep books, records, and accounts",
        "system of internal accounting controls",
    ),
}

VERIFIED_EXISTING_RULES = {
    "DOJ-TP-001",
    "DOJ-TP-002",
    "DOJ-TP-003",
    "DOJ-TP-004",
    "DOJ-TP-005",
    "OFAC-SCP-001",
    "OFAC-SCP-002",
    "OFAC-SCP-003",
    "OFAC-SCP-004",
    "FAR-PRICE-001",
    "FAR-PRICE-002",
}


def _load_contents() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    docs: dict[str, dict[str, Any]] = {}
    retrieved: dict[str, str] = {}
    for path in CONTENTS_FILES:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        timestamp = envelope["provenance"]["retrieved_at"]
        for item in envelope["response"]:
            url = item.get("url")
            markdown = item.get("markdown")
            if url and markdown:
                docs[url] = item
                retrieved[url] = timestamp
    return docs, retrieved


def _verify_sources(docs: dict[str, dict[str, Any]]) -> None:
    failures: list[str] = []
    for url, phrases in SOURCE_CHECKS.items():
        markdown = (docs.get(url) or {}).get("markdown", "")
        if not markdown:
            failures.append(f"missing extracted source: {url}")
            continue
        folded = markdown.casefold()
        for phrase in phrases:
            if phrase.casefold() not in folded:
                failures.append(f"missing expected phrase {phrase!r} in {url}")
    if failures:
        raise SystemExit("Evidence verification failed:\n- " + "\n- ".join(failures))


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _base_record(
    *,
    rule_id: str,
    text: str,
    domain: str,
    source_title: str,
    source_url: str,
    source_date: str | None,
    source_section: str | None,
    authority_level: str,
    jurisdiction: str | None,
    retrieved_at: str,
    binding_status: str,
    applicability: str,
    evidence_fields: list[str],
    recommended_action: str,
    retrieval_source_url: str | None = None,
    source_page: str | None = None,
    effective_from: str | None = None,
    notes: str = "Review evidence only; not proof of fraud or a legal determination.",
) -> dict[str, Any]:
    return {
        "chunk_id": f"fraud-policy-v1:{rule_id}",
        "rule_id": rule_id,
        "text": text,
        "domain": domain,
        "source_title": source_title,
        "source_url": source_url,
        "source_date": source_date,
        "source_page": source_page,
        "source_section": source_section,
        "authority_level": authority_level,
        "jurisdiction": jurisdiction,
        "effective_from": effective_from,
        "effective_to": None,
        "access_scope": "public",
        "retrieved_at": retrieved_at,
        "content_hash": _hash(text),
        "supersedes_chunk_id": None,
        "review_status": "reviewed",
        "binding_status": binding_status,
        "applicability": applicability,
        "evidence_fields": evidence_fields,
        "recommended_action": recommended_action,
        "retrieval_source_url": retrieval_source_url or source_url,
        "notes": notes,
    }


def _rule_text(rule: dict[str, Any]) -> str:
    evidence = ", ".join(rule["evidence_fields"])
    return (
        f"{rule['title']}. Applicability: {rule['applicability']}. "
        f"Review condition: {rule['trigger_logic']} Recommended reviewer action: "
        f"{rule['recommended_action']} Evidence to preserve: {evidence}. "
        f"Caveat: {rule['notes']}"
    )


def _existing_records(retrieved: dict[str, str]) -> list[dict[str, Any]]:
    rules = [json.loads(line) for line in RULES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_id = {rule["rule_id"]: rule for rule in rules}
    missing = VERIFIED_EXISTING_RULES - by_id.keys()
    if missing:
        raise SystemExit(f"Missing policy rules: {sorted(missing)}")

    records = []
    for rule_id in sorted(VERIFIED_EXISTING_RULES):
        rule = by_id[rule_id]
        retrieval_url = OFAC_FRAMEWORK if rule["source_url"] == OFAC_CANONICAL else rule["source_url"]
        binding = "binding_when_applicable" if rule["authority_level"] == "law_or_regulation" else "nonbinding_guidance"
        records.append(_base_record(
            rule_id=rule_id,
            text=_rule_text(rule),
            domain=rule["domain"],
            source_title=rule["source_title"],
            source_url=rule["source_url"],
            source_date=rule.get("source_date"),
            source_page=rule.get("source_page"),
            source_section=rule.get("source_section"),
            authority_level=rule["authority_level"],
            jurisdiction=rule.get("jurisdiction"),
            retrieved_at=retrieved[retrieval_url],
            binding_status=binding,
            applicability=rule["applicability"],
            evidence_fields=rule["evidence_fields"],
            recommended_action=rule["recommended_action"],
            retrieval_source_url=retrieval_url,
            notes=rule["notes"],
        ))
    return records


def _new_records(retrieved: dict[str, str]) -> list[dict[str, Any]]:
    specs = [
        dict(
            rule_id="FINCEN-BOI-001",
            text="FinCEN's final rule effective August 14, 2026 exempts U.S.-created companies and U.S. persons from Corporate Transparency Act BOI reporting. Qualifying foreign entities registered to do business in a U.S. jurisdiction generally remain reporting companies, subject to exemptions, and do not report U.S.-person beneficial owners. Do not treat a missing FinCEN BOI filing by a domestic company as suspicious by itself; obtain ownership evidence directly when another compliance, contract, sanctions, tax, or procurement control requires it.",
            domain="beneficial_ownership",
            source_title="Beneficial Ownership Information Reporting",
            source_url=FINCEN_BOI,
            source_date="2026-08-14",
            source_section="Final BOI reporting rule alert",
            authority_level="law_or_regulation",
            jurisdiction="United States",
            binding_status="binding_when_applicable",
            applicability="Corporate Transparency Act reporting scope for domestic entities, U.S. persons, and qualifying foreign reporting companies.",
            evidence_fields=["formation_jurisdiction", "us_registration", "entity_exemption", "ownership_documents", "beneficial_owners", "control_persons"],
            recommended_action="Determine entity type and applicable exemption before treating BOI status as a control gap; independently collect ownership evidence when required by another control.",
            effective_from="2026-08-14",
        ),
        dict(
            rule_id="FINCEN-CDD-001",
            text="FinCEN's Customer Due Diligence rule requires covered financial institutions to identify and verify customers and beneficial owners of legal-entity customers, understand the nature and purpose of relationships to develop risk profiles, and conduct ongoing monitoring. The rule applies to specified covered financial institutions, not automatically to every commercial payer; vendor-review systems should record why the rule applies before relying on it.",
            domain="beneficial_ownership",
            source_title="FinCEN Reminds Financial Institutions that the CDD Rule Becomes Effective Today",
            source_url=FINCEN_CDD,
            source_date="2018-05-11",
            source_section="Four core CDD requirements",
            authority_level="law_or_regulation",
            jurisdiction="United States",
            binding_status="binding_for_covered_financial_institutions",
            applicability="Banks, broker-dealers, mutual funds, futures commission merchants, and introducing brokers covered by the BSA CDD rule.",
            evidence_fields=["customer_identity", "beneficial_owners", "control_person", "verification_method", "relationship_purpose", "risk_profile", "monitoring_status"],
            recommended_action="Confirm covered-institution status and retain the ownership-verification and monitoring evidence used for the relationship.",
        ),
        dict(
            rule_id="FAR-CONFLICT-001",
            text="FAR 3.101 requires federal business to be conducted impartially and directs avoidance of actual conflicts of interest and their appearance in Government-contractor relationships. Government employees generally may not solicit or accept gifts, favors, entertainment, loans, or other things of value from parties seeking or conducting agency business, subject to authorized exceptions.",
            domain="conflict_of_interest",
            source_title="FAR Part 3 — Improper Business Practices and Personal Conflicts of Interest",
            source_url=FAR_PART_3,
            source_date="2026-03-13",
            source_section="3.101-1 and 3.101-2",
            authority_level="law_or_regulation",
            jurisdiction="United States federal procurement",
            binding_status="binding_when_applicable",
            applicability="Federal agencies, personnel, and Government-contractor relationships; private-company policies may be broader.",
            evidence_fields=["employee_or_official", "vendor_relationship", "gift_or_benefit", "value", "date", "procurement_role", "disclosure", "recusal", "ethics_approval"],
            recommended_action="Route disclosed or detected relationships and benefits to the designated ethics or contracting reviewer; do not infer intent from a relationship alone.",
            effective_from="2026-03-13",
        ),
        dict(
            rule_id="FAR-ETHICS-001",
            text="When FAR 52.203-13 is included and its requirements apply, contractors must exercise due diligence to prevent and detect criminal conduct, maintain specified ethics and internal-control measures, and timely disclose credible evidence of covered fraud, conflict-of-interest, bribery, gratuity, or False Claims Act violations to the agency OIG and contracting officer. Applicability and clause exceptions must be checked against the actual contract.",
            domain="ethics_and_escalation",
            source_title="FAR 52.203-13 Contractor Code of Business Ethics and Conduct",
            source_url=FAR_ETHICS,
            source_date="2021-11",
            source_section="52.203-13(b) and (c)",
            authority_level="law_or_regulation",
            jurisdiction="United States federal procurement",
            binding_status="binding_contract_clause_when_incorporated",
            applicability="Federal contracts containing the clause, subject to the clause prescription and stated exceptions.",
            evidence_fields=["contract_number", "clause_included", "credible_evidence_basis", "involved_parties", "allegation_date", "oig_disclosure_date", "contracting_officer_notice", "remediation"],
            recommended_action="Preserve evidence, confirm clause applicability, and route credible-evidence determinations to qualified legal and contracting personnel.",
        ),
        dict(
            rule_id="FAR-INVOICE-001",
            text="For commercial products and services contracts using FAR 52.212-4, an invoice includes contractor identity, invoice date and number, contract and line-item references, description, quantity, unit of measure, unit and extended prices, shipping information when applicable, discount terms, payment destination, a defective-invoice contact, and required tax or EFT information. Payment is for items accepted and delivered under the contract.",
            domain="invoice_completeness",
            source_title="FAR 52.212-4 Contract Terms and Conditions—Commercial Products and Commercial Services",
            source_url=FAR_COMMERCIAL,
            source_date="2023-11",
            source_section="52.212-4(g) Invoice and (i) Payment",
            authority_level="law_or_regulation",
            jurisdiction="United States federal procurement",
            binding_status="binding_contract_clause_when_incorporated",
            applicability="Commercial products and commercial services contracts containing FAR 52.212-4.",
            evidence_fields=["vendor_name", "invoice_number", "invoice_date", "contract_number", "line_item", "description", "quantity", "unit_price", "extended_price", "shipment", "payment_recipient", "eft_change"],
            recommended_action="Perform an invoice-to-contract and acceptance match; return incomplete invoices through the authorized process rather than treating incompleteness alone as fraud.",
        ),
        dict(
            rule_id="FAR-OVERPAY-001",
            text="Under FAR 52.212-4(i)(5), a contractor that becomes aware of a duplicate invoice or contract-financing payment, or another Government overpayment, must remit the amount with a description and provide supporting documentation to the contracting officer. The duplicate or overpayment amount and the discovery, notice, remittance, and supporting-document dates should be preserved.",
            domain="duplicate_payment",
            source_title="FAR 52.212-4 Contract Terms and Conditions—Commercial Products and Commercial Services",
            source_url=FAR_COMMERCIAL,
            source_date="2023-11",
            source_section="52.212-4(i)(5) Overpayments",
            authority_level="law_or_regulation",
            jurisdiction="United States federal procurement",
            binding_status="binding_contract_clause_when_incorporated",
            applicability="Commercial products and commercial services contracts containing FAR 52.212-4.",
            evidence_fields=["duplicate_match", "overpayment_amount", "discovery_date", "contract_number", "line_item", "remittance_date", "supporting_documents", "contracting_officer_notice"],
            recommended_action="Hold duplicate release where authorized, calculate the overpayment, preserve the match evidence, and follow the contract's remittance and notice process.",
        ),
        dict(
            rule_id="FAR-RECEIPT-001",
            text="FAR 32.905 states that federal payment is based on a proper invoice and satisfactory contract performance. Except for the stated interim-service-payment exception, an invoice payment must be supported by a receiving report or other Government documentation authorizing payment, with contract, delivery, acceptance, and quantity information.",
            domain="three_way_match",
            source_title="FAR Subpart 32.9 — Prompt Payment",
            source_url=FAR_PROMPT_PAYMENT,
            source_date="2026-03-13",
            source_section="32.905 Payment documentation and process",
            authority_level="law_or_regulation",
            jurisdiction="United States federal procurement",
            binding_status="binding_when_applicable",
            applicability="Federal invoice payments, subject to the exceptions and contract-specific payment terms in Subpart 32.9.",
            evidence_fields=["contract_number", "proper_invoice", "receiving_report", "acceptance_official", "delivery_date", "accepted_quantity", "quality_status", "payment_authorization"],
            recommended_action="Require a documented contract/receipt/invoice match before payment unless a documented regulatory or contract exception applies.",
            effective_from="2026-03-13",
        ),
        dict(
            rule_id="SEC-IC-001",
            text="Exchange Act Section 13(b) requires covered issuers to keep books, records, and accounts that accurately and fairly reflect transactions and asset dispositions in reasonable detail, and to maintain internal accounting controls providing reasonable assurance for authorization, recording, controlled asset access, and periodic comparison of recorded and existing assets. Applicability depends on issuer status and control relationships.",
            domain="books_and_records",
            source_title="Recordkeeping and Internal Controls Provisions — Securities Exchange Act Section 13(b)",
            source_url=SEC_CONTROLS,
            source_date=None,
            source_section="15 U.S.C. 78m(b)(2), (5), (6), and (7)",
            authority_level="law_or_regulation",
            jurisdiction="United States securities law",
            binding_status="binding_for_covered_issuers",
            applicability="Issuers covered by Exchange Act Section 13(b), including the statute's rules for controlled and minority-owned entities.",
            evidence_fields=["issuer_status", "management_authorization", "invoice_record", "journal_entry", "account_code", "asset_access", "reconciliation", "exception_resolution"],
            recommended_action="Confirm issuer applicability and reconcile vendor-payment records to authorization, accounting, and asset evidence; escalate unexplained differences for human review.",
        ),
        dict(
            rule_id="FAR-RETENTION-001",
            text="For contracts within FAR Subpart 4.7's scope, accounts-receivable invoices, purchase orders, paid checks, accounts-payable support, vendor invoices, invoice audits, receiving and inspection reports, purchase-order backup, and specified quality-control records generally have four-year retention periods. Computer-record transfers must preserve integrity, reliability, security, and an audit trail; contract-specific requirements may change the period.",
            domain="records_retention",
            source_title="FAR Subpart 4.7 — Contractor Records Retention",
            source_url=FAR_RETENTION,
            source_date="2026-03-13",
            source_section="4.703 and 4.705-1 through 4.705-3",
            authority_level="law_or_regulation",
            jurisdiction="United States federal procurement",
            binding_status="binding_when_applicable",
            applicability="Records generated under contracts containing the audit clauses identified in FAR 4.702, subject to longer contract-specific periods and exceptions.",
            evidence_fields=["contract_clause", "record_category", "record_date", "final_payment_date", "retention_until", "storage_medium", "transfer_audit_trail", "legal_hold"],
            recommended_action="Calculate retention from the applicable FAR and contract terms, preserve the longest applicable period, and maintain integrity evidence for electronic transfers.",
            effective_from="2026-03-13",
        ),
    ]
    return [
        _base_record(retrieved_at=retrieved[spec["source_url"]], **spec)
        for spec in specs
    ]


def main() -> None:
    docs, retrieved = _load_contents()
    _verify_sources(docs)
    records = _existing_records(retrieved) + _new_records(retrieved)
    chunk_ids = [record["chunk_id"] for record in records]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise SystemExit("Duplicate chunk_id generated")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    manifest = {
        "batch_id": "fraud-policy-batch-01",
        "generated_from": [str(path.relative_to(ROOT)) for path in CONTENTS_FILES],
        "output": str(OUTPUT_PATH.relative_to(ROOT)),
        "record_count": len(records),
        "review_status": "reviewed",
        "authority_counts": {
            level: sum(record["authority_level"] == level for record in records)
            for level in sorted({record["authority_level"] for record in records})
        },
        "source_count": len({record["source_url"] for record in records}),
        "acceptance_gate": {
            "contents_extracted": True,
            "expected_phrases_verified": True,
            "binding_status_recorded": True,
            "applicability_recorded": True,
            "review_evidence_not_fraud_determination": True,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(records)} reviewed chunks to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
