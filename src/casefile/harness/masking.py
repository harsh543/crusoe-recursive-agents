"""PII vault: emails, phone numbers and valid payment-card numbers become stable tokens before a prompt is built."""
import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<![\w$])(?:\+\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)")
_CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
_TOKEN = re.compile(r"\b(EMAIL|PHONE|CARD)_\d+\b")


def _luhn(num: str) -> bool:
    d = [int(c) for c in re.sub(r"\D", "", num)]
    if not 13 <= len(d) <= 19:
        return False
    total = sum(x if i % 2 == 0 else (x * 2 - 9 if x * 2 > 9 else x * 2) for i, x in enumerate(reversed(d)))
    return total % 10 == 0


class PiiVault:
    def __init__(self):
        self._fwd: dict[str, str] = {}
        self._rev: dict[str, str] = {}
        self._n = {"EMAIL": 0, "PHONE": 0, "CARD": 0}
        self.substitutions = 0                      # running count of values replaced by tokens

    def _token(self, kind: str, value: str) -> str:
        if value not in self._fwd:
            self._n[kind] += 1
            tok = f"{kind}_{self._n[kind]}"
            self._fwd[value], self._rev[tok] = tok, value
        self.substitutions += 1
        return self._fwd[value]

    def mask(self, text: str) -> str:
        text = _CARD.sub(lambda m: self._token("CARD", m.group(0)) if _luhn(m.group(0)) else m.group(0), text)
        text = _EMAIL.sub(lambda m: self._token("EMAIL", m.group(0)), text)
        return _PHONE.sub(lambda m: self._token("PHONE", m.group(0)), text)

    def unmask(self, text: str) -> str:
        return _TOKEN.sub(lambda m: self._rev.get(m.group(0), m.group(0)), text)
