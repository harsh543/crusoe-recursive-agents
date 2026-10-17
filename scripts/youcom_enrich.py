#!/usr/bin/env python3
"""Query You.com Web Search, Contents, Research, and Finance Research APIs.

Saved responses are wrapped with request provenance so they can be reviewed,
transformed, and indexed without losing the retrieval context. The API key is
read from YDC_API_KEY, .env.youcom, or .env and is never written to output.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
ENDPOINTS = {
    "search": "https://ydc-index.io/v1/search",
    "contents": "https://ydc-index.io/v1/contents",
    "research": "https://api.you.com/v1/research",
    "finance": "https://api.you.com/v1/finance_research",
}
USER_AGENT = "SKILL/(@youdotcom-oss/agent-skills nemotron-fraud-enrichment)"
ENV_LINE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


class YouComError(RuntimeError):
    """A safe-to-display You.com request error."""


def _read_env_value(path: Path, key: str) -> str | None:
    if not path.is_file():
        return None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or not ENV_LINE.match(line):
            continue
        name, value = line.split("=", 1)
        if name != key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        return value or None
    return None


def get_api_key(env_file: Path | None) -> str:
    process_value = os.environ.get("YDC_API_KEY", "").strip()
    if process_value:
        return process_value

    candidates = [env_file] if env_file else [ROOT / ".env.youcom", ROOT / ".env"]
    for candidate in candidates:
        if candidate is None:
            continue
        resolved = candidate if candidate.is_absolute() else ROOT / candidate
        value = _read_env_value(resolved, "YDC_API_KEY")
        if value:
            return value

    raise YouComError(
        "YDC_API_KEY is missing. Paste it into the gitignored .env.youcom file "
        "or export it in the current shell. Do not paste the key into chat or a committed file."
    )


def load_schema(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    resolved = path if path.is_absolute() else ROOT / path
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise YouComError(f"Could not read output schema {resolved}: {exc}") from exc
    if not isinstance(value, dict):
        raise YouComError(f"Output schema {resolved} must contain a JSON object.")
    return value


def post_json(endpoint: str, payload: dict[str, Any], api_key: str, timeout: int) -> Any:
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        hint = " Check the key and account access."
        if exc.code == 402:
            hint = " The request requires available You.com credits or supported payment handling."
        raise YouComError(f"You.com returned HTTP {exc.code}.{hint} Response: {detail}") from None
    except URLError as exc:
        raise YouComError(f"Could not reach You.com: {exc.reason}") from None
    except TimeoutError:
        raise YouComError(
            f"The request exceeded {timeout}s. Increase --timeout for deep research."
        ) from None


def compact(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    cleaned = [value.strip() for value in values if value.strip()]
    return cleaned or None


def build_request(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    payload: dict[str, Any]

    if args.command == "search":
        payload = {"query": args.query, "count": args.count}
        if args.freshness:
            payload["freshness"] = args.freshness
        for field in ("include_domains", "exclude_domains", "boost_domains"):
            values = compact(getattr(args, field))
            if values:
                payload[field] = values
        if args.include_domains and args.exclude_domains:
            raise YouComError("Use either --include-domain or --exclude-domain, not both.")
        if args.extract == "highlights":
            payload["extraction"] = {"extraction_mode": "highlights"}
        elif args.extract == "full_page":
            payload["extraction"] = {
                "extraction_mode": "full_page",
                "full_page": {"extraction_formats": ["markdown"]},
            }
        return ENDPOINTS["search"], payload

    if args.command == "contents":
        if not 1 <= len(args.url) <= 10:
            raise YouComError("The Contents API accepts 1 to 10 URLs per request.")
        payload = {
            "urls": args.url,
            "formats": args.format or ["markdown"],
            "crawl_timeout": args.crawl_timeout,
        }
        if args.max_age is not None:
            payload["max_age"] = args.max_age
        return ENDPOINTS["contents"], payload

    payload = {"input": args.query, "research_effort": args.effort}
    schema = load_schema(args.output_schema)
    if schema is not None:
        if args.command == "research" and args.effort == "lite":
            raise YouComError("Research output_schema is not supported with --effort lite.")
        payload["output_schema"] = schema

    if args.command == "research":
        if args.include_domains and args.exclude_domains:
            raise YouComError("Use either --include-domain or --exclude-domain, not both.")
        source_control: dict[str, Any] = {}
        for field in ("include_domains", "exclude_domains", "boost_domains"):
            values = compact(getattr(args, field))
            if values:
                source_control[field] = values
        if args.freshness:
            source_control["freshness"] = args.freshness
        if source_control:
            payload["source_control"] = source_control
        return ENDPOINTS["research"], payload

    return ENDPOINTS["finance"], payload


def save_record(
    endpoint: str,
    payload: dict[str, Any],
    response: Any,
    output: Path | None,
) -> None:
    record = {
        "provenance": {
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "endpoint": endpoint,
            "request": payload,
        },
        "response": response,
    }
    rendered = json.dumps(record, indent=2, ensure_ascii=False) + "\n"
    if output is None:
        sys.stdout.write(rendered)
        return
    resolved = output if output.is_absolute() else ROOT / output
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(rendered, encoding="utf-8")
    print(f"Saved You.com response to {resolved}")


def add_domain_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--include-domain", dest="include_domains", action="append")
    parser.add_argument("--exclude-domain", dest="exclude_domains", action="append")
    parser.add_argument("--boost-domain", dest="boost_domains", action="append")


def add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", type=Path, help="Write the provenance envelope to this JSON file.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, help="Optional file containing YDC_API_KEY.")
    parser.add_argument("--timeout", type=int, default=360, help="HTTP timeout in seconds (default: 360).")
    parser.add_argument("--dry-run", action="store_true", help="Print the endpoint and body without calling the API.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search", help="Search the live web and optionally extract result content.")
    search.add_argument("--query", required=True)
    search.add_argument("--count", type=int, choices=range(1, 101), default=10, metavar="1..100")
    search.add_argument("--freshness", help="day, week, month, year, or YYYY-MM-DDtoYYYY-MM-DD")
    search.add_argument("--extract", choices=("none", "highlights", "full_page"), default="none")
    add_domain_options(search)
    add_output_options(search)

    contents = subparsers.add_parser("contents", help="Extract content from URLs already selected for review.")
    contents.add_argument("--url", action="append", required=True, help="URL to extract; repeat up to 10 times.")
    contents.add_argument("--format", action="append", choices=("markdown", "html", "metadata"))
    contents.add_argument("--crawl-timeout", type=int, choices=range(1, 61), default=20, metavar="1..60")
    contents.add_argument("--max-age", type=int, help="Maximum cache age, in seconds.")
    add_output_options(contents)

    research = subparsers.add_parser("research", help="Run citation-backed policy or regulatory research.")
    research.add_argument("--query", required=True)
    research.add_argument(
        "--effort",
        choices=("lite", "standard", "deep", "exhaustive"),
        default="standard",
    )
    research.add_argument("--freshness", help="Freshness constraint placed in source_control.")
    research.add_argument("--output-schema", type=Path)
    add_domain_options(research)
    add_output_options(research)

    finance = subparsers.add_parser("finance", help="Run finance-index research for a company or market.")
    finance.add_argument("--query", required=True)
    finance.add_argument("--effort", choices=("deep", "exhaustive"), default="deep")
    finance.add_argument("--output-schema", type=Path)
    add_output_options(finance)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        endpoint, payload = build_request(args)
        if args.dry_run:
            save_record(endpoint, payload, {"dry_run": True}, args.output)
            return 0
        api_key = get_api_key(args.env_file)
        response = post_json(endpoint, payload, api_key, args.timeout)
        save_record(endpoint, payload, response, args.output)
        return 0
    except YouComError as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
