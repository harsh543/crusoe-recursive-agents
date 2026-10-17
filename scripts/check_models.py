"""Smoke test: key works, endpoint is right, our model roles exist, one call succeeds.

Usage: python scripts/check_models.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from crusoe_client import MODELS, Crusoe, reply_text  # noqa: E402

c = Crusoe()
records = {m["id"]: m for m in c.list_models()}
print(f"{len(records)} models available to this project\n")

print("Our roles:")
for role, mid in MODELS.items():
    m = records.get(mid)
    if not m:
        close = [i for i in records if i.lower() == mid.lower()]
        print(f"  MISSING  {role:9} {mid}" + (f"  (casing differs: {close[0]})" if close else ""))
        continue
    params = m.get("supported_parameters", [])
    print(f"  ok       {role:9} {mid}  ctx={m.get('context_length')}  tools={'tools' in params}")

print("\nAll IDs:")
for mid in sorted(records):
    print("  ", mid)

cheap = MODELS["cheap"]
if cheap in records:
    resp = c.chat(cheap, [{"role": "user", "content": "Reply with exactly: pong"}], max_tokens=1024)
    text, _ = reply_text(resp)
    print(f"\nCall to {cheap}: {text!r} (finish_reason={resp.choices[0].finish_reason})")
