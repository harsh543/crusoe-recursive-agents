"""The four PR-gate checks: PCI exposure, data classification, API-contract changes, regulatory surface.
Pure, deterministic, read-only. Detected card numbers are never echoed in full."""
import re
from dataclasses import dataclass, field

from ..harness.masking import _luhn
from ..harness.state import FIELD_CLASSES, DataClass

NOTICE = "Informational only; not legal advice. Confirm with compliance counsel before relying on it."

# ---------------------------------------------------------------- PCI exposure
TEST_PANS = {"4111111111111111", "4242424242424242", "5555555555554444", "5500000000000004", "378282246310005", "6011111111111117",
             "3530111333300000", "4000056655665556", "2223003122003222", "5105105105105100", "4012888888881881"}
_PAN = re.compile(r"(?<![\w%])(?:\d[ -]?){12,18}\d(?!\w)")
_CVV = re.compile(r"(?i)(?<![A-Za-z0-9])(cvv2?|cvc2?|cid|card[_ ]verification(?:[_ ]value|[_ ]code)?)(?![A-Za-z0-9])\s*[:=]\s*['\"]?\d{3,4}\b")
_TRACK = re.compile(r"%B\d{13,19}\^[^^]{2,26}\^\d{4}|;\d{13,19}=\d{4}")
_CARD_FIELD = re.compile(r"(?i)(?<![A-Za-z0-9])(card[_-]?number|card_no|cardnumber|pan|primary_account_number|cc_number|credit_card(?:_number)?)(?![A-Za-z0-9])")
_LOGGING = re.compile(r"(?i)\b(logger|logging|log|console\.log|print|printf|println)\b\s*[.(]")
_DIFF = re.compile(r"(?m)^(diff --git |@@ |\+\+\+ )")


@dataclass(frozen=True)
class PciFinding:
    kind: str
    severity: str
    line: int
    excerpt: str
    blocking: bool


@dataclass
class PciReport:
    findings: list = field(default_factory=list)

    @property
    def blocking(self) -> bool:
        return any(f.blocking for f in self.findings)


def _lines(text: str):
    """(line number, text) pairs. In a unified diff only added lines count, so removing card fields passes."""
    if _DIFF.search(text):
        return [(i, l[1:]) for i, l in enumerate(text.splitlines(), 1) if l.startswith("+") and not l.startswith("+++")]
    return list(enumerate(text.splitlines(), 1))


def _mask(m: re.Match) -> str:
    digits = re.sub(r"\D", "", m.group(0))
    return "*" * (len(digits) - 4) + digits[-4:]


def check_pci_exposure(text: str) -> PciReport:
    out, seen = [], set()

    def add(kind, sev, ln, excerpt, blocking):
        excerpt = _PAN.sub(lambda mm: _mask(mm) if _luhn(re.sub(r"\D", "", mm.group(0))) else mm.group(0), excerpt)
        if (kind, ln) not in seen:
            seen.add((kind, ln))
            out.append(PciFinding(kind, sev, ln, excerpt.strip()[:160], blocking))

    for ln, line in _lines(text):
        for m in _PAN.finditer(line):
            digits = re.sub(r"\D", "", m.group(0))
            if 13 <= len(digits) <= 19 and _luhn(digits):
                excerpt = _PAN.sub(lambda mm: _mask(mm) if _luhn(re.sub(r"\D", "", mm.group(0))) else mm.group(0), line)
                if digits in TEST_PANS:
                    add("test_pan", "low", ln, excerpt, False)
                else:
                    add("pan", "critical", ln, excerpt, True)
        if _CVV.search(line):
            add("cvv", "critical", ln, "[sensitive authentication data redacted]", True)
        if _TRACK.search(line):
            add("track_data", "critical", ln, "[track data redacted]", True)
        if _CARD_FIELD.search(line):
            add("card_field", "high", ln, line, False)
            if _LOGGING.search(line):
                add("card_data_in_logs", "high", ln, line, False)
    return PciReport(out)


# ---------------------------------------------------------------- data classification
@dataclass(frozen=True)
class FieldClass:
    name: str
    data_class: str
    reason: str


_RULES = [
    ("credential", re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|private[_-]?key|authorization|bearer)")),
    ("payment", re.compile(r"(?i)(card[_-]?(number|no)|cardnumber|^pan$|cvv|cvc|expiry|exp[_-]?date|iban|routing[_-]?number|bank[_-]?account|account[_-]?number)")),
    ("pii", re.compile(r"(?i)(email|phone|ssn|social[_-]?security|dob|date[_-]?of[_-]?birth|address|first[_-]?name|last[_-]?name|full[_-]?name|^name$|ip[_-]?address)")),
    ("internal", re.compile(r"(?i)(_id$|^id$|tenant|policy|window_|alert_|^amount$|status|outcome|verdict|version|created|updated)")),
]


def _flatten(node, prefix=""):
    if isinstance(node, dict) and "properties" in node:
        for k, v in node["properties"].items():
            yield from _flatten(v, f"{prefix}.{k}" if prefix else k)
    elif prefix:
        yield prefix


def classify_fields(fields) -> list[FieldClass]:
    names = list(_flatten(fields)) if isinstance(fields, dict) else list(fields)
    out = []
    for name in names:
        leaf = name.split(".")[-1]
        known = FIELD_CLASSES.get(leaf)
        if known is not None:
            out.append(FieldClass(name, known.value, "known platform field"))
            continue
        for cls, rx in _RULES:
            if rx.search(leaf):
                out.append(FieldClass(name, cls, f"name matches {cls} pattern"))
                break
        else:
            out.append(FieldClass(name, "unclassified", "no rule matched; a data owner must classify it before merge"))
    return out


