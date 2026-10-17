"""Failure attribution: closed schema, scored by exact match (never substring)."""
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Category(StrEnum):
    SPECIFICATION = "specification"
    INTER_AGENT_MISALIGNMENT = "inter_agent_misalignment"
    TASK_VERIFICATION = "task_verification"


class Attribution(BaseModel):
    model_config = ConfigDict(frozen=True)
    agent: Literal["planner", "investigator", "verifier", "gate"]
    step: str
    category: Category


def score_attribution(pred: Attribution, truth: Attribution) -> bool:
    return pred.agent == truth.agent and pred.step == truth.step


def attribution_accuracy(preds, truths) -> float:
    if not preds or len(preds) != len(truths):
        raise ValueError("need equal-length, non-empty lists")
    return sum(score_attribution(p, t) for p, t in zip(preds, truths)) / len(preds)
