"""Builds site/index.html from history (today + last 7 days)."""
import datetime as dt
import json
from pathlib import Path

TEMPLATE = Path(__file__).with_name("template.html")


def write(out: Path, history: dict, run: dict, cfg: dict):
    data = {
        "today": run["date"],
        "name": cfg.get("your_name", ""),
        "days": history["shortlist"],
        "run": run,
        "roles": {k: v["label"] for k, v in cfg["search"]["roles"].items()},
        "generated": dt.datetime.now().isoformat(timespec="minutes"),
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text().replace("__DATA__", payload)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
