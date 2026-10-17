#!/bin/zsh
# Prompt for the Supabase secret / service_role key (input hidden) and write it into .env.local.
# The key never appears on screen, in shell history, or in any output.
set -e
ENV_FILE="$(cd "$(dirname "$0")/.." && pwd)/.env.local"
printf 'Paste the Supabase secret key (sb_secret_... or service_role eyJ...), then press Enter: '
read -rs KEY
echo
KEY="${KEY//[[:space:]]/}"
if [[ -z "$KEY" ]]; then echo "Nothing pasted; .env.local unchanged."; exit 1; fi
KEY="$KEY" python3 -I - "$ENV_FILE" <<'EOF'
import os, sys, pathlib
p = pathlib.Path(sys.argv[1]); key = os.environ["KEY"]
lines = p.read_text().splitlines()
lines = [l for l in lines if not l.startswith("SUPABASE_SERVICE_ROLE_KEY=")] + [f"SUPABASE_SERVICE_ROLE_KEY={key}"]
p.write_text("\n".join(lines) + "\n")
kind = "legacy service_role JWT" if key.startswith("eyJ") else "sb_secret key" if key.startswith("sb_secret_") else "unrecognised format"
print(f"Saved to {p} (length {len(key)}, {kind}).")
EOF
unset KEY
