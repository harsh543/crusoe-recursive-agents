#!/usr/bin/env python3
"""Print You.com MCP headers without storing the API key in Codex config."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ENV_FILE = Path(__file__).resolve().parents[1] / ".env.youcom"


def _read_api_key() -> str:
    if value := os.environ.get("YDC_API_KEY", "").strip():
        return value

    try:
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError(f"cannot read {ENV_FILE}: {exc}") from exc

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        name, separator, value = line.partition("=")
        if separator and name.strip() == "YDC_API_KEY":
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            if value:
                return value
    raise RuntimeError(f"YDC_API_KEY is missing from the environment and {ENV_FILE}")


try:
    api_key = _read_api_key()
except RuntimeError as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(1) from exc

print(json.dumps({"Authorization": f"Bearer {api_key}"}))
