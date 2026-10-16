"""Check which career-board slugs in companies.yaml work.  Run: python -m src.check_companies"""
from pathlib import Path

import yaml

from .sources.ats_source import FETCHERS, INDIA_WORDS

ROOT = Path(__file__).resolve().parent.parent

companies = yaml.safe_load((ROOT / "companies.yaml").read_text()) or {}
for platform, entries in companies.items():
    for e in entries or []:
        try:
            jobs = list(FETCHERS[platform](e["name"], e["slug"]))
            india = sum(1 for j in jobs if any(w in j.location.lower() for w in INDIA_WORDS))
            print(f"OK    {platform:10} {e['slug']:20} {len(jobs):4} roles, {india} in India")
        except Exception as exc:
            print(f"FAIL  {platform:10} {e['slug']:20} {exc}")
