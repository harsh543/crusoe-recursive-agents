"""Role -> model resolution against GET /v1/models. Prices come from the API, not from memory."""
import re

from .cost import Price

LIGHTNING = "nvidia/Nemotron-3.5-Lightning-30B-A3B"
NANO = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
SUPER_120B = "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B"
SUPER_VL = "nvidia/NVIDIA-Nemotron-3.5-Super-VL"      # confirmed present in this project's /v1/models


def find_id(available: list[str], wanted: str) -> str | None:
    return next((i for i in available if i.lower() == wanted.lower()), None)


def resolve_models(available: list[str], small: str = LIGHTNING, big: str = SUPER_VL) -> dict[str, str]:
    """Pick real IDs from /v1/models. Never invents an ID the endpoint does not list."""
    small_id, big_id = find_id(available, small), find_id(available, big)
    missing = [n for n, v in (("small", small_id), ("big", big_id)) if not v]
    if missing:
        raise RuntimeError(f"not in /v1/models: {missing}. Nemotron available: "
                           f"{[i for i in available if 'nemotron' in i.lower()]}")
    return {"planner": big_id, "investigator": small_id, "attributor": small_id,
            "attributor_escalate": big_id, "critic": small_id,
            "intake": big_id, "records_investigator": small_id}


def prices_from_records(records: list[dict]) -> dict[str, Price]:
    """USD per 1M tokens as reported by /v1/models (prompt, input_cache_reads, completion)."""
    out = {}
    for m in records:
        p = m.get("pricing") or {}
        try:
            out[m["id"]] = Price(float(p["prompt"]), float(p.get("input_cache_reads") or p["prompt"]),
                                 float(p["completion"]))
        except (KeyError, TypeError, ValueError):
            continue
    return out
