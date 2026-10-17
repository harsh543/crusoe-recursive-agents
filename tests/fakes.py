"""Scripted stand-in for the LLM layer: deterministic, no network."""


class FakeLLM:
    def __init__(self, scripts: dict[str, list]):
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.calls: list[tuple[str, list]] = []

    def call_json(self, role, messages, max_tokens=2048, model=None, schema=None):
        self.calls.append((role, messages))
        queue = self.scripts.get(role)
        if not queue:
            raise AssertionError(f"unscripted {role} call #{len([c for c in self.calls if c[0] == role])}")
        item = queue.pop(0)
        return item(messages) if callable(item) else item
