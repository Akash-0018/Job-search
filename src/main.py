"""Daily job radar: collect -> filter -> score -> track trends -> build the page.

Run:  python -m src.main            (real run, needs secrets)
      python -m src.main --mock --no-llm   (offline test with fake jobs)
"""
import argparse
import datetime as dt
import logging
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import filters, render, trends
from .scorer import Scorer
from .sources import ats_source, jobspy_source, mock_source

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("job-radar")


def collect(cfg, mock, history, today_s, first_run):
    jobs, errors, source_stats = [], [], {}
    if mock:
        jobs = mock_source.fetch()
        source_stats["Sample data"] = {"jobs": len(jobs)}
        return jobs, errors, source_stats
    src = cfg["sources"]
    if src["job_sites"].get("enabled"):
        j, e, s = jobspy_source.fetch(src["job_sites"], first_run)
        jobs += j; errors += e; source_stats.update(s)
    if src["career_boards"].get("enabled"):
        companies = yaml.safe_load((ROOT / src["career_boards"]["companies_file"]).read_text()) or {}
        j, e, counts = ats_source.fetch(companies)
        jobs += j; errors += e
        source_stats["Career pages"] = {"jobs": len(j), "companies": len(counts)}
        trends.record_board_counts(history, counts, today_s)
    return jobs, errors, source_stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="use fake jobs, no network")
    ap.add_argument("--no-llm", action="store_true", help="skip AI scoring")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    tz = ZoneInfo(cfg.get("timezone", "Asia/Kolkata"))
    now = dt.datetime.now(tz)
    today, today_s = now.date(), now.date().isoformat()
    profile = (ROOT / cfg["profile_file"]).read_text()
    hist_path = ROOT / "data" / ("history.mock.json" if args.mock else "history.json")
    history = trends.load(hist_path)
    first_run = not history["seen"]

    # 1. Collect
    raw, errors, source_stats = collect(cfg, args.mock, history, today_s, first_run)

    # 2. De-duplicate (same company + title + city across sources), prefer ones with salary
    unique = {}
    for j in raw:
        cur = unique.get(j.id)
        if cur is None or (not cur.salary_text and j.salary_text):
            unique[j.id] = j
    new_jobs = [j for j in unique.values() if j.id not in history["seen"]]
    trends.record_seen(history, unique.values(), today_s)

    # 3. Hard filters
    lookback = cfg["search"]["first_run_lookback_days"] if first_run else cfg["search"]["max_age_days"]
    reasons, passed = Counter(), []
    for j in new_jobs:
        why = filters.check(j, cfg, today, lookback)
        if why:
            reasons[why] += 1
        else:
            j.prescore = filters.prescore(j, cfg["profile_keywords"])
            passed.append(j)

    # 4. AI scoring on the best candidates
    passed.sort(key=lambda j: j.prescore, reverse=True)
    cap = cfg["scoring"]["max_jobs_per_day"]
    to_score, overflow = passed[:cap], passed[cap:]
    if overflow:
        reasons["over the daily AI scoring cap (lower pre-rank)"] += len(overflow)
    scorer = Scorer(cfg, profile, disabled=args.no_llm)
    errors += scorer.errors
    sal = cfg["search"]["salary"]
    shortlist = []
    for j in to_score:
        fit = scorer.score(j)
        j.fit = fit
        if fit.get("role_type") in ("ai_engineer", "python_backend", "fde"):
            j.role_bucket = fit["role_type"]
        if fit.get("experience_ok") is False:
            reasons["AI: experience level doesn't fit"] += 1; continue
        if j.remote and fit.get("remote_open_to_india") is False:
            reasons["AI: remote but not open to India"] += 1; continue
        if j.salary_min_lpa is None and sal["undisclosed"] == "estimate" and scorer.uses_ai:
            est = fit.get("salary_estimate_lpa") or {}
            if not est.get("min"):
                reasons["salary unknown and not estimable"] += 1; continue
            if float(est["min"]) < sal["min_lpa"]:
                reasons[f"estimated salary below {sal['min_lpa']} LPA"] += 1; continue
            j.salary_min_lpa, j.salary_max_lpa = float(est["min"]), float(est.get("max") or est["min"])
            j.salary_estimated = True
        if int(fit.get("fit_score", 0)) < cfg["scoring"]["min_fit_score"]:
            reasons["fit score too low"] += 1; continue
        j.first_seen = today_s
        shortlist.append(j)

    # 5. Hiring trends for shortlisted companies
    for j in shortlist:
        j.trend = trends.company_trend(history, j.company, today)

    # 6. Save: merge with anything already found earlier today (manual re-runs)
    existing = {d["id"]: d for d in history["shortlist"].get(today_s, [])}
    for j in shortlist:
        existing[j.id] = j.to_page_dict()
    history["shortlist"][today_s] = sorted(existing.values(),
                                           key=lambda d: d["fit"].get("fit_score", 0), reverse=True)
    run = {
        "date": today_s,
        "time": now.strftime("%H:%M"),
        "collected": len(raw),
        "unique": len(unique),
        "new": len(new_jobs),
        "passed_filters": len(passed),
        "scored": len(to_score),
        "shortlisted": len(shortlist),
        "ai_scoring": scorer.uses_ai,
        "sources": source_stats,
        "skipped": dict(reasons.most_common()),
        "errors": errors,
        "tracking_days": trends.tracking_days(history, today),
        "mock": args.mock,
    }
    history["runs"].append(run)
    trends.save(hist_path, history, today)

    out = ROOT / "site" / "index.html"
    render.write(out, history, run, cfg)
    log.info("Done: %d new, %d passed filters, %d shortlisted. Page: %s",
             len(new_jobs), len(passed), len(shortlist), out)
    for e in errors:
        log.warning(e)


if __name__ == "__main__":
    main()
