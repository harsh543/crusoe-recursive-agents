"""results.json -> a single static report.html. Every number is read from the file, none are typed in."""
import html
import json
from pathlib import Path


def _f(v, pct=False, money=False, secs=False):
    if v is None:
        return "n/a"
    if pct:
        return f"{v * 100:.0f}%"
    if money:
        return f"${v:.4f}"
    return f"{v:.1f}s" if secs else str(v)


def render(results_path: Path) -> Path:
    r = json.loads(Path(results_path).read_text())
    cols = [("false_completion_rate", "False completion", dict(pct=True)),
            ("correct_disposition_rate", "Correct disposition", dict(pct=True)),
            ("recovery_rate", "Recovery", dict(pct=True)),
            ("unnecessary_escalation_rate", "Unnecessary escalation", dict(pct=True)),
            ("attribution_accuracy", "Attribution (exact)", dict(pct=True)),
            ("cost_per_correct_usd", "Cost / correct case", dict(money=True)),
            ("latency_p50_s", "p50 latency", dict(secs=True)), ("latency_p95_s", "p95 latency", dict(secs=True))]
    head = "".join(f"<th>{c[1]}</th>" for c in cols)
    body = "".join(
        f"<tr><td><b>{k}</b> {html.escape(v['name'])}<br><small>{v['runs']} runs, {v['claimed_completions']} claimed completions, "
        f"{v['errors']} crashed</small></td>" + "".join(f"<td>{_f(v[c[0]], **c[2])}</td>" for c in cols) + "</tr>"
        for k, v in r["summary"].items())
    rows = "".join(
        f"<tr class='{'ok' if x['oracle_complete'] else 'bad'}'><td>{x['config']}</td><td>{x['case']}</td><td>{x['fault']}</td>"
        f"<td>{x['expected']}</td><td>{x['outcome']}</td><td>{'yes' if x['claimed_complete'] else 'no'}</td>"
        f"<td>{'correct' if x['oracle_complete'] else 'WRONG'}</td><td>{_f(x['cost_usd'], money=True)}</td>"
        f"<td>{html.escape('; '.join(x['refusals'])[:160])}</td></tr>" for x in r["rows"])
    page = f"""<!doctype html><meta charset=utf-8><title>Casefile results</title>
<style>body{{font:14px system-ui;margin:24px;color:#111}}table{{border-collapse:collapse;margin:12px 0}}
td,th{{border:1px solid #ccc;padding:6px 10px;text-align:left}}th{{background:#f3f3f3}}.bad{{background:#fde8e8}}.ok{{background:#eefaf0}}</style>
<h1>Casefile: measured results ({html.escape(r['split'])} split)</h1>
<p>Models: {html.escape(json.dumps(r['models']))}. All values computed from <code>results.json</code>; synthetic cases only.</p>
<table><tr><th>Configuration</th>{head}</tr>{body}</table>
<h2>Every run</h2><table><tr><th>Cfg</th><th>Case</th><th>Fault</th><th>Oracle expects</th><th>Outcome</th><th>Claimed done</th>
<th>Verdict</th><th>Cost</th><th>Gate refusals</th></tr>{rows}</table>"""
    out = Path(results_path).with_name("report.html")
    out.write_text(page)
    return out
