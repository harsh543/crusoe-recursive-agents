"""MCP server exposing the dataset fraud engine over stdio:  python -m casefile.fraud_engine_mcp [dataset.json]
Tools: inspect_device_sharing(account_id), velocity_outliers(window_minutes, threshold_count). The dataset is a JSON list of
events {account_id, device_fp, beneficiary, amount, ts}; without a path a small built-in synthetic ring is served."""
import json
import sys

from mcp.server.fastmcp import FastMCP

from .fraud_engine import FraudDataset

DEMO = [{"account_id": f"acct_{i}", "device_fp": "fp_ring", "beneficiary": "Velo Holdings", "amount": 500.0,
         "ts": "2026-09-20T10:0%d:00Z" % i} for i in range(4)] + [
    {"account_id": "acct_x", "device_fp": "fp_solo", "beneficiary": None, "amount": 20.0, "ts": "2026-09-20T11:00:00Z"}]


def build(events=None) -> FastMCP:
    ds = FraudDataset(events or DEMO)
    mcp = FastMCP("casefile-fraud-engine")

    @mcp.tool()
    def inspect_device_sharing(account_id: str) -> str:
        """Accounts that share a device fingerprint with this account, and how many of them pay the same beneficiary."""
        return json.dumps(ds.inspect_device_sharing(account_id))

    @mcp.tool()
    def velocity_outliers(window_minutes: int = 60, threshold_count: int = 5) -> str:
        """Accounts with at least threshold_count events inside window_minutes."""
        return json.dumps(ds.velocity_outliers(window_minutes, threshold_count))

    return mcp


if __name__ == "__main__":
    events = json.loads(open(sys.argv[1]).read()) if len(sys.argv) > 1 else None
    build(events).run()