# ---------------------------------------------------------------- API-contract changes
@dataclass(frozen=True)
class Change:
    kind: str
    path: str
    breaking: bool
    detail: str = ""


def diff_contract(old: dict, new: dict, path: str = "") -> list[Change]:
    ch = []
    p = lambda k: f"{path}.{k}" if path else k
    if "type" in old and "type" in new and old["type"] != new["type"]:
        ch.append(Change("type_changed", path or "$", True, f"{old['type']} -> {new['type']}"))
    if "const" in old and "const" in new and old["const"] != new["const"]:
        ch.append(Change("const_changed", path or "$", True, f"{old['const']!r} -> {new['const']!r}"))
    if "enum" in old and "enum" in new:
        for v in sorted(map(str, set(old["enum"]) - set(new["enum"]))):
            ch.append(Change("enum_value_removed", path or "$", True, v))
        for v in sorted(map(str, set(new["enum"]) - set(old["enum"]))):
            ch.append(Change("enum_value_added", path or "$", False, v))
    if old.get("additionalProperties") is not False and new.get("additionalProperties") is False:
        ch.append(Change("additional_properties_restricted", path or "$", True))
    for r in sorted(set(new.get("required", [])) - set(old.get("required", []))):
        ch.append(Change("required_added", p(r), True))
    op, np_ = old.get("properties", {}), new.get("properties", {})
    for k in sorted(set(op) - set(np_)):
        ch.append(Change("property_removed", p(k), True))
    for k in sorted(set(np_) - set(op)):
        ch.append(Change("property_added", p(k), False))
    for k in sorted(set(op) & set(np_)):
        ch.extend(diff_contract(op[k], np_[k], p(k)))
    return ch


def diff_tool_specs(old: dict, new: dict) -> list[Change]:
    ch = []
    for name in sorted(set(old) - set(new)):
        ch.append(Change("tool_removed", name, True))
    for name in sorted(set(new) - set(old)):
        ch.append(Change("tool_added", name, False))
    for name in sorted(set(old) & set(new)):
        o, n = old[name], new[name]
        if o.get("access") != n.get("access"):
            ch.append(Change("access_class_changed", name, True, f"{o.get('access')} -> {n.get('access')}"))
        widened = sorted(set(n.get("roles", [])) - set(o.get("roles", [])))
        if widened:
            ch.append(Change("roles_widened", name, True, ", ".join(widened)))
        if o.get("version") != n.get("version"):
            ch.append(Change("version_changed", name, False, f"{o.get('version')} -> {n.get('version')}"))
    return ch


# ---------------------------------------------------------------- regulatory surface
@dataclass(frozen=True)
class Topic:
    topic: str
    why: str
    possible_regimes: list
    research_queries: list


@dataclass
class SurfaceReport:
    topics: list
    notice: str = NOTICE

    @property
    def needs_research(self) -> bool:
        return bool(self.topics)


_TOPICS = {
    "account_actions": (r"\b(freez\w*|account hold|block the account|lock\w* (the )?account|suspend\w* (the )?account|restrict\w* (the )?account|close (the )?account)\b",
                        ["consumer electronic-fund-transfer notice and error-resolution rules (e.g., Regulation E)", "account-agreement and adverse-action notice requirements"]),
    "money_movement": (r"\b(wire|transfer funds|send money|payouts?|ach|disburse\w*|remittance|refunds?)\b",
                       ["money-transmission licensing and payment-services rules", "NACHA operating rules for ACH", "OFAC sanctions screening"]),
    "card_data": (r"\b(card number|cardholder|cvv|payment card|card vault|pci|primary account number)\b",
                  ["PCI DSS (industry standard, contractual)", "card-network rules"]),
    "aml_reporting": (r"\b(suspicious activity|sar|aml|kyc|sanctions?|ofac|money laundering|know your customer)\b",
                      ["Bank Secrecy Act AML program and suspicious-activity reporting", "OFAC sanctions obligations", "customer due diligence rules"]),
    "credit_decisioning": (r"\b(credit decision|loans?|underwrit\w*|adverse action|credit score)\b",
                           ["Equal Credit Opportunity Act / Regulation B", "Fair Credit Reporting Act", "model risk management guidance"]),
    "personal_data": (r"\b(retain\w*|retention|customer emails?|pii|personal data|gdpr|ccpa|dsar)\b",
                      ["GLBA privacy and safeguards rules", "GDPR / CCPA-CPRA where applicable", "records-retention schedules"]),
    "automated_decisions": (r"\b(model score|automated decision\w*|llm decides|agent decides)\b",
                            ["EU AI Act obligations for high-risk uses", "model risk management (e.g., SR 11-7)", "explainability and adverse-action reasons"]),
}
_PATH_HINTS = {"card_data": ("card", "pci"), "money_movement": ("payout", "wire", "ach"), "aml_reporting": ("aml", "kyc", "sanction")}


def regulatory_surface(summary: str, paths: list[str]) -> SurfaceReport:
    topics = []
    for topic, (rx, regimes) in _TOPICS.items():
        m = re.search(rx, summary, re.I)
        hit_path = next((p for p in paths if any(h in p.lower() for h in _PATH_HINTS.get(topic, ()))), None)
        if m or hit_path:
            why = f"change summary mentions '{m.group(0)}'" if m else f"touched path '{hit_path}'"
            topics.append(Topic(topic, why, regimes, [f"{r} requirements summary" for r in regimes[:2]]))
    return SurfaceReport(topics)
