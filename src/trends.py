"""Keeps run history in data/history.json and works out each company's hiring trend.

Trend signals:
  - postings seen from the company (any source) in the last 14 days vs the 14 before
  - for career-page companies, total open roles and India roles over time
The picture sharpens as history builds up; the first two weeks show "Tracking".
"""
import datetime as dt
import json
import re
from pathlib import Path

SEEN_KEEP_DAYS = 120
SHORTLIST_KEEP_DAYS = 7


def _key(company: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", company.lower()).strip()


def load(path: Path) -> dict:
    if path.exists():
        data = json.loads(path.read_text())
    else:
        data = {}
    data.setdefault("seen", {})
    data.setdefault("board_counts", {})
    data.setdefault("shortlist", {})
    data.setdefault("runs", [])
    data.setdefault("pending", {})
    return data


def save(path: Path, history: dict, today: dt.date):
    cutoff = (today - dt.timedelta(days=SEEN_KEEP_DAYS)).isoformat()
    history["seen"] = {k: v for k, v in history["seen"].items() if v["d"] >= cutoff}
    s_cut = (today - dt.timedelta(days=SHORTLIST_KEEP_DAYS - 1)).isoformat()
    history["shortlist"] = {d: v for d, v in history["shortlist"].items() if d >= s_cut}
    for company, days in history["board_counts"].items():
        history["board_counts"][company] = {d: c for d, c in days.items() if d >= cutoff}
    history["runs"] = history["runs"][-30:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, indent=1, ensure_ascii=False))


def record_seen(history: dict, jobs, today: str):
    for j in jobs:
        history["seen"].setdefault(j.id, {"c": _key(j.company), "t": j.title, "d": today, "s": j.source})


def record_board_counts(history: dict, counts: dict, today: str):
    for company, c in counts.items():
        history["board_counts"].setdefault(_key(company), {})[today] = c


def tracking_days(history: dict, today: dt.date) -> int:
    dates = [v["d"] for v in history["seen"].values()]
    if not dates:
        return 0
    return (today - dt.date.fromisoformat(min(dates))).days + 1


def company_trend(history: dict, company: str, today: dt.date) -> dict:
    key = _key(company)
    recent_cut = (today - dt.timedelta(days=14)).isoformat()
    prior_cut = (today - dt.timedelta(days=28)).isoformat()
    recent = prior = last30 = 0
    month_cut = (today - dt.timedelta(days=30)).isoformat()
    for v in history["seen"].values():
        if v["c"] != key:
            continue
        if v["d"] > recent_cut:
            recent += 1
        elif v["d"] > prior_cut:
            prior += 1
        if v["d"] > month_cut:
            last30 += 1

    days = tracking_days(history, today)
    if days < 14:
        label, tone = "Tracking", "neutral"
        detail = f"{last30} role{'s' if last30 != 1 else ''} seen in {days} day{'s' if days != 1 else ''} of tracking"
    else:
        if recent >= 3 and recent > prior * 1.3:
            label, tone = "Hiring more", "up"
        elif prior >= 2 and recent < prior * 0.7:
            label, tone = "Hiring less", "down"
        else:
            label, tone = "Steady", "neutral"
        detail = f"{recent} new roles in the last 14 days, {prior} in the 14 before"

    board = history["board_counts"].get(key, {})
    board_line = ""
    if board:
        dates = sorted(board)
        latest = board[dates[-1]]
        board_line = f"{latest['total']} open roles on their careers page, {latest['india']} in India"
        old = [d for d in dates if d <= (today - dt.timedelta(days=21)).isoformat()]
        if old:
            then = board[old[-1]]["total"]
            change = latest["total"] - then
            if then and abs(change) / then >= 0.15:
                board_line += f" ({'up' if change > 0 else 'down'} {abs(change)} in 3 weeks)"
    return {"label": label, "tone": tone, "detail": detail, "board": board_line, "recent": recent}
