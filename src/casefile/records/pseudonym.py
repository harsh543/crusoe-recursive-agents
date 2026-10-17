"""Presentation-layer pseudonyms. Processing uses raw text (quotes must match); output hides names by default."""
import re


class Pseudonymizer:
    def __init__(self, mapping: dict[str, str]):
        self.mapping = mapping
        self._pairs = sorted(mapping.items(), key=lambda kv: len(kv[0]), reverse=True)

    def apply(self, text: str) -> str:
        for real, alias in self._pairs:
            text = re.sub(re.escape(real), alias, text, flags=re.I)
        return text

    def leaks(self, text: str) -> list[str]:
        return [real for real, alias in self.mapping.items()
                if real != alias and re.search(re.escape(real), text, re.I)]
