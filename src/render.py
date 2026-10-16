"""Builds one page per person (site/<id>/index.html) plus a landing page (site/index.html)."""
import datetime as dt
import html
import json
from pathlib import Path

TEMPLATE = Path(__file__).with_name("template.html")


def write(out: Path, history: dict, run: dict, cfg: dict, people=None):
    s = cfg["search"]
    places = []
    locs = " ".join(s.get("locations", []))
    if "bangalore" in locs or "bengaluru" in locs:
        places.append(["bangalore", "Bangalore"])
    if "chennai" in locs:
        places.append(["chennai", "Chennai"])
    if s.get("include_remote", True):
        places.append(["remote", "Remote"])
    data = {
        "id": cfg.get("id", "me"),
        "today": run["date"],
        "name": cfg.get("your_name", ""),
        "people": people or [],
        "places": places,
        "days": history["shortlist"],
        "run": run,
        "roles": {k: v["label"] for k, v in s["roles"].items()},
        "generated": dt.datetime.now().isoformat(timespec="minutes"),
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    page = TEMPLATE.read_text().replace("__DATA__", payload)
    page = page.replace("<title>Morning jobs</title>",
                        f"<title>{html.escape(cfg.get('your_name', ''))}: morning jobs</title>")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)


def write_index(out: Path, summaries, now):
    links = "\n".join(
        f'<a class="person" href="{html.escape(p["id"])}/"><span class="n">{html.escape(p["name"])}</span>'
        f'<span class="c">{p["today"]} {"role" if p["today"] == 1 else "roles"} today</span></a>'
        for p in summaries)
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Morning jobs</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🌼</text></svg>">
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,700&family=Public+Sans:wght@400;600&display=swap" rel="stylesheet">
<style>
:root {{ --bg:#EEF1F6; --surface:#fff; --ink:#18213A; --muted:#59627A; --line:#D6DCE7; --marigold:#D98E04; color-scheme: light; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#10151F; --surface:#171F2E; --ink:#E5E9F1; --muted:#9AA3B8; --line:#2A3447; --marigold:#F2B33D; color-scheme: dark; }} }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:400 16px/1.5 "Public Sans", system-ui, sans-serif; }}
.wrap {{ max-width:560px; margin:0 auto; padding:56px 20px; }}
h1 {{ font:700 clamp(2rem,6vw,3rem)/1.05 "Bricolage Grotesque", system-ui, sans-serif; margin:0 0 8px; }}
p {{ color:var(--muted); margin:0 0 28px; }}
.person {{ display:flex; justify-content:space-between; align-items:center; gap:12px; padding:20px 22px; margin-top:12px;
  background:var(--surface); border:1px solid var(--line); border-left:6px solid var(--marigold); border-radius:8px; text-decoration:none; color:inherit; }}
.person:hover {{ border-color:var(--marigold); }}
.n {{ font:700 1.4rem "Bricolage Grotesque", system-ui, sans-serif; }}
.c {{ color:var(--muted); font-size:.95rem; }}
</style></head>
<body><div class="wrap"><h1>Morning jobs</h1>
<p>Updated {now.strftime("%d %B, %H:%M")}. Pick a page.</p>
{links}
</div></body></html>"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
