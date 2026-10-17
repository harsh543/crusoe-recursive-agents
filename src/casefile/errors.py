"""Errors shared across layers (agents must be able to let these propagate without importing the harness)."""


class BudgetExceeded(Exception):
    """The per-case spend or token budget is used up."""


class ModelNotAllowed(Exception):
    """The requested model is not on the router's allowlist."""
