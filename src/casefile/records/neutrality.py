"""Neutral-language lint: wrongdoing vocabulary may appear only inside double-quoted (attributed) text."""
import re

BANNED = ["fraud", "fraudulent", "defraud", "corrupt", "corruption", "criminal", "crime", "guilty", "illegal",
          "unlawful", "embezzle", "embezzlement", "bribe", "bribery", "kickback", "scam", "steal", "stole",
          "theft", "misconduct", "collusion", "cover-up"]
_QUOTED = re.compile(r'"[^"]*"|“[^”]*”')
_WORDS = re.compile(r"\b(" + "|".join(sorted(map(re.escape, BANNED), key=len, reverse=True)) + r")\b", re.I)


def lint(text: str) -> list[str]:
    return sorted({m.group(1).lower() for m in _WORDS.finditer(_QUOTED.sub(" ", text))})
