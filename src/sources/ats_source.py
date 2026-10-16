"""Read public career boards (Greenhouse, Lever, Ashby). No login, no scraping."""
import datetime as dt
import logging

import requests

from ..models import Job, clean_text

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "job-radar/1.0 (personal job search digest)"}
INDIA_WORDS = ("india", "bangalore", "bengaluru", "chennai", "hyderabad", "pune", "mumbai",
               "gurgaon", "gurugram", "noida", "delhi", "coimbatore", "kochi")


def _get_json(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def _greenhouse(name, slug):
    data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    for j in data.get("jobs", []):
        loc = clean_text((j.get("location") or {}).get("name"))
        yield Job(title=j.get("title"), company=name, location=loc, url=j.get("absolute_url", ""),
                  description=j.get("content"), posted=j.get("updated_at", ""),
                  source="Career page", remote="remote" in loc.lower())


def _lever(name, slug):
    data = _get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    for j in data:
        cats = j.get("categories") or {}
        loc = clean_text(cats.get("allLocations") or cats.get("location"))
        desc = [j.get("descriptionPlain") or j.get("description") or ""]
        for block in j.get("lists") or []:
            desc.append(f"{block.get('text', '')}\n{block.get('content', '')}")
        sal = j.get("salaryRange") or {}
        salary = (f"{sal.get('min')}-{sal.get('max')} {sal.get('currency', '')} {sal.get('interval', '')}"
                  if sal.get("min") else "")
        created = j.get("createdAt")
        posted = (dt.datetime.fromtimestamp(created / 1000, dt.timezone.utc).isoformat()
                  if isinstance(created, (int, float)) else "")
        workplace = j.get("workplaceType") or ""
        yield Job(title=j.get("text"), company=name, location=loc, url=j.get("hostedUrl", ""),
                  description="\n".join(desc), salary_text=salary, posted=posted,
                  source="Career page", workplace=workplace,
                  remote=workplace == "remote" or "remote" in loc.lower())


def _ashby(name, slug):
    data = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
    for j in data.get("jobs", []):
        locs = [j.get("location") or ""] + [
            clean_text(s.get("location")) for s in j.get("secondaryLocations") or []]
        loc = ", ".join(l for l in locs if l)
        comp = j.get("compensation") or {}
        salary = comp.get("compensationTierSummary") or comp.get("scrapeableCompensationSalarySummary") or ""
        workplace = j.get("workplaceType") or ""
        yield Job(title=j.get("title"), company=name, location=loc, url=j.get("jobUrl", ""),
                  description=j.get("descriptionPlain") or j.get("descriptionHtml"),
                  salary_text=salary, posted=j.get("publishedAt", ""), source="Career page",
                  workplace=workplace, remote=bool(j.get("isRemote")) or workplace.lower() == "remote")


FETCHERS = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby}


def fetch(companies: dict):
    """Returns (jobs, errors, board_counts). board_counts feeds the hiring-trend view."""
    jobs, errors, counts = [], [], {}
    for platform, entries in (companies or {}).items():
        fetcher = FETCHERS.get(platform)
        if not fetcher:
            continue
        for entry in entries or []:
            name, slug = entry["name"], entry["slug"]
            try:
                found = list(fetcher(name, slug))
            except Exception as exc:
                errors.append(f"{name} career page ({platform}/{slug}) failed: {exc}")
                continue
            india = sum(1 for j in found if any(w in j.location.lower() for w in INDIA_WORDS))
            counts[name] = {"total": len(found), "india": india}
            jobs.extend(found)
            log.info("%s: %d open roles (%d India)", name, len(found), india)
    return jobs, errors, counts
