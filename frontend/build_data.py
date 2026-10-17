"""Bundle real run artifacts into frontend/data.js (no secrets: Supabase is queried locally for counts only).
   python frontend/build_data.py"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from casefile.store import Store  # noqa: E402

TITLES = {"dhs_ad_campaign": "DHS advertising campaign", "fat_leonard": "Fat Leonard / Navy contracts", "duke_cunningham": "Cunningham earmarks",
          "mississippi_tanf": "Mississippi TANF", "martin_kao": "Navatek / Kao"}
store = Store()
cases = {}
for d in sorted((ROOT / "runs").glob("casefile-*/result.json")):          # later runs overwrite earlier ones
    r = json.loads(d.read_text())
    if r.get("mode") != "live" or r["case"] not in TITLES or not r["claims"] or "trail" not in r["claims"][0]:
        continue
    r["title"], r["run_dir"] = TITLES[r["case"]], d.parent.name
    r["recorded_at"] = d.parent.name.removeprefix("casefile-")[:15]
    if store.remote and r.get("case_uuid"):
        cu = r["case_uuid"]
        r["supabase"] = {"claims": len(store.select("claims", case_id=cu)), "events": len(store.select("events", case_id=cu)),
                         "dispositions": len(store.select("dispositions", case_id=cu)),
                         "grounding_requests": len(store.select("grounding_requests", case_id=cu))}
    r.pop("run_id", None)
    r["case_uuid"] = (r.get("case_uuid") or "")[:8]
    cases[r["case"]] = r
nplus = None
for d in sorted((ROOT / "runs").glob("nplus1-*/result.json")):
    nplus = json.loads(d.read_text())
data = {"cases": list(cases.values()), "n_plus_1": nplus}
(ROOT / "frontend" / "data.js").write_text("window.CASEFILE_DATA = " + json.dumps(data, default=str) + ";\n")
print("cases:", [c["case"] for c in data["cases"]], "| n_plus_1:", bool(nplus))
