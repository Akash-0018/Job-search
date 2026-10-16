"""Free job collection with JobSpy (github.com/speedyapply/JobSpy).

Runs each search on each site separately, so one blocked site (LinkedIn rate
limits now and then) doesn't stop the others.
"""
import logging
import math
import time
from collections import defaultdict

from ..models import Job

log = logging.getLogger(__name__)
SITE_NAMES = {"linkedin": "LinkedIn", "indeed": "Indeed", "naukri": "Naukri",
              "glassdoor": "Glassdoor", "google": "Google Jobs"}


def _val(row, key):
    v = row.get(key)
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, str) and v.strip().lower() in ("", "nan", "none"):
        return None
    return v


def _salary_text(row) -> str:
    lo, hi = _val(row, "min_amount"), _val(row, "max_amount")
    if lo is None and hi is None:
        return ""
    cur = _val(row, "currency") or "INR"
    interval = _val(row, "interval") or "yearly"
    lo = lo if lo is not None else hi
    hi = hi if hi is not None else lo
    return f"{float(lo):.0f}-{float(hi):.0f} {cur} {interval}"


def row_to_job(row: dict, site: str):
    title, url = _val(row, "title"), _val(row, "job_url")
    if not title or not url:
        return None
    wfh = str(_val(row, "work_from_home_type") or "")
    remote = bool(_val(row, "is_remote")) or "remote" in wfh.lower()
    return Job(
        title=title,
        company=_val(row, "company") or "",
        location=_val(row, "location") or "",
        url=str(url),
        description=_val(row, "description") or "",
        salary_text=_salary_text(row),
        experience_text=_val(row, "experience_range") or "",
        posted=str(_val(row, "date_posted") or ""),
        source=SITE_NAMES.get(site, site.title()),
        remote=remote,
        workplace=wfh,
    )


def fetch(cfg: dict, first_run: bool):
    """Returns (jobs, errors, stats)."""
    try:
        from jobspy import scrape_jobs
    except ImportError:
        return [], ["Job sites skipped: python-jobspy is not installed."], {}

    jobs, stats = [], defaultdict(lambda: {"jobs": 0, "searches": 0, "failed": 0})
    failures = defaultdict(list)
    hours = cfg.get("first_run_hours_old", 72) if first_run else cfg.get("hours_old", 24)

    for search in cfg.get("searches", []):
        for site in cfg.get("sites", []):
            label = SITE_NAMES.get(site, site)
            stats[label]["searches"] += 1
            try:
                df = scrape_jobs(
                    site_name=[site],
                    search_term=search["term"],
                    location=search.get("location", "India"),
                    is_remote=bool(search.get("remote", False)),
                    results_wanted=cfg.get("results_per_search", 20),
                    hours_old=hours,
                    country_indeed="India",
                    fetch_description=cfg.get("fetch_description", True),
                    verbose=0,
                )
                count = 0
                for row in df.to_dict("records"):
                    job = row_to_job(row, site)
                    if job:
                        jobs.append(job)
                        count += 1
                stats[label]["jobs"] += count
                log.info("%s / %s / %s: %d jobs", label, search["term"],
                         search.get("location", "India"), count)
            except Exception as exc:
                stats[label]["failed"] += 1
                failures[label].append(str(exc)[:160])
                log.warning("%s search '%s' failed: %s", label, search["term"], exc)
            time.sleep(cfg.get("delay_seconds", 4))

    errors = []
    for label, s in stats.items():
        # JobSpy logs most site errors itself and returns an empty result,
        # so "no jobs from any search" is the reliable sign of a block.
        if s["jobs"] == 0 and label not in failures:
            errors.append(f"{label} returned no jobs from {s['searches']} searches today. "
                          "It may be blocking automated requests; it usually recovers in a day or two.")
    for label, msgs in failures.items():
        s = stats[label]
        if s["failed"] == s["searches"]:
            errors.append(f"{label}: all {s['searches']} searches failed today "
                          f"(often a temporary block). First error: {msgs[0]}")
        elif s["failed"] >= max(2, s["searches"] // 2):
            errors.append(f"{label}: {s['failed']} of {s['searches']} searches failed, "
                          "so some jobs may be missing today.")
    return jobs, errors, dict(stats)
